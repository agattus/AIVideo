"""Per-scene image aptness scoring and single-regen quality gate."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from config.settings import get_settings
from youtube_pipeline.assets.hitl_workspace import find_scene_image, load_prompts, scene_image_path
from youtube_pipeline.quality.models import ImageReview, QualityReview
from youtube_pipeline.quality.store import load_quality_review, save_quality_review
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

PASSING_SCORE = 3
_MIN_IMAGE_BYTES = 256

VisionFn = Callable[[Mapping[str, Any], Path], int]
TextFn = Callable[[Mapping[str, Any]], int]
ScoreFn = Callable[[Mapping[str, Any], Path | None], int]
RegenerateFn = Callable[[int], None]


def _scene_key(scene_id: int) -> str:
    return str(int(scene_id))


def _image_ready(path: Path | None) -> bool:
    return (
        path is not None
        and path.exists()
        and path.is_file()
        and path.stat().st_size > _MIN_IMAGE_BYTES
    )


def _parse_score(raw: str) -> int:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Score payload must be an object")
    score = payload.get("score")
    if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
        raise ValueError("Score must be an integer from 1 to 5")
    return score


def _aptness_system_prompt() -> str:
    return (
        "You score whether a scene image matches its visual prompt and narration. "
        "Return only JSON: {\"score\": 1} where score is an integer from 1 to 5."
    )


def _aptness_text_prompt(scene: Mapping[str, Any]) -> str:
    return (
        "Score how well the visual prompt fits the narration text.\n"
        f"Visual prompt: {scene.get('visual_prompt', '')}\n"
        f"Narration: {scene.get('script_text', '')}"
    )


def _aptness_vision_prompt(scene: Mapping[str, Any]) -> str:
    return (
        "Score how well this image matches the visual prompt and narration.\n"
        f"Visual prompt: {scene.get('visual_prompt', '')}\n"
        f"Narration excerpt: {scene.get('script_text', '')}"
    )


def _default_text_score(scene: Mapping[str, Any]) -> int:
    from youtube_pipeline.script_engine.generator import ScriptEngine

    engine = ScriptEngine(get_settings())
    llm_call = getattr(engine, "_call_llm", None)
    if llm_call is None:
        return 1
    raw = llm_call(
        _aptness_text_prompt(scene),
        system_prompt=_aptness_system_prompt(),
    )
    try:
        return _parse_score(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 1


def _default_vision_score(scene: Mapping[str, Any], image_path: Path) -> int:
    import google.generativeai as genai

    settings = get_settings()
    api_key = settings.gemini_api_key
    if not api_key:
        return _default_text_score(scene)

    genai.configure(api_key=api_key)
    model_name = settings.llm_model or "gemini-1.5-flash"
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=_aptness_system_prompt(),
        generation_config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )
    image_bytes = image_path.read_bytes()
    response = model.generate_content(
        [
            _aptness_vision_prompt(scene),
            {"mime_type": "image/jpeg", "data": image_bytes},
        ]
    )
    content = getattr(response, "text", None)
    if not content:
        try:
            content = response.candidates[0].content.parts[0].text
        except Exception:  # noqa: BLE001
            return 1
    try:
        return _parse_score(str(content))
    except (TypeError, ValueError, json.JSONDecodeError):
        return 1


def score_scene_aptness(
    scene: Mapping[str, Any],
    image_path: Path | None,
    *,
    vision_fn: VisionFn | None = None,
    text_fn: TextFn | None = None,
) -> int:
    """Score scene/image aptness on a 1–5 scale."""
    if vision_fn is not None:
        if image_path is not None:
            return vision_fn(scene, image_path)
        if text_fn is not None:
            return text_fn(scene)
        return 1
    if text_fn is not None:
        return text_fn(scene)

    settings = get_settings()
    if _image_ready(image_path) and settings.gemini_api_key:
        assert image_path is not None
        return _default_vision_score(scene, image_path)
    return _default_text_score(scene)


def _resolve_scene_image(root: Path, scene_id: int) -> Path | None:
    assets_dir = root / "assets"
    found = find_scene_image(assets_dir, scene_id)
    if found is not None:
        return found
    candidate = scene_image_path(root, scene_id)
    return candidate if _image_ready(candidate) else None


def _default_regenerate(root: Path, scene_id: int) -> None:
    from youtube_pipeline.assets.hitl_workspace import generate_one_scene_image

    generate_one_scene_image(root, scene_id)


def run_image_quality_gate(
    run_dir: Path | str,
    *,
    score_fn: ScoreFn | None = None,
    regenerate_fn: RegenerateFn | None = None,
    persist: bool = True,
) -> ImageReview:
    """Score scene images, regenerate weak scenes once, and merge into quality_review.json."""
    root = Path(run_dir)
    scenes = load_prompts(root).get("scenes") or []

    try:
        quality = load_quality_review(root)
    except FileNotFoundError:
        quality = QualityReview()

    retries = dict(quality.image_review.retries)
    scene_scores: dict[str, Any] = {}
    effective_score = score_fn or (
        lambda scene, image_path: score_scene_aptness(scene, image_path)
    )
    effective_regen = regenerate_fn or (lambda scene_id: _default_regenerate(root, scene_id))

    for scene in scenes:
        scene_id = int(scene["scene_id"])
        sid_key = _scene_key(scene_id)
        image_path = _resolve_scene_image(root, scene_id)
        if not _image_ready(image_path):
            continue

        score = effective_score(scene, image_path)
        scene_scores[sid_key] = {"score": score}

        if score >= PASSING_SCORE:
            continue

        if retries.get(sid_key, 0) == 0:
            effective_regen(scene_id)
            retries[sid_key] = retries.get(sid_key, 0) + 1
            image_path = _resolve_scene_image(root, scene_id)
            score = effective_score(scene, image_path)
            scene_scores[sid_key] = {"score": score}

    failing = [
        sid_key
        for sid_key, payload in scene_scores.items()
        if int(payload.get("score") or 0) < PASSING_SCORE
    ]
    image_review = ImageReview(
        status="pass" if not failing else "needs_approval",
        scenes=scene_scores,
        retries=retries,
    )

    if persist:
        quality.image_review = image_review
        save_quality_review(root, quality)

    return image_review


def maybe_run_image_quality_gate(
    run_dir: Path | str,
    *,
    score_fn: ScoreFn | None = None,
    regenerate_fn: RegenerateFn | None = None,
) -> ImageReview | None:
    """Run the image gate when review is still pending and scene images exist."""
    root = Path(run_dir)
    try:
        quality = load_quality_review(root)
    except FileNotFoundError:
        quality = QualityReview()

    if quality.image_review.status != "pending":
        return None

    scenes = load_prompts(root).get("scenes") or []
    assets_dir = root / "assets"
    has_images = any(
        _image_ready(_resolve_scene_image(root, int(scene["scene_id"])))
        for scene in scenes
    )
    if not has_images:
        return None

    return run_image_quality_gate(
        root,
        score_fn=score_fn,
        regenerate_fn=regenerate_fn,
    )

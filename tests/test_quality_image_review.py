from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from youtube_pipeline.quality.models import QualityReview, ScriptReview, TimingReview


def _jpeg_bytes(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=color).save(buf, format="JPEG")
    return buf.getvalue()


def _scene(scene_id: int = 0) -> dict:
    return {
        "scene_id": scene_id,
        "visual_prompt": f"Visual for scene {scene_id}",
        "script_text": f"Narration for scene {scene_id}",
    }


def _run_dir(tmp_path: Path, *, scenes: int = 2, with_images: bool = True) -> Path:
    run = tmp_path / "run"
    assets = run / "assets"
    assets.mkdir(parents=True)
    payload = {
        "title": "Test",
        "style": "cinematic",
        "aspect_ratio": "16:9",
        "scene_count": scenes,
        "scenes": [
            {
                "scene_number": index + 1,
                "scene_id": index,
                "filename": f"scene_{index:02d}.jpg",
                "visual_prompt": f"Visual {index}",
                "script_text": f"Line {index}",
                "duration_seconds": 3.0,
            }
            for index in range(scenes)
        ],
    }
    run.mkdir(parents=True, exist_ok=True)
    (run / "prompts.json").write_text(json.dumps(payload), encoding="utf-8")
    if with_images:
        for index in range(scenes):
            (assets / f"scene_{index:02d}.jpg").write_bytes(_jpeg_bytes())
    return run


def test_score_scene_aptness_uses_vision_fn_when_image_present() -> None:
    from youtube_pipeline.quality.image_review import score_scene_aptness

    image_path = Path("scene.jpg")
    seen: list[tuple[dict, Path]] = []

    def vision_fn(scene: dict, path: Path) -> int:
        seen.append((dict(scene), path))
        return 4

    score = score_scene_aptness(
        _scene(0),
        image_path,
        vision_fn=vision_fn,
        text_fn=lambda scene: 1,
    )

    assert score == 4
    assert seen == [(_scene(0), image_path)]


def test_score_scene_aptness_falls_back_to_text_fn_without_image() -> None:
    from youtube_pipeline.quality.image_review import score_scene_aptness

    seen: list[dict] = []

    def text_fn(scene: dict) -> int:
        seen.append(dict(scene))
        return 3

    score = score_scene_aptness(
        _scene(1),
        None,
        vision_fn=lambda scene, path: 5,
        text_fn=text_fn,
    )

    assert score == 3
    assert seen == [_scene(1)]


def test_run_image_quality_gate_passes_when_all_scenes_score_high(tmp_path: Path) -> None:
    from youtube_pipeline.quality.image_review import run_image_quality_gate

    run = _run_dir(tmp_path)

    review = run_image_quality_gate(
        run,
        score_fn=lambda scene, image_path: 4,
        regenerate_fn=lambda scene_id: (_ for _ in ()).throw(
            AssertionError(f"unexpected regen for scene {scene_id}")
        ),
    )

    assert review.status == "pass"
    assert review.retries == {}
    assert review.scenes == {"0": {"score": 4}, "1": {"score": 4}}


def test_run_image_quality_gate_regens_weak_scene_once_then_passes(tmp_path: Path) -> None:
    from youtube_pipeline.quality.image_review import run_image_quality_gate

    run = _run_dir(tmp_path, scenes=1)
    scores = iter([2, 4])
    regen_calls: list[int] = []

    review = run_image_quality_gate(
        run,
        score_fn=lambda scene, image_path: next(scores),
        regenerate_fn=lambda scene_id: regen_calls.append(scene_id),
    )

    assert review.status == "pass"
    assert regen_calls == [0]
    assert review.retries == {"0": 1}
    assert review.scenes["0"]["score"] == 4


def test_run_image_quality_gate_regens_once_then_needs_approval(tmp_path: Path) -> None:
    from youtube_pipeline.quality.image_review import run_image_quality_gate

    run = _run_dir(tmp_path, scenes=1)
    regen_calls: list[int] = []

    review = run_image_quality_gate(
        run,
        score_fn=lambda scene, image_path: 2,
        regenerate_fn=lambda scene_id: regen_calls.append(scene_id),
    )

    assert review.status == "needs_approval"
    assert regen_calls == [0]
    assert review.retries == {"0": 1}
    assert review.scenes["0"]["score"] == 2


def test_run_image_quality_gate_skips_scenes_without_images(tmp_path: Path) -> None:
    from youtube_pipeline.quality.image_review import run_image_quality_gate

    run = _run_dir(tmp_path, scenes=2, with_images=False)
    (run / "assets" / "scene_00.jpg").write_bytes(_jpeg_bytes())

    review = run_image_quality_gate(
        run,
        score_fn=lambda scene, image_path: 5,
        regenerate_fn=lambda scene_id: (_ for _ in ()).throw(
            AssertionError("unexpected regen")
        ),
    )

    assert review.status == "pass"
    assert review.scenes == {"0": {"score": 5}}


def test_run_image_quality_gate_merges_without_wiping_other_stages(tmp_path: Path) -> None:
    from youtube_pipeline.quality.image_review import run_image_quality_gate
    from youtube_pipeline.quality.store import load_quality_review, save_quality_review

    run = _run_dir(tmp_path, scenes=1)
    save_quality_review(
        run,
        QualityReview(
            script_review=ScriptReview(
                status="needs_approval",
                scores={"hook": 2},
                issues=["low_score:hook"],
                retries=1,
            ),
            timing_review=TimingReview(status="pass", issues=[]),
        ),
    )

    run_image_quality_gate(run, score_fn=lambda scene, image_path: 4)

    loaded = load_quality_review(run)
    assert loaded.script_review.status == "needs_approval"
    assert loaded.script_review.issues == ["low_score:hook"]
    assert loaded.timing_review.status == "pass"
    assert loaded.image_review.status == "pass"
    assert loaded.image_review.scenes == {"0": {"score": 4}}


def test_auto_fill_runs_image_quality_gate(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from config.settings import AssetProvider
    from youtube_pipeline.assets.hitl_workspace import auto_fill_scene_images
    from youtube_pipeline.models import MediaAsset

    run = _run_dir(tmp_path, scenes=1, with_images=False)
    gate_calls: list[Path] = []

    def fake_gate(run_dir, *, score_fn=None, regenerate_fn=None):
        gate_calls.append(Path(run_dir))
        from youtube_pipeline.quality.models import ImageReview

        return ImageReview(status="pass", scenes={"0": {"score": 5}})

    provider = MagicMock()
    provider.name = "gemini_image"

    def fake_fetch(scene, output_dir, *, aspect_ratio="16:9"):
        dest = Path(output_dir) / "raw.jpg"
        dest.write_bytes(_jpeg_bytes())
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(dest),
            source="gemini_image",
            media_type="image",
        )

    provider.fetch_for_scene.side_effect = fake_fetch

    with (
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=SimpleNamespace(asset_provider=AssetProvider.GEMINI_IMAGE),
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
            return_value=provider,
        ),
        patch(
            "youtube_pipeline.quality.image_review.maybe_run_image_quality_gate",
            side_effect=fake_gate,
        ),
    ):
        result = auto_fill_scene_images(run)

    assert gate_calls == [run]
    assert result["image_review"]["status"] == "pass"


def test_workspace_status_lazy_runs_pending_image_gate(tmp_path: Path) -> None:
    from youtube_pipeline.assets.hitl_workspace import workspace_status
    from youtube_pipeline.quality.store import save_quality_review

    run = _run_dir(tmp_path, scenes=1)
    save_quality_review(run, QualityReview())
    gate_calls: list[Path] = []

    def fake_gate(run_dir, *, score_fn=None, regenerate_fn=None):
        gate_calls.append(Path(run_dir))
        from youtube_pipeline.quality.models import ImageReview

        return ImageReview(status="needs_approval", scenes={"0": {"score": 2}}, retries={"0": 1})

    with patch(
        "youtube_pipeline.quality.image_review.maybe_run_image_quality_gate",
        side_effect=fake_gate,
    ):
        workspace_status(run, job_id="job-1")

    assert gate_calls == [run]

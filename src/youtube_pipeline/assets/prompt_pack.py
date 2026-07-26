"""Export per-scene visual prompts for manual image generation + re-upload."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from youtube_pipeline.assets.aspect import (
    dimensions_for_aspect,
    label_for_aspect,
    normalize_aspect_ratio,
)
from youtube_pipeline.assets.provider import AssetService
from youtube_pipeline.models import SceneData, VideoScript
from youtube_pipeline.utils.files import ensure_dir, write_json
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


def scene_image_name(scene_id: int) -> str:
    return f"scene_{int(scene_id):02d}.jpg"


def write_visual_prompt_pack(
    run_dir: Path | str,
    script: VideoScript,
    *,
    aspect_ratio: str = "16:9",
    style: str | None = None,
    pending_scene_ids: list[int] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Write ``visual_prompts.json`` + ``VISUAL_PROMPTS.md`` under ``run_dir``.

    Users can copy prompts into any image tool, save as ``assets/scene_XX.jpg``,
    then run ``python cli.py continue <run_dir>``.
    """
    root = ensure_dir(Path(run_dir))
    assets_dir = ensure_dir(root / "assets")
    ratio = normalize_aspect_ratio(aspect_ratio)
    width, height = dimensions_for_aspect(ratio)
    style_key = (style or script.style or "cinematic").strip().lower()
    pending = set(pending_scene_ids or [])

    scenes_payload: list[dict[str, Any]] = []
    for scene in script.scenes:
        filename = scene_image_name(scene.scene_id)
        image_path = assets_dir / filename
        prompt = AssetService._style_augmented_prompt(scene.visual_prompt, style_key)
        # Persist a per-scene prompt file for easy copy/paste.
        prompt_file = assets_dir / f"scene_{scene.scene_id:02d}.prompt.txt"
        prompt_file.write_text(prompt + "\n", encoding="utf-8")
        status = "ready"
        if scene.scene_id in pending:
            status = "needs_upload"
        elif not image_path.exists() or image_path.stat().st_size < 256:
            status = "needs_upload"
        elif AssetService._looks_blank_image(image_path):
            status = "needs_upload"

        scenes_payload.append(
            {
                "scene_id": scene.scene_id,
                "filename": filename,
                "relative_path": f"assets/{filename}",
                "prompt_file": f"assets/{prompt_file.name}",
                "visual_prompt": prompt,
                "script_text": scene.script_text,
                "keywords": list(scene.keywords or []),
                "duration_seconds": float(scene.duration or 0.0),
                "status": status,
                "aspect_ratio": ratio,
                "width": width,
                "height": height,
            }
        )

    pack = {
        "title": script.title,
        "style": style_key,
        "aspect_ratio": ratio,
        "aspect_label": label_for_aspect(ratio),
        "width": width,
        "height": height,
        "reason": reason
        or "Generate missing scene images externally, then re-upload to continue.",
        "instructions": [
            f"Generate each image at {ratio} ({width}x{height}) — {label_for_aspect(ratio)}.",
            "Save files exactly as assets/scene_XX.jpg (zero-padded scene id).",
            "Replace any blank/black placeholders.",
            f"Then run: python cli.py continue \"{root}\"",
        ],
        "scenes": scenes_payload,
        "pending_scene_ids": sorted(
            s["scene_id"] for s in scenes_payload if s["status"] == "needs_upload"
        ),
    }
    json_path = root / "visual_prompts.json"
    md_path = root / "VISUAL_PROMPTS.md"
    write_json(json_path, pack)
    md_path.write_text(_render_markdown(pack), encoding="utf-8")
    logger.info(
        "Visual prompt pack written | pending=%d | json=%s | md=%s",
        len(pack["pending_scene_ids"]),
        json_path,
        md_path,
    )
    return pack


def missing_scene_ids(script: VideoScript, assets_dir: Path | str) -> list[int]:
    """Return scene ids that still need a real non-blank ``scene_XX.jpg``."""
    root = Path(assets_dir)
    missing: list[int] = []
    for scene in script.scenes:
        path = root / scene_image_name(scene.scene_id)
        if not path.exists() or AssetService._looks_blank_image(path):
            missing.append(scene.scene_id)
    return missing


def _render_markdown(pack: dict[str, Any]) -> str:
    lines = [
        f"# Visual prompts — {pack['title']}",
        "",
        f"**Aspect ratio:** `{pack['aspect_ratio']}` — {pack['aspect_label']}",
        f"**Target size:** `{pack['width']}x{pack['height']}`",
        f"**Style:** `{pack['style']}`",
        "",
        f"> {pack['reason']}",
        "",
        "## How to continue",
        "",
    ]
    for i, step in enumerate(pack["instructions"], start=1):
        lines.append(f"{i}. {step}")
    lines.extend(["", "## Scenes", ""])

    pending = set(pack.get("pending_scene_ids") or [])
    for scene in pack["scenes"]:
        flag = "NEEDS UPLOAD" if scene["scene_id"] in pending else "OK"
        lines.extend(
            [
                f"### Scene {scene['scene_id']:02d} — `{scene['filename']}` [{flag}]",
                "",
                f"- Save as: `assets/{scene['filename']}`",
                f"- Size: `{scene['width']}x{scene['height']}` (`{scene['aspect_ratio']}`)",
                f"- Narration: {scene['script_text']}",
                "",
                "```",
                scene["visual_prompt"],
                "```",
                "",
            ]
        )
    return "\n".join(lines)

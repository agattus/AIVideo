"""Export per-scene visual prompts for human-in-the-loop image generation."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from youtube_pipeline.models import VideoScript
from youtube_pipeline.utils.files import ensure_dir


def export_visual_prompts(
    script: VideoScript,
    output_dir: Path | str,
    *,
    aspect_ratio: str = "16:9",
) -> dict[str, Any]:
    """Write ``prompts.json`` + ``prompts.csv`` under ``output_dir``.

    Returns the JSON payload (also written to disk).
    """
    root = ensure_dir(Path(output_dir))
    rows: list[dict[str, Any]] = []
    for scene in script.scenes:
        # scene_number is 1-based for humans; scene_id stays 0-based for files.
        rows.append(
            {
                "scene_number": int(scene.scene_id) + 1,
                "scene_id": int(scene.scene_id),
                "filename": f"scene_{scene.scene_id:02d}.jpg",
                "visual_prompt": scene.visual_prompt,
                "script_text": scene.script_text,
                "duration_seconds": float(scene.duration or 0.0),
                "keywords": list(scene.keywords or []),
                "aspect_ratio": aspect_ratio,
            }
        )

    payload = {
        "title": script.title,
        "style": script.style,
        "aspect_ratio": aspect_ratio,
        "scene_count": len(rows),
        "instructions": [
            f"Generate one image per scene at aspect ratio {aspect_ratio}.",
            "Name files scene_00.jpg, scene_01.jpg, ... (zero-padded scene_id).",
            "Zip the images and upload via POST /api/v1/jobs/{job_id}/upload-assets.",
        ],
        "scenes": rows,
    }

    json_path = root / "prompts.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    csv_path = root / "prompts.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "scene_number",
                "scene_id",
                "filename",
                "aspect_ratio",
                "visual_prompt",
                "script_text",
                "duration_seconds",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "scene_number": row["scene_number"],
                    "scene_id": row["scene_id"],
                    "filename": row["filename"],
                    "aspect_ratio": row["aspect_ratio"],
                    "visual_prompt": row["visual_prompt"],
                    "script_text": row["script_text"],
                    "duration_seconds": row["duration_seconds"],
                }
            )

    readme = root / "PROMPTS_README.txt"
    readme.write_text(
        "\n".join(
            [
                f"Title: {script.title}",
                f"Aspect ratio: {aspect_ratio}",
                f"Scenes: {len(rows)}",
                "",
                "1. Open prompts.csv or prompts.json",
                "2. Generate each visual_prompt in Meta AI / Gemini / any image tool",
                f"3. Save images as scene_00.jpg … scene_{len(rows) - 1:02d}.jpg",
                "4. Zip those images and upload to resume assembly",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload

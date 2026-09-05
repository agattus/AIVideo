"""Reorder whole scenes in a job run directory while keeping stable scene_id assets."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from youtube_pipeline.utils.files import read_json, write_json


def _load_script(run_dir: Path) -> dict[str, Any]:
    for name in ("script_timed.json", "script.json"):
        path = run_dir / name
        if path.exists():
            return read_json(path)
    raise FileNotFoundError(f"No script.json in {run_dir}")


def _scene_block_duration(block: dict[str, Any]) -> float:
    if block.get("duration") is not None:
        return float(block["duration"])
    return float(block.get("speech_duration") or 0) + float(block.get("pause_after") or 0)


def _validate_permutation(existing_ids: set[int], scene_ids: list[int]) -> None:
    if set(scene_ids) != existing_ids or len(scene_ids) != len(existing_ids):
        raise ValueError(
            "scene_ids must be a full permutation of existing scene ids "
            f"(expected {sorted(existing_ids)}, got {scene_ids})"
        )


def _retime_scenes(timing: dict[str, Any], scene_ids: list[int]) -> dict[str, Any]:
    by_id = {int(block["scene_id"]): block for block in timing.get("scenes") or []}
    cursor = 0.0
    new_scenes: list[dict[str, Any]] = []
    for scene_id in scene_ids:
        block = dict(by_id[scene_id])
        duration = _scene_block_duration(block)
        block["start"] = cursor
        block["end"] = cursor + duration
        block["duration"] = duration
        new_scenes.append(block)
        cursor += duration
    updated = dict(timing)
    updated["scenes"] = new_scenes
    updated["total_duration"] = cursor
    return updated


def reorder_scenes(run_dir: Path, scene_ids: list[int]) -> dict[str, Any]:
    """Permute scenes in script and timing artifacts; asset filenames stay keyed by scene_id."""
    root = Path(run_dir)
    script = _load_script(root)
    scenes = script.get("scenes") or []
    by_id = {int(scene["scene_id"]): scene for scene in scenes}
    existing_ids = set(by_id)
    _validate_permutation(existing_ids, scene_ids)

    new_scenes = [by_id[scene_id] for scene_id in scene_ids]
    script["scenes"] = new_scenes
    script["full_script"] = " ".join(str(scene.get("script_text") or "") for scene in new_scenes).strip()

    write_json(root / "script.json", script)
    write_json(root / "script_timed.json", script)

    timing_path = root / "timing.json"
    if timing_path.exists():
        timing = _retime_scenes(read_json(timing_path), scene_ids)
        write_json(timing_path, timing)

    return {"scene_ids": list(scene_ids), "scene_count": len(scene_ids)}

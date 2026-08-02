"""Derive and publish in-progress assemble scene counts for the Studio UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


def count_finished_clips(run_dir: Path | str | None) -> int:
    """Count completed scene clips under ``run_dir/_ffmpeg_work``."""
    if not run_dir:
        return 0
    work = Path(run_dir) / "_ffmpeg_work"
    if not work.is_dir():
        return 0
    count = 0
    for path in work.glob("clip_*.mp4"):
        name = path.name.lower()
        if "_base" in name or name.startswith("video_"):
            continue
        try:
            if path.stat().st_size > 1024:
                count += 1
        except OSError:
            continue
    return count


def resolve_scene_total(run_dir: Path | str | None, fallback: int | None = None) -> int:
    if fallback and int(fallback) > 0:
        return int(fallback)
    if not run_dir:
        return 0
    root = Path(run_dir)
    for name in ("script_timed.json", "script.json", "prompts.json"):
        path = root / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if name == "prompts.json":
            total = int(data.get("scene_count") or 0)
            if total > 0:
                return total
        scenes = data.get("scenes")
        if isinstance(scenes, list) and scenes:
            return len(scenes)
    return 0


def assemble_phase(run_dir: Path | str | None) -> str:
    """Return a coarse assemble phase for messaging."""
    if not run_dir:
        return "checking"
    work = Path(run_dir) / "_ffmpeg_work"
    if (work / "video_silent.mp4").exists():
        return "muxing"
    if count_finished_clips(run_dir) > 0:
        return "rendering"
    return "checking"


def friendly_assemble_stage(done: int, total: int, *, phase: str | None = None) -> str:
    phase = phase or "rendering"
    if phase == "muxing":
        return "Mixing voice, music, and sound…"
    if phase == "checking" and done <= 0:
        return "Checking your scene images…"
    if total > 0:
        shown = min(done, total)
        return f"Rendering scene {shown} of {total}…"
    if done > 0:
        return f"Rendering scene {done}…"
    return "Assembling your film…"


def progress_percent_for_clips(done: int, total: int, *, phase: str | None = None) -> int:
    """Map clip progress onto the assemble band (80–95%)."""
    phase = phase or "rendering"
    if phase == "muxing":
        return 94
    if total <= 0:
        return 82
    ratio = max(0.0, min(1.0, done / float(total)))
    return 80 + int(14 * ratio)


def build_assemble_progress(
    run_dir: Path | str | None,
    *,
    scene_count: int | None = None,
) -> dict[str, Any] | None:
    total = resolve_scene_total(run_dir, scene_count)
    done = count_finished_clips(run_dir)
    phase = assemble_phase(run_dir)
    if done <= 0 and phase == "checking":
        return None
    return {
        "scenes_done": done,
        "scenes_total": total,
        "phase": phase,
        "current_stage": friendly_assemble_stage(done, total, phase=phase),
        "progress_percent": progress_percent_for_clips(done, total, phase=phase),
    }


def write_assemble_progress_file(
    static_dir: Path | str,
    job_id: str,
    payload: dict[str, Any] | None,
) -> Path | None:
    """Write ``static/{job_id}/assemble_progress.json`` for the UI to poll."""
    if not payload:
        return None
    dest_dir = Path(static_dir) / job_id
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / "assemble_progress.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path
    except OSError as exc:
        logger.warning("Could not write assemble progress | job_id=%s | %s", job_id, exc)
        return None


def enrich_job_status_payload(
    state: Any,
    *,
    static_dir: Path | str | None = None,
) -> Any:
    """Overlay live clip counts onto a JobStatusResponse while processing."""
    status_value = getattr(state, "status", None)
    status_text = status_value.value if hasattr(status_value, "value") else str(status_value or "")
    if status_text != "processing":
        return state

    run_dir = getattr(state, "run_dir", None)
    scene_count = getattr(state, "scene_count", None)
    progress = build_assemble_progress(run_dir, scene_count=scene_count)
    if not progress:
        return state

    if static_dir is not None and getattr(state, "job_id", None):
        write_assemble_progress_file(static_dir, str(state.job_id), progress)

    updates = {
        "current_stage": progress["current_stage"],
        "progress_percent": max(
            int(getattr(state, "progress_percent", 0) or 0),
            int(progress["progress_percent"]),
        ),
        "scene_count": progress["scenes_total"] or scene_count,
        "scenes_done": progress["scenes_done"],
        "scenes_total": progress["scenes_total"] or scene_count,
    }
    try:
        return state.model_copy(update=updates)
    except Exception:  # noqa: BLE001
        return state

"""Pad quiz question scenes so viewers get think-time before the answer reveal."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from youtube_pipeline.content_types import DEFAULT_QUESTION_HOLD_SECONDS
from youtube_pipeline.models import SceneData, VideoScript
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


def _resolve_ffmpeg() -> str:
    which = shutil.which("ffmpeg")
    if which:
        return which
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"ffmpeg not found for quiz hold padding: {exc}") from exc


def _is_question_scene(scene: SceneData) -> bool:
    phase = (scene.phase or "").strip().lower()
    return phase == "question"


def apply_quiz_holds(
    script: VideoScript,
    audio_path: Path | str,
    timing: dict[str, Any],
    *,
    default_hold: float = DEFAULT_QUESTION_HOLD_SECONDS,
) -> tuple[VideoScript, Path, dict[str, Any], float]:
    """Ensure each question scene lasts at least ``hold_seconds`` by inserting silence.

    Returns (updated_script, audio_path, updated_timing, new_total_duration).
    If no padding is needed, returns the inputs unchanged.
    """
    audio_file = Path(audio_path)
    scenes = list(script.scenes)
    if not scenes or not audio_file.exists():
        return script, audio_file, timing, float(sum(s.duration for s in scenes))

    pads: list[tuple[int, float]] = []  # (scene_index, pad_seconds)
    for idx, scene in enumerate(scenes):
        if not _is_question_scene(scene):
            continue
        hold = float(scene.hold_seconds if scene.hold_seconds is not None else default_hold)
        hold = max(3.0, min(30.0, hold))
        current = max(0.2, float(scene.duration or 0.0))
        if current + 0.05 < hold:
            pads.append((idx, hold - current))

    if not pads:
        total = float(sum(max(0.2, float(s.duration or 0.0)) for s in scenes))
        return script, audio_file, timing, total

    logger.info(
        "Padding quiz question holds | pads=%s | audio=%s",
        [(i, round(p, 2)) for i, p in pads],
        audio_file,
    )

    # Build scene start/end from current durations.
    starts: list[float] = []
    cursor = 0.0
    for scene in scenes:
        starts.append(cursor)
        cursor += max(0.2, float(scene.duration or 0.0))
    ends = [starts[i] + max(0.2, float(scenes[i].duration or 0.0)) for i in range(len(scenes))]

    ffmpeg = _resolve_ffmpeg()
    work = Path(tempfile.mkdtemp(prefix="quiz_hold_"))
    try:
        parts: list[Path] = []
        part_idx = 0
        timeline = 0.0
        new_scenes: list[SceneData] = []
        pad_by_index = {i: p for i, p in pads}

        for idx, scene in enumerate(scenes):
            seg_start = starts[idx]
            seg_end = ends[idx]
            seg_dur = max(0.05, seg_end - seg_start)
            spoken = work / f"spoken_{part_idx:03d}.mp3"
            _cut_audio(ffmpeg, audio_file, spoken, seg_start, seg_dur)
            parts.append(spoken)
            part_idx += 1

            new_dur = seg_dur
            pad = pad_by_index.get(idx)
            if pad and pad > 0.05:
                silence = work / f"silence_{part_idx:03d}.mp3"
                _make_silence(ffmpeg, silence, pad)
                parts.append(silence)
                part_idx += 1
                new_dur = seg_dur + pad

            new_scenes.append(scene.model_copy(update={"duration": round(new_dur, 3)}))
            timeline += new_dur

        concat_list = work / "concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{p.resolve()}'" for p in parts) + "\n",
            encoding="utf-8",
        )
        out_audio = audio_file.with_name(audio_file.stem + "_quizpad.mp3")
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(out_audio),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not out_audio.exists():
            logger.warning(
                "Quiz hold concat failed — keeping original audio | stderr=%s",
                (proc.stderr or "")[-400:],
            )
            total = float(sum(max(0.2, float(s.duration or 0.0)) for s in scenes))
            return script, audio_file, timing, total

        # Replace original voiceover so downstream paths stay stable.
        shutil.move(str(out_audio), str(audio_file))

        # Rebuild simple timing dictionary from new durations.
        new_timing = _rebuild_timing(new_scenes, timing)
        updated = script.model_copy(update={"scenes": new_scenes})
        return updated, audio_file, new_timing, timeline
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _cut_audio(ffmpeg: str, src: Path, dest: Path, start: float, duration: float) -> None:
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{max(0.0, start):.3f}",
        "-t",
        f"{max(0.05, duration):.3f}",
        "-i",
        str(src),
        "-acodec",
        "libmp3lame",
        "-q:a",
        "4",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError(f"ffmpeg cut failed: {(proc.stderr or '')[-300:]}")


def _make_silence(ffmpeg: str, dest: Path, seconds: float) -> None:
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=24000:cl=mono",
        "-t",
        f"{max(0.05, seconds):.3f}",
        "-q:a",
        "9",
        "-acodec",
        "libmp3lame",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError(f"ffmpeg silence failed: {(proc.stderr or '')[-300:]}")


def _rebuild_timing(scenes: list[SceneData], old_timing: dict[str, Any]) -> dict[str, Any]:
    cursor = 0.0
    scene_rows: list[dict[str, Any]] = []
    for scene in scenes:
        dur = max(0.2, float(scene.duration or 0.0))
        scene_rows.append(
            {
                "scene_id": scene.scene_id,
                "start": round(cursor, 3),
                "end": round(cursor + dur, 3),
                "duration": round(dur, 3),
                "phase": scene.phase,
            }
        )
        cursor += dur
    return {
        "words": list((old_timing or {}).get("words") or []),
        "scenes": scene_rows,
        "total_duration": round(cursor, 3),
        "quiz_holds_applied": True,
    }

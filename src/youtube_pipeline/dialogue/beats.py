"""Expand normalized dialogue into visual beat scenes."""

from __future__ import annotations

from typing import Any

from youtube_pipeline.dialogue.casting import _cast_ids
from youtube_pipeline.models import SceneData


def _normalize_lines(
    cast: list[dict[str, Any]],
    lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cast_ids = _cast_ids(cast)
    names = {
        cast_id: str(member.get("name") or "").strip()
        for cast_id, member in zip(cast_ids, cast, strict=True)
    }
    normalized: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        speaker_id = str(line.get("speaker_id") or "").strip()
        if speaker_id not in names:
            raise ValueError(
                f"Dialogue line {index} speaker_id {speaker_id!r} is not in cast"
            )
        text = str(line.get("text") or "").strip()
        if not text:
            raise ValueError(f"Dialogue line {index} must have non-empty text")
        normalized.append(
            {
                **line,
                "speaker_id": speaker_id,
                "speaker_name": names[speaker_id],
                "text": text,
            }
        )
    if not normalized:
        raise ValueError("Dialogue lines must not be empty")
    return normalized


def _validate_coverage(
    visual_beats: list[dict[str, Any]],
    line_count: int,
) -> None:
    if not visual_beats:
        raise ValueError("Visual beats must cover all dialogue lines")

    next_line = 0
    for beat_index, beat in enumerate(visual_beats):
        line_start = beat.get("line_start")
        line_end = beat.get("line_end")
        if not isinstance(line_start, int) or not isinstance(line_end, int):
            raise ValueError(f"Visual beat {beat_index} line range must use integers")
        if line_start < next_line:
            raise ValueError(f"Visual beat {beat_index} overlaps a previous beat")
        if line_start > next_line:
            raise ValueError(f"Visual beats do not cover line {next_line}")
        if line_end < line_start:
            raise ValueError(f"Visual beat {beat_index} has an invalid line range")
        if line_end >= line_count:
            raise ValueError(f"Visual beat {beat_index} exceeds dialogue lines")
        next_line = line_end + 1

    if next_line != line_count:
        raise ValueError(f"Visual beats do not cover line {next_line}")


def expand_dialogue_script(
    *,
    cast: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    visual_beats: list[dict[str, Any]],
    language: str = "en",
) -> tuple[list[SceneData], list[dict[str, Any]]]:
    """Return HITL visual scenes and lines enriched with cast display names."""
    del language  # Reserved for language-specific dialogue expansion.
    normalized_lines = _normalize_lines(cast, lines)
    _validate_coverage(visual_beats, len(normalized_lines))

    scenes: list[SceneData] = []
    for scene_id, beat in enumerate(visual_beats):
        line_start = beat["line_start"]
        line_end = beat["line_end"]
        beat_lines = normalized_lines[line_start : line_end + 1]
        speakers = {line["speaker_id"] for line in beat_lines}
        single_speaker = next(iter(speakers)) if len(speakers) == 1 else None
        scenes.append(
            SceneData(
                scene_id=scene_id,
                script_text="\n".join(line["text"] for line in beat_lines),
                visual_prompt=str(beat.get("visual_prompt") or "").strip(),
                speaker_id=single_speaker,
                speaker_name=(
                    beat_lines[0]["speaker_name"] if single_speaker is not None else ""
                ),
                line_start=line_start,
                line_end=line_end,
            )
        )

    return scenes, normalized_lines

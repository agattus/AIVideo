"""Filter-graph builder for mixing scene ambience and one-shot SFX under narration."""

from __future__ import annotations

from pathlib import Path

from youtube_pipeline.models import SceneData

__all__ = ["build_sfx_filter_complex"]

_VO_VOLUME = 1.05
_BGM_VOLUME = 0.10
_AMBIENCE_VOLUME = 0.12
_ONESHOT_VOLUME = 0.35
_FADE_SECONDS = 0.15


def _fade_suffix(duration: float) -> str:
    """Short in/out fade so looped ambience segments don't click at cut points."""
    if duration <= _FADE_SECONDS * 2:
        return ""
    fade_out_start = max(0.0, duration - _FADE_SECONDS)
    return f",afade=t=in:st=0:d={_FADE_SECONDS:.3f},afade=t=out:st={fade_out_start:.3f}:d={_FADE_SECONDS:.3f}"


def build_sfx_filter_complex(
    *,
    scene_durations: list[float],
    scenes: list[SceneData],
    has_bgm: bool,
    ambience_inputs: list[tuple[int, Path]],
    oneshot_inputs: list[tuple[int, Path, float]],
) -> str:
    """Return a ``-filter_complex`` string ending with a mixed ``[a]`` audio bus.

    Input layout assumed by the caller: ``0`` = video, ``1`` = voiceover,
    ``2`` = bgm (only when ``has_bgm``), followed by the ambience and one-shot
    inputs in the order given here.

    ``ambience_inputs`` pairs each ffmpeg ``-i`` index with its resolved
    ambience file, in the same order as ``scenes`` filtered to those whose
    ``ambience`` tag is not ``"none"`` (scenes with an unresolved/missing
    ambience file are simply absent from this list, so the Nth entry lines up
    positionally with the Nth such scene). Scene start/duration are looked up
    via ``scene_durations`` for that scene index.

    ``oneshot_inputs`` carries a precomputed absolute ``delay_ms`` per cue, so
    no scene lookup is needed for one-shots.
    """
    starts: list[float] = []
    cursor = 0.0
    for duration in scene_durations:
        starts.append(cursor)
        cursor += duration

    ambience_scene_indices = [
        index for index, scene in enumerate(scenes) if scene.ambience != "none"
    ]

    parts: list[str] = [f"[1:a]volume={_VO_VOLUME}[vo]"]
    bus_labels: list[str] = ["[vo]"]

    if has_bgm:
        parts.append(f"[2:a]aloop=loop=-1:size=2e+09,volume={_BGM_VOLUME}[bg]")
        bus_labels.append("[bg]")

    amb_labels: list[str] = []
    for position, (input_index, _path) in enumerate(ambience_inputs):
        if position >= len(ambience_scene_indices):
            break
        scene_index = ambience_scene_indices[position]
        duration = scene_durations[scene_index] if scene_index < len(scene_durations) else 0.0
        start_ms = int(round(starts[scene_index] * 1000))
        label = f"amb{position}"
        parts.append(
            f"[{input_index}:a]aloop=loop=-1:size=2e+09,atrim=0:{duration:.3f},"
            f"asetpts=PTS-STARTPTS{_fade_suffix(duration)},"
            f"adelay={start_ms}:all=1,volume={_AMBIENCE_VOLUME}[{label}]"
        )
        amb_labels.append(f"[{label}]")

    if len(amb_labels) == 1:
        bus_labels.append(amb_labels[0])
    elif amb_labels:
        parts.append(
            "".join(amb_labels)
            + f"amix=inputs={len(amb_labels)}:duration=longest:dropout_transition=0[ambmix]"
        )
        bus_labels.append("[ambmix]")

    shot_labels: list[str] = []
    for position, (input_index, _path, delay_ms) in enumerate(oneshot_inputs):
        label = f"shot{position}"
        parts.append(
            f"[{input_index}:a]adelay={int(round(delay_ms))}:all=1,"
            f"volume={_ONESHOT_VOLUME}[{label}]"
        )
        shot_labels.append(f"[{label}]")

    if len(shot_labels) == 1:
        bus_labels.append(shot_labels[0])
    elif shot_labels:
        parts.append(
            "".join(shot_labels)
            + f"amix=inputs={len(shot_labels)}:duration=longest:dropout_transition=0[shotmix]"
        )
        bus_labels.append("[shotmix]")

    parts.append(
        "".join(bus_labels)
        + f"amix=inputs={len(bus_labels)}:duration=first:dropout_transition=2[a]"
    )
    return ";".join(parts)

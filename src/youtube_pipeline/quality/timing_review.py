"""Deterministic timing checks after TTS."""

from __future__ import annotations

from youtube_pipeline.models import VideoScript
from youtube_pipeline.quality.models import TimingReview

DURATION_DRIFT_TOLERANCE = 0.35
WORD_SPAN_MIN_FRACTION = 0.85


def review_timing(
    *,
    script: VideoScript,
    timing: dict,
    duration_seconds: float,
    target_duration_seconds: int | None,
) -> TimingReview:
    """Run deterministic timing sanity checks on TTS output."""
    issues: list[str] = []

    if target_duration_seconds is not None and target_duration_seconds > 0:
        drift = abs(duration_seconds - target_duration_seconds) / target_duration_seconds
        if drift > DURATION_DRIFT_TOLERANCE:
            issues.append(
                "duration_drift:"
                f"{duration_seconds:.2f}s vs target {target_duration_seconds}s"
            )

    for scene in timing.get("scenes") or []:
        scene_duration = float(scene.get("duration") or 0.0)
        if scene_duration <= 0:
            scene_id = scene.get("scene_id", "?")
            issues.append(f"zero_scene_duration:scene_{scene_id}")

    if script.format == "dialogue" and len(script.scenes) != len(script.lines):
        issues.append(
            "dialogue_scene_line_mismatch:"
            f"{len(script.scenes)} scenes vs {len(script.lines)} lines"
        )

    words = timing.get("words") or []
    if words:
        last_end = float(words[-1].get("end") or 0.0)
        minimum_end = WORD_SPAN_MIN_FRACTION * duration_seconds
        if last_end < minimum_end:
            issues.append(
                "word_span_short:"
                f"last word ends at {last_end:.2f}s, expected >= {minimum_end:.2f}s"
            )

    if issues:
        return TimingReview(status="needs_approval", issues=issues)
    return TimingReview(status="pass", issues=[])

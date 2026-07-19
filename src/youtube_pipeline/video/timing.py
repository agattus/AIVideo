"""Helpers for inspecting timed VideoScript scenes."""

from __future__ import annotations

from youtube_pipeline.models import VideoScript
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


def scene_timeline(script: VideoScript) -> list[dict[str, float | int]]:
    """Build a contiguous timeline from already-populated scene durations.

    TTS is responsible for writing ``SceneData.duration``. This helper is useful
    for debugging and intermediate JSON artifacts.
    """
    cursor = 0.0
    timeline: list[dict[str, float | int]] = []
    for scene in script.scenes:
        duration = max(0.05, float(scene.duration))
        start = cursor
        end = cursor + duration
        timeline.append(
            {
                "scene_id": scene.scene_id,
                "start": start,
                "end": end,
                "duration": duration,
            }
        )
        cursor = end

    logger.info(
        "Scene timeline ready | scenes=%d | total=%.2fs",
        len(timeline),
        cursor,
    )
    return timeline

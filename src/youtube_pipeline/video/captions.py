"""Styled burned-in caption overlays."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from moviepy import CompositeVideoClip, TextClip, VideoClip

from youtube_pipeline.models import SubtitleCue, VisualStyle
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


# Prefer expressive fonts when present; TextClip falls back gracefully.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _resolve_font() -> str | None:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def style_for(visual_style: VisualStyle) -> dict:
    """Caption look tuned lightly per visual style."""
    base = {
        "font_size": 54,
        "color": "white",
        "stroke_color": "black",
        "stroke_width": 2,
        "method": "caption",
        "text_align": "center",
    }
    if visual_style == VisualStyle.FAST_PACED_SHORTS:
        return {**base, "font_size": 64, "stroke_width": 3}
    if visual_style == VisualStyle.MINIMAL:
        return {**base, "font_size": 48, "stroke_width": 1}
    if visual_style == VisualStyle.CORPORATE:
        return {**base, "font_size": 50, "color": "#F5F7FA", "stroke_width": 2}
    return base


def burn_captions(
    video: VideoClip,
    cues: Sequence[SubtitleCue],
    *,
    visual_style: VisualStyle,
    bottom_margin: int = 80,
    vertical_ratio: float = 0.75,
) -> VideoClip:
    """Composite short caption clips over the base video timeline.

    Captions are centered around ``vertical_ratio`` from the top (default 3/4)
    so they stay readable above the bottom edge / player chrome.
    """
    if not cues:
        return video

    font = _resolve_font()
    style = style_for(visual_style)
    caption_clips: list[TextClip] = []
    max_width = int(video.w * 0.85)

    for cue in cues:
        duration = max(0.2, cue.end - cue.start)
        try:
            kwargs: dict = {
                "text": cue.text,
                "font_size": style["font_size"],
                "color": style["color"],
                "stroke_color": style["stroke_color"],
                "stroke_width": style["stroke_width"],
                "method": style["method"],
                "text_align": style["text_align"],
                "size": (max_width, None),
                "duration": duration,
            }
            if font:
                kwargs["font"] = font
            txt = TextClip(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping caption cue %s: %s", cue.index, exc)
            continue

        ratio = min(0.92, max(0.35, float(vertical_ratio)))
        y = int(round(video.h * ratio - txt.h / 2))
        y = max(8, min(y, video.h - txt.h - max(8, bottom_margin // 4)))
        txt = txt.with_start(cue.start).with_position(("center", y))
        caption_clips.append(txt)

    if not caption_clips:
        return video

    logger.info("Burning %d caption clips", len(caption_clips))
    return CompositeVideoClip([video, *caption_clips])

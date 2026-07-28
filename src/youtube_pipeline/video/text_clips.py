"""Portable Pillow-based caption clips (no ImageMagick required)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

import numpy as np
from moviepy import ImageClip
from PIL import Image, ImageDraw, ImageFont

from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

_CLAUSE_SPLIT_RE = re.compile(r"(?<=[,:;!?])\s+|(?<=\.)\s+")

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def resolve_font_path(preferred: str | None = None) -> str | None:
    """Return the first usable TrueType font path, if any."""
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    candidates.extend(_FONT_CANDIDATES)
    for path in candidates:
        if path and Path(path).exists():
            return path
    return None


def _load_font(font_size: int, font_path: str | None = None) -> ImageFont.ImageFont:
    path = resolve_font_path(font_path)
    if path:
        try:
            return ImageFont.truetype(path, font_size)
        except OSError as exc:
            logger.warning("Failed loading font %s (%s); using default bitmap font", path, exc)
    return ImageFont.load_default()


def wrap_text_to_width(
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """Word-wrap ``text`` so each line fits within ``max_width`` pixels."""
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render_caption_rgba(
    text: str,
    *,
    size: tuple[int, int],
    font_size: int = 52,
    font_path: str | None = None,
    text_color: tuple[int, int, int, int] = (255, 255, 255, 255),
    stroke_color: tuple[int, int, int, int] = (0, 0, 0, 230),
    stroke_width: int = 3,
    padding_x: int = 24,
    padding_y: int = 16,
    max_lines: int = 2,
    vertical_ratio: float = 0.75,
) -> np.ndarray:
    """Render caption text onto a transparent RGBA numpy frame.

    ``vertical_ratio`` places the text block around that fraction from the top
    (default ``0.75`` = three-quarters down — readable above the bottom edge).
    """
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid caption size: {size}")

    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return np.zeros((height, width, 4), dtype=np.uint8)

    font = _load_font(font_size, font_path)
    # Scratch image used only for measuring text.
    measure = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(measure)
    max_text_width = max(8, width - (padding_x * 2))
    lines = wrap_text_to_width(cleaned, font, max_text_width, draw)[:max_lines]

    # Measure block size.
    line_sizes: list[tuple[int, int]] = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        line_sizes.append((bbox[2] - bbox[0], bbox[3] - bbox[1]))

    line_gap = max(4, font_size // 6)
    block_w = max((w for w, _ in line_sizes), default=0) + padding_x * 2
    block_h = sum(h for _, h in line_sizes) + line_gap * max(0, len(lines) - 1) + padding_y * 2
    block_w = min(width, max(1, block_w))
    block_h = min(height, max(1, block_h))

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas_draw = ImageDraw.Draw(canvas)

    # Soft dark pill behind text for readability on bright footage.
    ratio = min(0.92, max(0.35, float(vertical_ratio)))
    # Center the caption block on the target ratio from the top.
    y0 = int(round(height * ratio - block_h / 2))
    y0 = max(padding_y, min(y0, height - block_h - padding_y))
    x0 = (width - block_w) // 2
    x1 = x0 + block_w
    y1 = min(height, y0 + block_h)
    canvas_draw.rounded_rectangle(
        [x0, y0, x1, y1],
        radius=min(18, block_h // 3),
        fill=(0, 0, 0, 140),
    )

    y = y0 + padding_y
    for line, (line_w, line_h) in zip(lines, line_sizes, strict=True):
        x = (width - line_w) // 2
        canvas_draw.text(
            (x, y),
            line,
            font=font,
            fill=text_color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
        )
        y += line_h + line_gap

    return np.array(canvas)


def create_caption_clip(
    text: str,
    duration: float,
    size: tuple[int, int],
    font_size: int = 52,
    *,
    font_path: str | None = None,
    transparent: bool = True,
) -> ImageClip:
    """Create a MoviePy caption clip using Pillow — no ImageMagick needed.

    Parameters
    ----------
    text:
        Caption phrase to render (may include spaces; wrapping is automatic).
    duration:
        Seconds the caption remains on screen.
    size:
        ``(width, height)`` of the transparent overlay frame. Typically the
        full video frame size so positioning can stay at ``("center", "bottom")``.
    font_size:
        Point size for the TrueType font.
    """
    if duration <= 0:
        raise ValueError("Caption duration must be > 0")

    frame = render_caption_rgba(
        text,
        size=size,
        font_size=font_size,
        font_path=font_path,
    )
    clip = ImageClip(frame, is_mask=False, transparent=transparent).with_duration(duration)
    return clip


def split_script_into_phrases(
    text: str,
    *,
    scene_duration: float,
    max_chars: int = 42,
    max_words: int = 6,
    min_phrase_seconds: float = 1.1,
    max_phrase_seconds: float = 3.2,
) -> list[tuple[str, float]]:
    """Split scene narration into punchy caption phrases with per-phrase durations.

    Returns a list of ``(phrase, duration_seconds)`` whose durations sum to
    approximately ``scene_duration``.
    """
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return []

    scene_duration = max(0.2, float(scene_duration))

    # Prefer clause/sentence boundaries, then pack into short word groups.
    clauses = [part.strip() for part in _CLAUSE_SPLIT_RE.split(cleaned) if part and part.strip()]
    if not clauses:
        clauses = [cleaned]

    phrases: list[str] = []
    for clause in clauses:
        words = clause.split()
        bucket: list[str] = []
        for word in words:
            tentative = bucket + [word]
            candidate = " ".join(tentative)
            if bucket and (len(tentative) > max_words or len(candidate) > max_chars):
                phrases.append(" ".join(bucket))
                bucket = [word]
            else:
                bucket = tentative
        if bucket:
            phrases.append(" ".join(bucket))

    if not phrases:
        phrases = [cleaned]

    # Merge adjacent ultra-short fragments when we over-split.
    merged: list[str] = []
    i = 0
    while i < len(phrases):
        if (
            i + 1 < len(phrases)
            and len(phrases[i].split()) <= 2
            and len((phrases[i] + " " + phrases[i + 1]).split()) <= max_words
        ):
            merged.append(f"{phrases[i]} {phrases[i + 1]}")
            i += 2
        else:
            merged.append(phrases[i])
            i += 1
    phrases = merged

    weights = [max(1, len(p.split())) for p in phrases]
    total_weight = float(sum(weights))
    raw = [scene_duration * (w / total_weight) for w in weights]

    # Clamp extreme phrase lengths, then renormalize to scene_duration.
    clamped = [min(max_phrase_seconds, max(min_phrase_seconds, d)) for d in raw]
    scale = scene_duration / sum(clamped) if sum(clamped) > 0 else 1.0
    durations = [d * scale for d in clamped]
    residual = scene_duration - sum(durations)
    durations[-1] = max(0.15, durations[-1] + residual)

    return list(zip(phrases, durations, strict=True))


def phrase_timeline(
    phrases: Sequence[tuple[str, float]],
) -> list[tuple[str, float, float]]:
    """Convert ``(text, duration)`` pairs into ``(text, start, end)`` cues."""
    cursor = 0.0
    timeline: list[tuple[str, float, float]] = []
    for text, duration in phrases:
        start = cursor
        end = cursor + max(0.15, float(duration))
        timeline.append((text, start, end))
        cursor = end
    return timeline

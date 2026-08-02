"""Pillow-rendered full-frame overlays for Quizverse beats."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from youtube_pipeline.i18n import caption_font_for_language
from youtube_pipeline.models import BeatType, SceneData
from youtube_pipeline.utils.files import ensure_dir
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

QUIZ_OVERLAY_BEATS = frozenset(
    {BeatType.QUESTION, BeatType.TIMER, BeatType.REVEAL, BeatType.CTA}
)

__all__ = [
    "QUIZ_OVERLAY_BEATS",
    "render_quiz_card",
    "render_quiz_overlay_png",
]


def _font(
    size: int,
    *,
    language: str,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        caption_font_for_language(language),
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    *,
    center_x: int,
    top: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    spacing: int,
) -> int:
    y = top
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        width = box[2] - box[0]
        height = box[3] - box[1]
        draw.text((center_x - width / 2, y), line, font=font, fill=fill)
        y += height + spacing
    return y


def render_quiz_card(
    beat: SceneData,
    *,
    dest: Path,
    width: int,
    height: int,
    countdown: int | None,
    language: str = "en",
) -> Path:
    """Render one transparent full-frame Quizverse card PNG."""
    width = max(320, int(width))
    height = max(320, int(height))
    destination = Path(dest)
    ensure_dir(destination.parent)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    scale = min(width / 1080.0, height / 1920.0)
    margin = max(24, int(width * 0.07))
    panel_left = margin
    panel_right = width - margin
    panel_top = max(margin, int(height * 0.15))
    panel_bottom = min(height - margin, int(height * 0.85))
    radius = max(24, int(42 * scale))
    draw.rounded_rectangle(
        (panel_left, panel_top, panel_right, panel_bottom),
        radius=radius,
        fill=(8, 12, 24, 218),
        outline=(255, 201, 71, 235),
        width=max(3, int(6 * scale)),
    )

    center_x = width // 2
    content_width = panel_right - panel_left - max(36, int(80 * scale))
    label_font = _font(max(24, int(48 * scale)), language=language, bold=True)
    title_font = _font(max(30, int(64 * scale)), language=language, bold=True)
    body_font = _font(max(24, int(48 * scale)), language=language)
    answer_font = _font(max(36, int(86 * scale)), language=language, bold=True)
    timer_font = _font(max(96, int(300 * scale)), language=language, bold=True)
    white = (255, 255, 255, 255)
    gold = (255, 201, 71, 255)
    muted = (218, 225, 238, 255)
    y = panel_top + max(28, int(64 * scale))

    if beat.beat_type == BeatType.QUESTION:
        y = _draw_centered_lines(
            draw,
            ["QUESTION"],
            center_x=center_x,
            top=y,
            font=label_font,
            fill=gold,
            spacing=max(8, int(16 * scale)),
        )
        y += max(18, int(42 * scale))
        y = _draw_centered_lines(
            draw,
            _wrap_text(draw, beat.question or beat.script_text, font=title_font, max_width=content_width),
            center_x=center_x,
            top=y,
            font=title_font,
            fill=white,
            spacing=max(10, int(20 * scale)),
        )
        y += max(22, int(52 * scale))
        for index, choice in enumerate(beat.choices):
            text = f"{chr(65 + index)}. {choice}"
            lines = _wrap_text(draw, text, font=body_font, max_width=content_width)
            y = _draw_centered_lines(
                draw,
                lines,
                center_x=center_x,
                top=y,
                font=body_font,
                fill=muted,
                spacing=max(8, int(14 * scale)),
            )
            y += max(14, int(28 * scale))

    elif beat.beat_type == BeatType.TIMER:
        if beat.question:
            y = _draw_centered_lines(
                draw,
                _wrap_text(draw, beat.question, font=body_font, max_width=content_width),
                center_x=center_x,
                top=y,
                font=body_font,
                fill=muted,
                spacing=max(8, int(14 * scale)),
            )
        number = str(max(0, countdown or 0))
        box = draw.textbbox((0, 0), number, font=timer_font)
        number_width = box[2] - box[0]
        number_height = box[3] - box[1]
        draw.text(
            (center_x - number_width / 2, (panel_top + panel_bottom - number_height) / 2),
            number,
            font=timer_font,
            fill=gold,
        )

    elif beat.beat_type == BeatType.REVEAL:
        y = _draw_centered_lines(
            draw,
            ["ANSWER"],
            center_x=center_x,
            top=y,
            font=label_font,
            fill=gold,
            spacing=max(8, int(16 * scale)),
        )
        y += max(26, int(56 * scale))
        y = _draw_centered_lines(
            draw,
            _wrap_text(draw, beat.answer, font=answer_font, max_width=content_width),
            center_x=center_x,
            top=y,
            font=answer_font,
            fill=white,
            spacing=max(10, int(20 * scale)),
        )
        if beat.explain:
            y += max(30, int(64 * scale))
            _draw_centered_lines(
                draw,
                _wrap_text(draw, beat.explain, font=body_font, max_width=content_width),
                center_x=center_x,
                top=y,
                font=body_font,
                fill=muted,
                spacing=max(8, int(16 * scale)),
            )

    elif beat.beat_type == BeatType.CTA:
        y = int((panel_top + panel_bottom) / 2 - 100 * scale)
        _draw_centered_lines(
            draw,
            ["ANSWER IN", "THE COMMENTS"],
            center_x=center_x,
            top=y,
            font=answer_font,
            fill=white,
            spacing=max(14, int(28 * scale)),
        )

    image.save(destination, format="PNG")
    return destination


def render_quiz_overlay_png(
    beat: SceneData,
    *,
    width: int,
    height: int,
    t_within_beat: float,
    language: str = "en",
    dest_dir: Path | None = None,
) -> Path | None:
    """Select countdown state and render an overlay, returning ``None`` on failure."""
    if beat.beat_type not in QUIZ_OVERLAY_BEATS:
        return None
    try:
        remaining: int | None = None
        if beat.beat_type == BeatType.TIMER:
            duration = float(beat.hold_seconds or beat.duration or 0.0)
            remaining = max(0, math.ceil(duration - max(0.0, t_within_beat)))
        root = ensure_dir(
            Path(dest_dir)
            if dest_dir is not None
            else Path(tempfile.gettempdir()) / "youtube_pipeline_quiz_overlays"
        )
        suffix = f"_{remaining}" if remaining is not None else ""
        destination = root / f"quiz_{beat.scene_id:03d}_{beat.beat_type.value}{suffix}.png"
        return render_quiz_card(
            beat,
            dest=destination,
            width=width,
            height=height,
            countdown=remaining,
            language=language,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Quiz overlay render failed | scene=%s | %s", beat.scene_id, exc)
        return None

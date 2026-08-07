"""Compact Pillow-rendered speaker nameplates for dialogue videos."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from youtube_pipeline.i18n import caption_font_for_language
from youtube_pipeline.utils.files import ensure_dir

__all__ = ["render_nameplate_png"]


def _font(
    size: int,
    *,
    language: str,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        caption_font_for_language(language),
        "C:/Windows/Fonts/arialbd.ttf",
        "DejaVuSans-Bold.ttf",
    ):
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_nameplate_png(
    name: str,
    *,
    dest: Path,
    width: int,
    height: int,
    language: str = "en",
) -> Path:
    """Render a compact transparent speaker label scaled for the video frame."""
    frame_width = max(320, int(width))
    frame_height = max(320, int(height))
    destination = Path(dest)
    ensure_dir(destination.parent)

    scale = min(frame_width / 1080.0, frame_height / 1920.0)
    padding_x = max(14, int(28 * scale))
    padding_y = max(9, int(15 * scale))
    max_plate_width = int(frame_width * 0.46)
    max_text_width = max(1, max_plate_width - padding_x * 2)

    measure = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    measure_draw = ImageDraw.Draw(measure)
    font_size = max(18, int(38 * scale))
    font = _font(font_size, language=language)
    box = measure_draw.textbbox((0, 0), name, font=font)
    while box[2] - box[0] > max_text_width and font_size > 10:
        font_size = max(10, font_size - 2)
        font = _font(font_size, language=language)
        box = measure_draw.textbbox((0, 0), name, font=font)
    text_width = max(1, box[2] - box[0])
    text_height = max(1, box[3] - box[1])
    plate_width = min(max_plate_width, text_width + padding_x * 2)
    plate_height = min(int(frame_height * 0.12), text_height + padding_y * 2)

    image = Image.new("RGBA", (plate_width, plate_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    radius = max(10, int(18 * scale))
    draw.rounded_rectangle(
        (0, 0, plate_width - 1, plate_height - 1),
        radius=radius,
        fill=(8, 12, 24, 218),
        outline=(255, 201, 71, 235),
        width=max(2, int(3 * scale)),
    )
    draw.text(
        (padding_x, (plate_height - text_height) / 2 - box[1]),
        name,
        font=font,
        fill=(255, 255, 255, 255),
    )
    image.save(destination, format="PNG")
    return destination

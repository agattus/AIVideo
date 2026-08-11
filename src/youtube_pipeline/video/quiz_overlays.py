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
    {BeatType.HOOK, BeatType.QUESTION, BeatType.TIMER, BeatType.REVEAL, BeatType.CTA}
)

_HOOK_HERO_EMOJI = "🧠"
_CTA_HERO_EMOJI = "💬"

# Common emoji / symbol ranges that Arial/DejaVu cannot paint (tofu boxes).
_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),  # Misc Symbols and Pictographs … Symbols Extended-A
    (0x2600, 0x27BF),  # Misc symbols + Dingbats
    (0xFE00, 0xFE0F),  # Variation selectors
    (0x1F1E6, 0x1F1FF),  # Regional indicator (flags)
    (0x200D, 0x200D),  # ZWJ
)

_EMOJI_FONT_CANDIDATES = (
    "C:/Windows/Fonts/seguiemj.ttf",
    "C:/Windows/Fonts/SegoeUIEmoji.ttf",
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
)

__all__ = [
    "QUIZ_OVERLAY_BEATS",
    "render_quiz_card",
    "render_quiz_overlay_png",
]


def _is_emoji_char(ch: str) -> bool:
    code = ord(ch)
    return any(start <= code <= end for start, end in _EMOJI_RANGES)


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


def _emoji_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont | None:
    for candidate in _EMOJI_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return None


def _split_text_runs(text: str) -> list[tuple[str, bool]]:
    """Split ``text`` into (run, is_emoji) segments preserving order."""
    if not text:
        return []
    runs: list[tuple[str, bool]] = []
    current = text[0]
    emoji = _is_emoji_char(text[0])
    for ch in text[1:]:
        is_emoji = _is_emoji_char(ch)
        if is_emoji == emoji:
            current += ch
        else:
            runs.append((current, emoji))
            current = ch
            emoji = is_emoji
    runs.append((current, emoji))
    return runs


def _text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    emoji_font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None,
) -> int:
    width = 0
    for run, is_emoji in _split_text_runs(text):
        use = emoji_font if is_emoji and emoji_font is not None else font
        box = draw.textbbox((0, 0), run, font=use)
        width += box[2] - box[0]
    return width


def _text_height(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    emoji_font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None,
) -> int:
    height = 0
    for run, is_emoji in _split_text_runs(text):
        use = emoji_font if is_emoji and emoji_font is not None else font
        box = draw.textbbox((0, 0), run, font=use)
        height = max(height, box[3] - box[1])
    return height


def _draw_text_mixed(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    emoji_font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None,
    fill: tuple[int, int, int, int],
    image: Image.Image | None = None,
    emoji_target_px: int | None = None,
) -> None:
    x, y = xy
    for run, is_emoji in _split_text_runs(text):
        if (
            is_emoji
            and emoji_font is not None
            and image is not None
            and emoji_target_px
            and emoji_target_px >= 48
        ):
            advance = _paste_scaled_emoji(
                image,
                run,
                xy=(x, y),
                emoji_font=emoji_font,
                target_px=emoji_target_px,
            )
            x += advance
            continue
        use = emoji_font if is_emoji and emoji_font is not None else font
        kwargs: dict[str, object] = {"font": use, "fill": fill}
        if is_emoji and emoji_font is not None:
            kwargs["embedded_color"] = True
        try:
            draw.text((x, y), run, **kwargs)
        except TypeError:
            kwargs.pop("embedded_color", None)
            draw.text((x, y), run, **kwargs)
        box = draw.textbbox((0, 0), run, font=use)
        x += box[2] - box[0]


def _paste_scaled_emoji(
    image: Image.Image,
    emoji: str,
    *,
    xy: tuple[float, float],
    emoji_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    target_px: int,
) -> int:
    """Paint color emoji and upscale — CBDT fonts often ignore large point sizes."""
    canvas_size = max(target_px * 2, 256)
    tmp = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    try:
        tmp_draw.text((8, 8), emoji, font=emoji_font, embedded_color=True)
    except TypeError:
        tmp_draw.text((8, 8), emoji, font=emoji_font, fill=(255, 255, 255, 255))
    bbox = tmp.getbbox()
    if bbox is None:
        return target_px
    glyph = tmp.crop(bbox)
    # Keep aspect; fit inside target box.
    gw, gh = glyph.size
    scale = min(target_px / max(1, gw), target_px / max(1, gh))
    new_size = (max(1, int(gw * scale)), max(1, int(gh * scale)))
    glyph = glyph.resize(new_size, Image.Resampling.LANCZOS)
    x, y = int(xy[0]), int(xy[1])
    image.alpha_composite(glyph, (x, y))
    return new_size[0]


def _draw_hero_emoji(
    image: Image.Image,
    emoji: str,
    *,
    center_x: int,
    top: int,
    target_px: int,
) -> int:
    """Centered oversized emoji for hook/CTA impact frames."""
    emoji_font = _emoji_font(max(64, min(128, target_px)))
    if emoji_font is None:
        return top
    canvas_size = max(target_px * 2, 320)
    tmp = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    try:
        tmp_draw.text((16, 16), emoji, font=emoji_font, embedded_color=True)
    except TypeError:
        tmp_draw.text((16, 16), emoji, font=emoji_font, fill=(255, 255, 255, 255))
    bbox = tmp.getbbox()
    if bbox is None:
        return top
    glyph = tmp.crop(bbox)
    gw, gh = glyph.size
    scale = min(target_px / max(1, gw), target_px / max(1, gh))
    new_size = (max(1, int(gw * scale)), max(1, int(gh * scale)))
    glyph = glyph.resize(new_size, Image.Resampling.LANCZOS)
    x = int(center_x - new_size[0] / 2)
    y = int(top)
    image.alpha_composite(glyph, (max(0, x), max(0, y)))
    return top + new_size[1]


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    emoji_font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None,
) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _text_width(draw, candidate, font=font, emoji_font=emoji_font) <= max_width:
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
    emoji_font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None,
    image: Image.Image | None = None,
    emoji_target_px: int | None = None,
) -> int:
    y = top
    target = emoji_target_px
    for line in lines:
        if target and any(_is_emoji_char(ch) for ch in line):
            # Width estimate for mixed lines: treat emoji runs as target_px wide.
            width = 0
            height = 0
            for run, is_emoji in _split_text_runs(line):
                if is_emoji and emoji_font is not None:
                    width += target
                    height = max(height, target)
                else:
                    box = draw.textbbox((0, 0), run, font=font)
                    width += box[2] - box[0]
                    height = max(height, box[3] - box[1])
        else:
            width = _text_width(draw, line, font=font, emoji_font=emoji_font)
            height = _text_height(draw, line, font=font, emoji_font=emoji_font)
        _draw_text_mixed(
            draw,
            (center_x - width / 2, y),
            line,
            font=font,
            emoji_font=emoji_font,
            fill=fill,
            image=image,
            emoji_target_px=target,
        )
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
    # Prefer the dominant axis so 9:16 Shorts keep punchy type.
    scale = max(width / 1080.0, height / 1920.0)
    scale = max(0.55, min(1.35, scale))
    is_hook = beat.beat_type == BeatType.HOOK
    margin = max(20, int(width * (0.05 if is_hook else 0.07)))
    panel_left = margin
    panel_right = width - margin
    panel_top = max(margin, int(height * (0.10 if is_hook else 0.15)))
    panel_bottom = min(height - margin, int(height * (0.90 if is_hook else 0.85)))
    radius = max(24, int(42 * scale))
    panel_fill = (6, 8, 20, 230) if is_hook else (8, 12, 24, 218)
    draw.rounded_rectangle(
        (panel_left, panel_top, panel_right, panel_bottom),
        radius=radius,
        fill=panel_fill,
        outline=(255, 201, 71, 245),
        width=max(4, int(8 * scale)),
    )

    center_x = width // 2
    content_width = panel_right - panel_left - max(36, int(80 * scale))
    label_font = _font(max(28, int(56 * scale)), language=language, bold=True)
    title_font = _font(max(40, int(78 * scale)), language=language, bold=True)
    body_font = _font(max(30, int(56 * scale)), language=language)
    answer_font = _font(max(44, int(96 * scale)), language=language, bold=True)
    hook_font = _font(max(48, int(92 * scale)), language=language, bold=True)
    timer_font = _font(max(96, int(300 * scale)), language=language, bold=True)
    # Color emoji fonts often cap ~128px; we upscale via _paste_scaled_emoji.
    title_emoji = _emoji_font(128)
    body_emoji = _emoji_font(96)
    answer_emoji = _emoji_font(128)
    title_emoji_px = max(72, int(150 * scale))
    body_emoji_px = max(56, int(110 * scale))
    answer_emoji_px = max(80, int(170 * scale))
    hero_emoji_px = max(160, int(320 * scale))
    white = (255, 255, 255, 255)
    gold = (255, 201, 71, 255)
    muted = (218, 225, 238, 255)
    y = panel_top + max(28, int(64 * scale))

    if beat.beat_type == BeatType.HOOK:
        y = _draw_hero_emoji(
            image,
            _HOOK_HERO_EMOJI,
            center_x=center_x,
            top=y,
            target_px=hero_emoji_px,
        )
        y += max(20, int(36 * scale))
        y = _draw_centered_lines(
            draw,
            ["QUIZ TIME"],
            center_x=center_x,
            top=y,
            font=label_font,
            fill=gold,
            spacing=max(8, int(16 * scale)),
        )
        y += max(18, int(36 * scale))
        hook_text = (beat.script_text or "Think you know the answers?").strip()
        _draw_centered_lines(
            draw,
            _wrap_text(
                draw,
                hook_text,
                font=hook_font,
                max_width=content_width,
                emoji_font=title_emoji,
            ),
            center_x=center_x,
            top=y,
            font=hook_font,
            fill=white,
            spacing=max(14, int(28 * scale)),
            emoji_font=title_emoji,
            image=image,
            emoji_target_px=title_emoji_px,
        )

    elif beat.beat_type == BeatType.QUESTION:
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
            _wrap_text(
                draw,
                beat.question or beat.script_text,
                font=title_font,
                max_width=content_width,
                emoji_font=title_emoji,
            ),
            center_x=center_x,
            top=y,
            font=title_font,
            fill=white,
            spacing=max(12, int(24 * scale)),
            emoji_font=title_emoji,
            image=image,
            emoji_target_px=title_emoji_px,
        )
        y += max(22, int(52 * scale))
        for index, choice in enumerate(beat.choices):
            text = f"{chr(65 + index)}. {choice}"
            lines = _wrap_text(
                draw,
                text,
                font=body_font,
                max_width=content_width,
                emoji_font=body_emoji,
            )
            y = _draw_centered_lines(
                draw,
                lines,
                center_x=center_x,
                top=y,
                font=body_font,
                fill=muted,
                spacing=max(8, int(14 * scale)),
                emoji_font=body_emoji,
                image=image,
                emoji_target_px=body_emoji_px,
            )
            y += max(14, int(28 * scale))

    elif beat.beat_type == BeatType.TIMER:
        if beat.question:
            y = _draw_centered_lines(
                draw,
                _wrap_text(
                    draw,
                    beat.question,
                    font=body_font,
                    max_width=content_width,
                    emoji_font=body_emoji,
                ),
                center_x=center_x,
                top=y,
                font=body_font,
                fill=muted,
                spacing=max(8, int(14 * scale)),
                emoji_font=body_emoji,
                image=image,
                emoji_target_px=body_emoji_px,
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
            _wrap_text(
                draw,
                beat.answer,
                font=answer_font,
                max_width=content_width,
                emoji_font=answer_emoji,
            ),
            center_x=center_x,
            top=y,
            font=answer_font,
            fill=white,
            spacing=max(12, int(24 * scale)),
            emoji_font=answer_emoji,
            image=image,
            emoji_target_px=answer_emoji_px,
        )
        if beat.explain:
            y += max(30, int(64 * scale))
            _draw_centered_lines(
                draw,
                _wrap_text(
                    draw,
                    beat.explain,
                    font=body_font,
                    max_width=content_width,
                    emoji_font=body_emoji,
                ),
                center_x=center_x,
                top=y,
                font=body_font,
                fill=muted,
                spacing=max(8, int(16 * scale)),
                emoji_font=body_emoji,
                image=image,
                emoji_target_px=body_emoji_px,
            )

    elif beat.beat_type == BeatType.CTA:
        y = panel_top + max(36, int(72 * scale))
        y = _draw_hero_emoji(
            image,
            _CTA_HERO_EMOJI,
            center_x=center_x,
            top=y,
            target_px=max(140, int(260 * scale)),
        )
        y += max(18, int(32 * scale))
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

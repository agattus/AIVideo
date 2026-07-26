"""Aspect-ratio helpers for image generation and video framing."""

from __future__ import annotations

from youtube_pipeline.models import AspectRatio

# Output frame sizes used by MoviePy + prompt-pack instructions.
ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    AspectRatio.LANDSCAPE.value: (1920, 1080),  # normal YouTube
    AspectRatio.VERTICAL.value: (1080, 1920),  # Shorts / Reels / TikTok
    AspectRatio.SQUARE.value: (1080, 1080),
}

# OpenAI DALL·E 3 accepted sizes closest to each ratio.
DALLE_SIZES: dict[str, str] = {
    AspectRatio.LANDSCAPE.value: "1792x1024",
    AspectRatio.VERTICAL.value: "1024x1792",
    AspectRatio.SQUARE.value: "1024x1024",
}

ASPECT_LABELS: dict[str, str] = {
    AspectRatio.LANDSCAPE.value: "Landscape / normal YouTube (16:9)",
    AspectRatio.VERTICAL.value: "Vertical Shorts / Reels / TikTok (9:16)",
    AspectRatio.SQUARE.value: "Square feed post (1:1)",
}


def normalize_aspect_ratio(value: AspectRatio | str | None) -> str:
    """Return a canonical ``16:9`` / ``9:16`` / ``1:1`` string."""
    if value is None:
        return AspectRatio.LANDSCAPE.value
    text = value.value if isinstance(value, AspectRatio) else str(value).strip()
    aliases = {
        "16:9": AspectRatio.LANDSCAPE.value,
        "landscape": AspectRatio.LANDSCAPE.value,
        "widescreen": AspectRatio.LANDSCAPE.value,
        "youtube": AspectRatio.LANDSCAPE.value,
        "9:16": AspectRatio.VERTICAL.value,
        "vertical": AspectRatio.VERTICAL.value,
        "portrait": AspectRatio.VERTICAL.value,
        "shorts": AspectRatio.VERTICAL.value,
        "reel": AspectRatio.VERTICAL.value,
        "reels": AspectRatio.VERTICAL.value,
        "tiktok": AspectRatio.VERTICAL.value,
        "1:1": AspectRatio.SQUARE.value,
        "square": AspectRatio.SQUARE.value,
    }
    key = text.lower().replace(" ", "")
    if key in aliases:
        return aliases[key]
    if text in ASPECT_DIMENSIONS:
        return text
    return AspectRatio.LANDSCAPE.value


def dimensions_for_aspect(aspect_ratio: AspectRatio | str | None) -> tuple[int, int]:
    ratio = normalize_aspect_ratio(aspect_ratio)
    return ASPECT_DIMENSIONS.get(ratio, ASPECT_DIMENSIONS[AspectRatio.LANDSCAPE.value])


def dalle_size_for_aspect(aspect_ratio: AspectRatio | str | None) -> str:
    ratio = normalize_aspect_ratio(aspect_ratio)
    return DALLE_SIZES.get(ratio, DALLE_SIZES[AspectRatio.LANDSCAPE.value])


def label_for_aspect(aspect_ratio: AspectRatio | str | None) -> str:
    ratio = normalize_aspect_ratio(aspect_ratio)
    return ASPECT_LABELS.get(ratio, ASPECT_LABELS[AspectRatio.LANDSCAPE.value])

"""Aspect-ratio helpers for scene image generation."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

_ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "1:1": (1, 1),
}


def _ratio_parts(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio not in _ASPECT_RATIOS:
        raise ValueError(f"Unsupported aspect ratio: {aspect_ratio!r}")
    return _ASPECT_RATIOS[aspect_ratio]


def target_size(aspect_ratio: str, *, long_edge: int = 1280) -> tuple[int, int]:
    rw, rh = _ratio_parts(aspect_ratio)
    if rw >= rh:
        width = long_edge
        height = round(long_edge * rh / rw)
    else:
        height = long_edge
        width = round(long_edge * rw / rh)
    return width, height


def aspect_prompt_clause(aspect_ratio: str) -> str:
    clauses = {
        "9:16": "Frame: vertical 9:16 portrait, subject fully in frame, no letterboxing.",
        "16:9": "Frame: horizontal 16:9 landscape, subject fully in frame, no letterboxing.",
        "1:1": "Frame: square 1:1, subject fully in frame, no letterboxing.",
    }
    if aspect_ratio not in clauses:
        raise ValueError(f"Unsupported aspect ratio: {aspect_ratio!r}")
    return clauses[aspect_ratio]


def normalize_image_to_aspect(image_bytes: bytes, aspect_ratio: str) -> bytes:
    rw, rh = _ratio_parts(aspect_ratio)
    target_w, target_h = target_size(aspect_ratio)
    target_ratio = rw / rh

    with Image.open(BytesIO(image_bytes)) as img:
        img = img.convert("RGB")
        src_w, src_h = img.size
        src_ratio = src_w / src_h

        if src_ratio > target_ratio:
            new_w = int(round(src_h * target_ratio))
            new_h = src_h
        else:
            new_w = src_w
            new_h = int(round(src_w / target_ratio))

        left = (src_w - new_w) // 2
        top = (src_h - new_h) // 2
        cropped = img.crop((left, top, left + new_w, top + new_h))
        resized = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)

        out = BytesIO()
        resized.save(out, format="PNG")
        return out.getvalue()

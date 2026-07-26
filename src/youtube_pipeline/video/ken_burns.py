"""Ken Burns (subtle pan/zoom) effect helpers for still images."""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable

from moviepy import ImageClip, VideoClip


class KenBurnsDirection(str, Enum):
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_RIGHT = "pan_right"
    PAN_LEFT = "pan_left"


def smoothstep(progress: float) -> float:
    """Hermite smoothstep for cinematic ease-in/out motion (0..1 → 0..1)."""
    p = min(1.0, max(0.0, progress))
    return p * p * (3.0 - 2.0 * p)


def apply_ken_burns(
    clip: ImageClip,
    *,
    direction: KenBurnsDirection | None = None,
    zoom_ratio: float = 0.12,
) -> VideoClip:
    """Apply a subtle Ken Burns motion to an ImageClip.

    The clip must already have a duration and target size set. Motion uses
    smoothstep easing so pans/zooms feel cinematic rather than linear.
    """
    if clip.duration is None or clip.duration <= 0:
        raise ValueError("ImageClip must have a positive duration for Ken Burns")

    w, h = clip.size
    direction = direction or _pick_direction(int(getattr(clip, "scene_index", 0)))
    zoom_ratio = max(0.02, min(zoom_ratio, 0.25))

    def fl(get_frame: Callable[[float], Any], t: float) -> Any:
        raw = 0.0 if not clip.duration else min(1.0, max(0.0, t / clip.duration))
        progress = smoothstep(raw)
        frame = get_frame(t)

        if direction == KenBurnsDirection.ZOOM_IN:
            scale = 1.0 + (zoom_ratio * progress)
        elif direction == KenBurnsDirection.ZOOM_OUT:
            scale = 1.0 + (zoom_ratio * (1.0 - progress))
        else:
            scale = 1.0 + (zoom_ratio * 0.5)

        crop_w = int(w / scale)
        crop_h = int(h / scale)
        crop_w -= crop_w % 2
        crop_h -= crop_h % 2
        crop_w = max(2, min(crop_w, w))
        crop_h = max(2, min(crop_h, h))

        max_x = max(0, w - crop_w)
        max_y = max(0, h - crop_h)

        if direction == KenBurnsDirection.PAN_RIGHT:
            x1 = int(max_x * progress)
            y1 = max_y // 2
        elif direction == KenBurnsDirection.PAN_LEFT:
            x1 = int(max_x * (1.0 - progress))
            y1 = max_y // 2
        else:
            x1 = max_x // 2
            y1 = max_y // 2

        x2 = x1 + crop_w
        y2 = y1 + crop_h
        cropped = frame[y1:y2, x1:x2]

        try:
            from PIL import Image
            import numpy as np

            img = Image.fromarray(cropped)
            img = img.resize((w, h), Image.Resampling.LANCZOS)
            return np.array(img)
        except Exception:  # noqa: BLE001
            import numpy as np

            ys = (np.linspace(0, cropped.shape[0] - 1, h)).astype(int)
            xs = (np.linspace(0, cropped.shape[1] - 1, w)).astype(int)
            return cropped[ys][:, xs]

    return clip.transform(fl)


def _pick_direction(scene_index: int) -> KenBurnsDirection:
    cycle = [
        KenBurnsDirection.ZOOM_IN,
        KenBurnsDirection.PAN_RIGHT,
        KenBurnsDirection.ZOOM_OUT,
        KenBurnsDirection.PAN_LEFT,
    ]
    return cycle[scene_index % len(cycle)]

"""Video composition and editing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from youtube_pipeline.video.composer import VideoComposer

__all__ = ["VideoComposer"]


def __getattr__(name: str):
    if name == "VideoComposer":
        from youtube_pipeline.video.composer import VideoComposer

        return VideoComposer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

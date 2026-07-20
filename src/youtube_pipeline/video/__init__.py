"""Video composition and editing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from youtube_pipeline.video.composer import VideoComposer

__all__ = ["VideoComposer", "create_caption_clip"]


def __getattr__(name: str):
    if name == "VideoComposer":
        from youtube_pipeline.video.composer import VideoComposer

        return VideoComposer
    if name == "create_caption_clip":
        from youtube_pipeline.video.text_clips import create_caption_clip

        return create_caption_clip
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

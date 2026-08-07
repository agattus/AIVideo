"""Asset provider protocol and shared helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from youtube_pipeline.models import MediaAsset, SceneData


class AssetProviderProtocol(Protocol):
    """Interface implemented by AI and stock media providers."""

    name: str

    def fetch_for_scene(
        self,
        scene: SceneData,
        output_dir: Path,
        *,
        aspect_ratio: str = "16:9",
    ) -> MediaAsset:
        """Return a local media file for the given scene.

        Implementations may accept ``aspect_ratio`` (e.g. ``16:9``, ``9:16``, ``1:1``)
        to shape generated or fetched imagery before compose.
        """
        ...

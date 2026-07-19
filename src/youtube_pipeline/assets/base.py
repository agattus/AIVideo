"""Asset provider protocol and shared helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from youtube_pipeline.models import MediaAsset, SceneData


class AssetProviderProtocol(Protocol):
    """Interface implemented by AI and stock media providers."""

    name: str

    def fetch_for_scene(self, scene: SceneData, output_dir: Path) -> MediaAsset:
        """Return a local media file for the given scene."""
        ...

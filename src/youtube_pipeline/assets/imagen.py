"""Standalone Google Imagen 3 image provider (protocol-compatible)."""

from __future__ import annotations

from pathlib import Path

from config.settings import Settings, get_settings
from youtube_pipeline.assets.provider import AssetService
from youtube_pipeline.models import MediaAsset, SceneData


class ImagenProvider:
    """Thin wrapper around ``AssetService._fetch_imagen_image``."""

    name = "imagen"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._service = AssetService(self.settings)

    def fetch_for_scene(self, scene: SceneData, output_dir: Path) -> MediaAsset:
        return self._service._fetch_imagen_image(scene, output_dir)

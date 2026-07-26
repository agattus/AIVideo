"""Pixabay stock routing was removed — Imagen is the default generative path."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import AssetProvider, Settings
from youtube_pipeline.assets.provider import AssetService
from youtube_pipeline.exceptions import ConfigurationError


def test_pixabay_and_pexels_enum_values_removed() -> None:
    assert not hasattr(AssetProvider, "PIXABAY")
    assert not hasattr(AssetProvider, "PEXELS")
    assert AssetProvider.IMAGEN.value == "imagen"
    assert AssetProvider.POLLINATIONS.value == "pollinations"


def test_default_asset_provider_is_imagen(tmp_path: Path) -> None:
    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        gemini_api_key="test-gemini-key",
    )
    assert settings.asset_provider == AssetProvider.IMAGEN
    AssetService(settings)


def test_imagen_requires_gemini_api_key(tmp_path: Path) -> None:
    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        asset_provider=AssetProvider.IMAGEN,
        gemini_api_key=None,
    )
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        AssetService(settings)

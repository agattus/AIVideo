"""Pixabay stock routing was removed — Pollinations is the default generative path."""

from __future__ import annotations

from pathlib import Path

from config.settings import AssetProvider, Settings
from youtube_pipeline.assets.provider import AssetService


def test_pixabay_and_pexels_enum_values_removed() -> None:
    assert not hasattr(AssetProvider, "PIXABAY")
    assert not hasattr(AssetProvider, "PEXELS")
    assert AssetProvider.POLLINATIONS.value == "pollinations"


def test_default_asset_provider_is_pollinations(tmp_path: Path) -> None:
    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
    )
    assert settings.asset_provider == AssetProvider.POLLINATIONS
    # Construction must succeed with no Pixabay/Pexels keys.
    AssetService(settings)

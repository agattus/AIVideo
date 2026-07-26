"""Factory for visual asset providers."""

from __future__ import annotations

from config.settings import AssetProvider, Settings, get_settings
from youtube_pipeline.assets.ai_generator import OpenAIImageProvider
from youtube_pipeline.assets.base import AssetProviderProtocol
from youtube_pipeline.assets.imagen import ImagenProvider
from youtube_pipeline.assets.pollinations import PollinationsProvider
from youtube_pipeline.exceptions import ConfigurationError


def build_asset_provider(settings: Settings | None = None) -> AssetProviderProtocol:
    settings = settings or get_settings()
    if settings.asset_provider == AssetProvider.IMAGEN:
        return ImagenProvider(settings)
    if settings.asset_provider == AssetProvider.POLLINATIONS:
        return PollinationsProvider(settings)
    if settings.asset_provider == AssetProvider.OPENAI_IMAGE:
        return OpenAIImageProvider(settings)
    raise ConfigurationError(f"Unsupported asset provider: {settings.asset_provider}")

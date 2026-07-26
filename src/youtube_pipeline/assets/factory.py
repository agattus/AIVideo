"""Factory for visual asset providers."""

from __future__ import annotations

from config.settings import AssetProvider, Settings, get_settings
from youtube_pipeline.assets.ai_generator import OpenAIImageProvider
from youtube_pipeline.assets.base import AssetProviderProtocol
from youtube_pipeline.assets.pollinations import PollinationsProvider
from youtube_pipeline.exceptions import ConfigurationError


def build_asset_provider(settings: Settings | None = None) -> AssetProviderProtocol:
    settings = settings or get_settings()
    if settings.asset_provider == AssetProvider.POLLINATIONS:
        return PollinationsProvider(settings)
    if settings.asset_provider == AssetProvider.OPENAI_IMAGE:
        return OpenAIImageProvider(settings)
    if settings.asset_provider == AssetProvider.MANUAL:
        raise ConfigurationError(
            "ASSET_PROVIDER=manual skips auto image generation; "
            "upload a ZIP via POST /api/v1/jobs/{job_id}/upload-assets"
        )
    if settings.asset_provider == AssetProvider.IMAGEN:
        # HITL / Gemini image workflows pause for external assets; no local Imagen client yet.
        raise ConfigurationError(
            "ASSET_PROVIDER=imagen is reserved; use ASSET_PROVIDER=manual for "
            "human-in-the-loop ZIP upload, or pollinations/openai_image for auto gen"
        )
    raise ConfigurationError(f"Unsupported asset provider: {settings.asset_provider}")

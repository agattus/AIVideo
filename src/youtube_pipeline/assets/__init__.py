"""Visual asset acquisition (AI generation + stock media)."""

from youtube_pipeline.assets.base import AssetProviderProtocol
from youtube_pipeline.assets.factory import build_asset_provider

__all__ = ["AssetProviderProtocol", "build_asset_provider"]

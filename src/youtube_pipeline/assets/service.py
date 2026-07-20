"""Back-compat re-export of AssetService (canonical implementation in provider.py)."""

from youtube_pipeline.assets.provider import STYLE_PROMPT_SUFFIX, AssetService

__all__ = ["AssetService", "STYLE_PROMPT_SUFFIX"]

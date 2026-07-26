"""Legacy stock providers removed.

Pixabay / Pexels stock footage was replaced by generative images via Imagen /
Pollinations (see ``provider.AssetService``).
"""

from __future__ import annotations

from youtube_pipeline.assets.pollinations import PollinationsProvider

# Back-compat aliases so old imports do not crash.
PexelsProvider = PollinationsProvider
PixabayProvider = PollinationsProvider

__all__ = ["PollinationsProvider", "PexelsProvider", "PixabayProvider"]

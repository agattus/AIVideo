"""Stock media providers (Pexels / Pixabay)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from youtube_pipeline.exceptions import AssetAcquisitionError, ConfigurationError
from youtube_pipeline.models import MediaAsset, Scene
from youtube_pipeline.utils.files import ensure_dir, slugify
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


class PexelsProvider:
    """Fetch still photos from the Pexels API."""

    name = "pexels"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.pexels_api_key:
            raise ConfigurationError("PEXELS_API_KEY is required for asset provider 'pexels'")

    def fetch_for_scene(self, scene: Scene, output_dir: Path) -> MediaAsset:
        query = " ".join(scene.keywords) if scene.keywords else scene.narration[:80]
        logger.info("Pexels search | scene=%d | query=%r", scene.index, query)
        photo = self._search_photo(query)
        url = photo["src"]["large2x"]
        dest = ensure_dir(output_dir) / f"scene_{scene.index:02d}_{slugify(query)[:40]}.jpg"
        self._download(url, dest)
        return MediaAsset(
            scene_index=scene.index,
            path=dest,
            source=self.name,
            media_type="image",
            width=photo.get("width"),
            height=photo.get("height"),
            attribution=f"Photo by {photo.get('photographer')} on Pexels",
        )

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _search_photo(self, query: str) -> dict:
        headers = {"Authorization": self.settings.pexels_api_key or ""}
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 1, "orientation": "landscape"},
                headers=headers,
            )
            response.raise_for_status()
            photos = response.json().get("photos") or []
            if not photos:
                raise AssetAcquisitionError(f"No Pexels results for query={query!r}")
            return photos[0]

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _download(self, url: str, dest: Path) -> None:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            dest.write_bytes(response.content)


class PixabayProvider:
    """Fetch still photos from the Pixabay API."""

    name = "pixabay"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.pixabay_api_key:
            raise ConfigurationError("PIXABAY_API_KEY is required for asset provider 'pixabay'")

    def fetch_for_scene(self, scene: Scene, output_dir: Path) -> MediaAsset:
        query = " ".join(scene.keywords) if scene.keywords else scene.narration[:80]
        logger.info("Pixabay search | scene=%d | query=%r", scene.index, query)
        hit = self._search_photo(query)
        url = hit.get("largeImageURL") or hit.get("webformatURL")
        if not url:
            raise AssetAcquisitionError("Pixabay hit missing image URL")
        ext = Path(urlparse(url).path).suffix or ".jpg"
        dest = ensure_dir(output_dir) / f"scene_{scene.index:02d}_{slugify(query)[:40]}{ext}"
        self._download(url, dest)
        return MediaAsset(
            scene_index=scene.index,
            path=dest,
            source=self.name,
            media_type="image",
            width=hit.get("imageWidth"),
            height=hit.get("imageHeight"),
            attribution="Image from Pixabay",
        )

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _search_photo(self, query: str) -> dict:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                "https://pixabay.com/api/",
                params={
                    "key": self.settings.pixabay_api_key,
                    "q": query,
                    "image_type": "photo",
                    "orientation": "horizontal",
                    "per_page": 3,
                    "safesearch": "true",
                },
            )
            response.raise_for_status()
            hits = response.json().get("hits") or []
            if not hits:
                raise AssetAcquisitionError(f"No Pixabay results for query={query!r}")
            return hits[0]

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _download(self, url: str, dest: Path) -> None:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            dest.write_bytes(response.content)

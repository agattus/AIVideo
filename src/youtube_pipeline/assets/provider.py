"""Multi-tier asset acquisition: Pexels video → Pexels image → OpenAI DALL·E 3."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from youtube_pipeline.exceptions import AssetAcquisitionError, ConfigurationError
from youtube_pipeline.models import MediaAsset, SceneData, VideoScript
from youtube_pipeline.utils.files import ensure_dir
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"
PEXELS_PHOTO_SEARCH = "https://api.pexels.com/v1/search"

# Style suffixes appended to visual_prompt for DALL·E fallback.
STYLE_PROMPT_SUFFIX: dict[str, str] = {
    "cinematic": (
        "cinematic lighting, ultra-detailed photorealistic, shallow depth of field, "
        "anamorphic widescreen composition, rich color grading"
    ),
    "documentary": (
        "documentary photography, natural light, authentic candid framing, "
        "realistic detail, observational style"
    ),
    "corporate": (
        "clean modern corporate aesthetic, bright balanced lighting, "
        "professional photography, brand-safe composition"
    ),
    "fast_paced_shorts": (
        "bold high-contrast composition, vibrant colors, dynamic energy, "
        "sharp detail, vertical-friendly framing"
    ),
    "animated": (
        "stylized illustration, clean shapes, expressive color, "
        "consistent art direction, high detail"
    ),
    "minimal": (
        "minimal aesthetic, negative space, soft neutrals, elegant simplicity, "
        "calm composition"
    ),
}


class AssetService:
    """Fetch one local visual asset per scene with a multi-tier fallback chain.

    Fallback order (per scene)
    --------------------------
    1. Pexels **Video** API using scene keywords
    2. Pexels **Image** API using scene keywords
    3. OpenAI **DALL·E 3** using the style-augmented ``visual_prompt``

    Files are saved as ``scene_XX.mp4`` / ``scene_XX.png`` (zero-padded
    ``scene_id``) so ``VideoComposer`` can map them instantly.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._http_timeout = httpx.Timeout(45.0, connect=15.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire_all(self, script: VideoScript, output_dir: Path | str) -> list[MediaAsset]:
        """Download/generate one asset per scene into ``output_dir``."""
        if not script.scenes:
            raise AssetAcquisitionError("VideoScript.scenes is empty; nothing to acquire")

        assets_dir = ensure_dir(Path(output_dir))
        style = (script.style or "cinematic").strip().lower()
        assets: list[MediaAsset] = []
        failures: list[str] = []

        logger.info(
            "Asset acquisition start | scenes=%d | style=%s | dir=%s",
            len(script.scenes),
            style,
            assets_dir,
        )

        for scene in script.scenes:
            try:
                asset = self.fetch_for_scene(scene, assets_dir, style=style)
                assets.append(asset)
                logger.info(
                    "Asset ready | scene=%d | source=%s | path=%s",
                    scene.scene_id,
                    asset.source,
                    asset.path,
                )
            except Exception as exc:  # noqa: BLE001
                msg = f"scene {scene.scene_id}: {exc}"
                failures.append(msg)
                logger.error("Asset acquisition failed | %s", msg)

        if not assets:
            raise AssetAcquisitionError(
                "Failed to acquire any visual assets: " + "; ".join(failures)
            )
        if failures:
            logger.warning(
                "Partial asset acquisition (%d ok, %d failed)",
                len(assets),
                len(failures),
            )
        return assets

    def fetch_for_scene(
        self,
        scene: SceneData,
        output_dir: Path,
        *,
        style: str = "cinematic",
    ) -> MediaAsset:
        """Run the multi-tier fallback chain for a single scene."""
        query = self._build_query(scene)
        errors: list[str] = []

        # Tier 1 — Pexels video
        try:
            asset = self._fetch_pexels_video(scene, output_dir, query)
            if asset is not None:
                return asset
            errors.append("pexels_video: no results")
        except _RateLimited as exc:
            logger.warning("Pexels video rate-limited | scene=%d | %s", scene.scene_id, exc)
            errors.append(f"pexels_video: rate_limited ({exc})")
        except ConfigurationError as exc:
            errors.append(f"pexels_video: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Pexels video failed | scene=%d | %s", scene.scene_id, exc)
            errors.append(f"pexels_video: {exc}")

        # Tier 2 — Pexels image
        try:
            asset = self._fetch_pexels_image(scene, output_dir, query)
            if asset is not None:
                return asset
            errors.append("pexels_image: no results")
        except _RateLimited as exc:
            logger.warning("Pexels image rate-limited | scene=%d | %s", scene.scene_id, exc)
            errors.append(f"pexels_image: rate_limited ({exc})")
        except ConfigurationError as exc:
            errors.append(f"pexels_image: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Pexels image failed | scene=%d | %s", scene.scene_id, exc)
            errors.append(f"pexels_image: {exc}")

        # Tier 3 — OpenAI DALL·E 3
        try:
            return self._fetch_openai_image(scene, output_dir, style=style)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"openai_dalle: {exc}")
            raise AssetAcquisitionError(
                f"All asset tiers failed for scene {scene.scene_id}: " + " | ".join(errors)
            ) from exc

    # ------------------------------------------------------------------
    # Tier 1: Pexels Video
    # ------------------------------------------------------------------

    def _fetch_pexels_video(
        self,
        scene: SceneData,
        output_dir: Path,
        query: str,
    ) -> MediaAsset | None:
        api_key = self.settings.pexels_api_key
        if not api_key:
            raise ConfigurationError("PEXELS_API_KEY is required for Pexels video search")

        payload = self._pexels_get(
            PEXELS_VIDEO_SEARCH,
            api_key,
            params={
                "query": query,
                "per_page": 5,
                "orientation": "landscape",
            },
        )
        videos = payload.get("videos") or []
        if not videos:
            return None

        video = videos[0]
        file_url = self._select_video_file(video)
        if not file_url:
            return None

        dest = output_dir / f"scene_{scene.scene_id:02d}.mp4"
        self._download(file_url, dest)
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(dest.resolve()),
            source="pexels_video",
            media_type="video",
            width=video.get("width"),
            height=video.get("height"),
            duration_seconds=float(video["duration"]) if video.get("duration") else None,
            attribution=f"Video by {video.get('user', {}).get('name', 'Pexels')} on Pexels",
        )

    @staticmethod
    def _select_video_file(video: dict[str, Any]) -> str | None:
        """Prefer a mid-quality HD mp4 (avoid huge UHD downloads)."""
        files = list(video.get("video_files") or [])
        if not files:
            return None

        def rank(item: dict[str, Any]) -> tuple[int, int]:
            width = int(item.get("width") or 0)
            # Prefer ~1080p, then anything >= 720p, then whatever remains.
            if 1280 <= width <= 1920:
                band = 0
            elif width >= 720:
                band = 1
            else:
                band = 2
            # Prefer mp4 / h264-ish links.
            file_type = str(item.get("file_type") or "").lower()
            type_penalty = 0 if "mp4" in file_type else 1
            return (band + type_penalty * 3, -width)

        files_sorted = sorted(files, key=rank)
        for item in files_sorted:
            link = item.get("link")
            if link:
                return str(link)
        return None

    # ------------------------------------------------------------------
    # Tier 2: Pexels Image
    # ------------------------------------------------------------------

    def _fetch_pexels_image(
        self,
        scene: SceneData,
        output_dir: Path,
        query: str,
    ) -> MediaAsset | None:
        api_key = self.settings.pexels_api_key
        if not api_key:
            raise ConfigurationError("PEXELS_API_KEY is required for Pexels image search")

        payload = self._pexels_get(
            PEXELS_PHOTO_SEARCH,
            api_key,
            params={
                "query": query,
                "per_page": 5,
                "orientation": "landscape",
            },
        )
        photos = payload.get("photos") or []
        if not photos:
            return None

        photo = photos[0]
        src = photo.get("src") or {}
        url = src.get("large2x") or src.get("large") or src.get("original")
        if not url:
            return None

        # Preserve extension when possible; default to .jpg.
        suffix = Path(urlparse(str(url)).path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".jpg"
        dest = output_dir / f"scene_{scene.scene_id:02d}{suffix}"
        self._download(str(url), dest)
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(dest.resolve()),
            source="pexels_image",
            media_type="image",
            width=photo.get("width"),
            height=photo.get("height"),
            attribution=f"Photo by {photo.get('photographer', 'Pexels')} on Pexels",
        )

    # ------------------------------------------------------------------
    # Tier 3: OpenAI DALL·E 3
    # ------------------------------------------------------------------

    def _fetch_openai_image(
        self,
        scene: SceneData,
        output_dir: Path,
        *,
        style: str,
    ) -> MediaAsset:
        if not self.settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required for DALL·E fallback")

        prompt = self._style_augmented_prompt(scene.visual_prompt, style)
        logger.info(
            "DALL·E fallback | scene=%d | style=%s | prompt_chars=%d",
            scene.scene_id,
            style,
            len(prompt),
        )
        image_bytes = self._generate_dalle(prompt)
        dest = output_dir / f"scene_{scene.scene_id:02d}.png"
        dest.write_bytes(image_bytes)
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(dest.resolve()),
            source="openai_dalle3",
            media_type="image",
            attribution="AI-generated via OpenAI DALL·E 3",
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _generate_dalle(self, prompt: str) -> bytes:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        model = self.settings.openai_image_model or "dall-e-3"
        # DALL·E 3 only supports n=1 and specific sizes.
        size = "1792x1024" if "dall-e-3" in model else "1024x1024"
        result = client.images.generate(
            model=model,
            prompt=prompt[:3900],  # hard limit safety
            size=size,
            n=1,
            response_format="b64_json",
        )
        item = result.data[0]
        if getattr(item, "b64_json", None):
            return base64.b64decode(item.b64_json)

        url = getattr(item, "url", None)
        if not url:
            raise AssetAcquisitionError("DALL·E response missing b64_json/url")
        return self._download_bytes(str(url))

    @staticmethod
    def _style_augmented_prompt(visual_prompt: str, style: str) -> str:
        base = visual_prompt.strip()
        suffix = STYLE_PROMPT_SUFFIX.get(style.lower(), STYLE_PROMPT_SUFFIX["cinematic"])
        # Avoid duplicating an already style-heavy prompt.
        if suffix.split(",")[0].lower() in base.lower():
            return base
        return f"{base}, {suffix}"

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _pexels_get(self, url: str, api_key: str, *, params: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": api_key}
        with httpx.Client(timeout=self._http_timeout, follow_redirects=True) as client:
            response = client.get(url, params=params, headers=headers)
            if response.status_code == 429:
                raise _RateLimited(f"HTTP 429 from {url}")
            if response.status_code >= 400:
                raise AssetAcquisitionError(
                    f"Pexels HTTP {response.status_code}: {response.text[:240]}"
                )
            return response.json()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _download(self, url: str, dest: Path) -> None:
        data = self._download_bytes(url)
        if not data:
            raise AssetAcquisitionError(f"Downloaded empty file from {url}")
        dest.write_bytes(data)

    def _download_bytes(self, url: str) -> bytes:
        with httpx.Client(timeout=self._http_timeout, follow_redirects=True) as client:
            response = client.get(url)
            if response.status_code == 429:
                raise _RateLimited(f"HTTP 429 downloading {url}")
            response.raise_for_status()
            return response.content

    @staticmethod
    def _build_query(scene: SceneData) -> str:
        if scene.keywords:
            return " ".join(scene.keywords[:6]).strip()
        # Fall back to a short slice of narration / visual prompt.
        text = scene.script_text or scene.visual_prompt
        return " ".join(text.split()[:8]).strip() or "nature landscape"


class _RateLimited(Exception):
    """Internal signal that the upstream API returned HTTP 429."""

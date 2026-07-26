"""Generative AI asset acquisition for per-scene stills.

Default provider
----------------
- ``imagen``: Google Imagen 3 via ``google-genai`` (requires ``GEMINI_API_KEY``)
  → save as ``scene_XX.jpg``

Optional
--------
- ``pollinations``: free Pollinations.ai images (no API key)
- ``openai_image``: paid OpenAI DALL-E 3 (requires ``OPENAI_API_KEY``)

Stock footage (Pixabay / Pexels) has been removed so era/character continuity
comes from generative prompts instead of mismatched modern stock clips.

Background music (BGM) is still fetched via Internet Archive / static URLs.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from PIL import Image
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import AssetProvider, Settings, get_settings
from youtube_pipeline.exceptions import AssetAcquisitionError, ConfigurationError
from youtube_pipeline.models import MediaAsset, SceneData, VideoScript
from youtube_pipeline.utils.files import ensure_dir
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"
ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"
ARCHIVE_METADATA = "https://archive.org/metadata/{identifier}"

# Style -> search phrases for royalty-free / CC background music.
STYLE_BGM_QUERIES: dict[str, list[str]] = {
    "cinematic": ["cinematic ambient instrumental", "epic orchestral ambient"],
    "documentary": ["documentary ambient instrumental", "soft piano ambient"],
    "corporate": ["corporate upbeat instrumental", "business background music"],
    "fast_paced_shorts": ["upbeat electronic instrumental", "energetic beat royalty free"],
    "animated": ["playful whimsical instrumental", "light cheerful background"],
    "minimal": ["minimal ambient piano", "calm soft ambient"],
    "suspense": ["suspense dark ambient", "thriller tension underscore"],
}

# Last-resort public demo tracks (used only if search APIs fail).
STYLE_BGM_STATIC_URLS: dict[str, str] = {
    "cinematic": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
    "documentary": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
    "corporate": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
    "fast_paced_shorts": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-8.mp3",
    "animated": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-9.mp3",
    "minimal": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-10.mp3",
    "suspense": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-14.mp3",
}

# Optional style suffixes for the OpenAI DALL-E path only.
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
    """Generate one local still image per scene (Imagen 3 by default).

    Files are saved as ``scene_XX.jpg`` (zero-padded ``scene_id``) so
    ``VideoComposer`` can map them instantly.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        # Pollinations / HTTP downloads can be slow under load.
        self._http_timeout = httpx.Timeout(120.0, connect=20.0)
        self._validate_provider_config()

    def _validate_provider_config(self) -> None:
        provider = self.settings.asset_provider
        if provider == AssetProvider.IMAGEN and not self.settings.gemini_api_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is required when ASSET_PROVIDER=imagen"
            )
        if provider == AssetProvider.OPENAI_IMAGE and not self.settings.openai_api_key:
            raise ConfigurationError(
                "OPENAI_API_KEY is required when ASSET_PROVIDER=openai_image"
            )
        # pollinations.ai is free and keyless — no config required.

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire_all(self, script: VideoScript, output_dir: Path | str) -> list[MediaAsset]:
        """Download/generate one asset per scene into ``output_dir``."""
        if not script.scenes:
            raise AssetAcquisitionError("VideoScript.scenes is empty; nothing to acquire")

        assets_dir = ensure_dir(Path(output_dir))
        style = (script.style or "cinematic").strip().lower()
        provider = self.settings.asset_provider
        assets: list[MediaAsset] = []
        failures: list[str] = []

        logger.info(
            "Asset acquisition start | provider=%s | scenes=%d | style=%s | dir=%s",
            provider.value,
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
        """Route a single scene to the configured generative image provider."""
        provider = self.settings.asset_provider
        if provider == AssetProvider.IMAGEN:
            return self._fetch_imagen_image(scene, output_dir)
        if provider == AssetProvider.OPENAI_IMAGE:
            return self._fetch_openai_image(scene, output_dir, style=style)
        return self._fetch_pollinations_image(scene, output_dir)

    # ------------------------------------------------------------------
    # Google Imagen 3 (high-quality default)
    # ------------------------------------------------------------------

    def _fetch_imagen_image(self, scene: SceneData, output_dir: Path) -> MediaAsset:
        """Generate a 16:9 still with Google Imagen 3 and save as ``scene_XX.jpg``."""
        prompt = (scene.visual_prompt or "").strip()
        if not prompt:
            prompt = (scene.script_text or "cinematic still frame").strip()

        width = int(self.settings.video_width or 1920)
        height = int(self.settings.video_height or 1080)
        dest = ensure_dir(output_dir) / f"scene_{scene.scene_id:02d}.jpg"
        model = self.settings.imagen_model or "imagen-3.0-generate-002"

        logger.info(
            "Imagen generate | scene=%d | model=%s | prompt=%r",
            scene.scene_id,
            model,
            prompt[:160],
        )

        try:
            image_bytes = self._generate_imagen(prompt, model=model)
            if not image_bytes or len(image_bytes) < 256:
                raise AssetAcquisitionError("Imagen returned empty/tiny image bytes")
            dest.write_bytes(image_bytes)
            self._ensure_jpeg(dest)
            return MediaAsset(
                scene_id=scene.scene_id,
                path=str(dest.resolve()),
                source="imagen",
                media_type="image",
                width=width,
                height=height,
                attribution="Generated via Google Imagen 3",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Imagen failed for scene %d (%s); writing solid fallback",
                scene.scene_id,
                exc,
            )
            return self._write_black_fallback(scene, output_dir)

    def _generate_imagen(self, prompt: str, *, model: str) -> bytes:
        """Call ``google-genai`` ``generate_images`` and return raw image bytes."""
        from google import genai
        from google.genai import types

        if not self.settings.gemini_api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for imagen provider")

        client = genai.Client(api_key=self.settings.gemini_api_key)
        result = client.models.generate_images(
            model=model,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="16:9",
            ),
        )
        generated = getattr(result, "generated_images", None) or []
        if not generated:
            raise AssetAcquisitionError("Imagen response contained no generated_images")
        image = getattr(generated[0], "image", None)
        image_bytes = getattr(image, "image_bytes", None) if image is not None else None
        if not image_bytes:
            raise AssetAcquisitionError("Imagen response missing image.image_bytes")
        return bytes(image_bytes)

    # ------------------------------------------------------------------
    # Pollinations.ai (free generative images)
    # ------------------------------------------------------------------

    def _fetch_pollinations_image(self, scene: SceneData, output_dir: Path) -> MediaAsset:
        """URL-encode visual_prompt and download a 1920x1080 JPEG from Pollinations."""
        prompt = (scene.visual_prompt or "").strip()
        if not prompt:
            prompt = (scene.script_text or "cinematic still frame").strip()

        width = int(self.settings.video_width or 1920)
        height = int(self.settings.video_height or 1080)
        dest = ensure_dir(output_dir) / f"scene_{scene.scene_id:02d}.jpg"

        encoded = quote(prompt, safe="")
        url = (
            f"{POLLINATIONS_BASE}/{encoded}"
            f"?width={width}&height={height}&nologo=true"
        )

        logger.info(
            "Pollinations generate | scene=%d | prompt=%r | size=%dx%d",
            scene.scene_id,
            prompt[:160],
            width,
            height,
        )

        try:
            self._download_image(url, dest)
            if not dest.exists() or dest.stat().st_size < 256:
                raise AssetAcquisitionError("Pollinations returned an empty/tiny image")
            # Normalize to JPEG in case the CDN returns PNG/WebP bytes.
            self._ensure_jpeg(dest)
            return MediaAsset(
                scene_id=scene.scene_id,
                path=str(dest.resolve()),
                source="pollinations",
                media_type="image",
                width=width,
                height=height,
                attribution="Generated via pollinations.ai",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Pollinations failed for scene %d (%s); writing solid fallback",
                scene.scene_id,
                exc,
            )
            return self._write_black_fallback(scene, output_dir)

    def _download_image(self, url: str, dest: Path) -> None:
        """GET an image URL with retries and write bytes to ``dest``."""
        self._download(url, dest)

    @staticmethod
    def _ensure_jpeg(path: Path) -> None:
        """Re-encode the file as JPEG if needed so composers always see ``.jpg``."""
        try:
            with Image.open(path) as img:
                rgb = img.convert("RGB")
                rgb.save(path, format="JPEG", quality=92)
        except Exception:  # noqa: BLE001
            # If Pillow cannot decode, leave raw bytes — MoviePy may still load them.
            pass

    # ------------------------------------------------------------------
    # Optional OpenAI DALL-E 3
    # ------------------------------------------------------------------

    def _fetch_openai_image(
        self,
        scene: SceneData,
        output_dir: Path,
        *,
        style: str = "cinematic",
    ) -> MediaAsset:
        if not self.settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required for openai_image provider")

        prompt = self._style_augmented_prompt(scene.visual_prompt, style)
        logger.info("OpenAI DALL-E generate | scene=%d | prompt=%r", scene.scene_id, prompt[:160])
        image_bytes = self._generate_dalle(prompt)
        dest = ensure_dir(output_dir) / f"scene_{scene.scene_id:02d}.jpg"
        # DALL-E often returns PNG bytes; normalize to JPEG for consistent naming.
        tmp = dest.with_suffix(".png")
        tmp.write_bytes(image_bytes)
        try:
            with Image.open(tmp) as img:
                img.convert("RGB").save(dest, format="JPEG", quality=92)
            tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            # Fall back to writing raw bytes under .jpg name.
            dest.write_bytes(image_bytes)
            tmp.unlink(missing_ok=True)

        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(dest.resolve()),
            source="openai_dalle3",
            media_type="image",
            width=self.settings.video_width,
            height=self.settings.video_height,
            attribution="Generated by OpenAI DALL-E 3",
        )

    def _generate_dalle(self, prompt: str) -> bytes:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        model = self.settings.openai_image_model or "dall-e-3"
        response = client.images.generate(
            model=model,
            prompt=prompt[:3900],
            size="1792x1024",
            quality="standard",
            n=1,
            response_format="b64_json",
        )
        b64 = response.data[0].b64_json
        if not b64:
            raise AssetAcquisitionError("OpenAI image response missing b64_json")
        return base64.b64decode(b64)

    @staticmethod
    def _style_augmented_prompt(visual_prompt: str, style: str) -> str:
        base = visual_prompt.strip()
        suffix = STYLE_PROMPT_SUFFIX.get(style.lower(), STYLE_PROMPT_SUFFIX["cinematic"])
        if suffix.split(",")[0].lower() in base.lower():
            return base
        return f"{base}, {suffix}"

    # ------------------------------------------------------------------
    # HTTP helpers / fallbacks
    # ------------------------------------------------------------------

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
            content_type = (response.headers.get("content-type") or "").lower()
            if "text/html" in content_type or "application/json" in content_type:
                raise AssetAcquisitionError(
                    f"Expected image bytes but got content-type={content_type}"
                )
            return response.content

    def _write_black_fallback(self, scene: SceneData, output_dir: Path) -> MediaAsset:
        """Always-succeeding solid black JPEG so MoviePy never sees a missing asset."""
        width = self.settings.video_width or 1920
        height = self.settings.video_height or 1080
        dest = ensure_dir(output_dir) / f"scene_{scene.scene_id:02d}.jpg"
        Image.new("RGB", (width, height), (0, 0, 0)).save(dest, format="JPEG", quality=90)
        logger.info(
            "Black fallback image written | scene=%d | path=%s",
            scene.scene_id,
            dest,
        )
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(dest.resolve()),
            source="black_fallback",
            media_type="image",
            width=width,
            height=height,
            attribution="Solid black fallback (generative image failed)",
        )

    # ------------------------------------------------------------------
    # Background music (BGM)
    # ------------------------------------------------------------------

    def fetch_bgm(self, style: str, output_dir: Path | str) -> Path | None:
        """Download a single BGM track for ``style`` into ``output_dir/bgm.mp3``.

        1. Searches Internet Archive for Creative Commons instrumental audio
        2. Falls back to a curated public demo MP3 URL for the style
        3. Returns ``None`` (skip BGM) if everything fails — never crashes
        """
        assets_dir = ensure_dir(Path(output_dir))
        dest = assets_dir / "bgm.mp3"
        style_key = (style or "cinematic").strip().lower()
        queries = STYLE_BGM_QUERIES.get(style_key, STYLE_BGM_QUERIES["cinematic"])

        logger.info("BGM fetch start | style=%s | queries=%s", style_key, queries)

        for query in queries:
            try:
                path = self._fetch_bgm_from_archive(query, dest)
                if path is not None:
                    logger.info(
                        "BGM acquired via Internet Archive | query=%r | path=%s",
                        query,
                        path,
                    )
                    return path
            except Exception as exc:  # noqa: BLE001
                logger.warning("Archive.org BGM search failed | query=%r | %s", query, exc)

        static_url = STYLE_BGM_STATIC_URLS.get(style_key) or STYLE_BGM_STATIC_URLS["cinematic"]
        try:
            self._download(static_url, dest)
            if dest.exists() and dest.stat().st_size > 1024:
                logger.info(
                    "BGM acquired via static fallback URL | style=%s | path=%s",
                    style_key,
                    dest,
                )
                return dest
        except Exception as exc:  # noqa: BLE001
            logger.warning("Static BGM fallback failed | style=%s | %s", style_key, exc)

        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        logger.warning(
            "BGM unavailable for style=%s — continuing without background music",
            style_key,
        )
        return None

    def _fetch_bgm_from_archive(self, query: str, dest: Path) -> Path | None:
        """Search archive.org for an MP3 matching ``query`` and download it."""
        q = (
            f"({query}) AND mediatype:audio AND format:MP3 "
            f"AND NOT subject:speech AND NOT subject:podcast"
        )
        params = {
            "q": q,
            "fl[]": ["identifier", "title"],
            "rows": 5,
            "page": 1,
            "output": "json",
            "sort[]": "downloads desc",
        }
        with httpx.Client(timeout=self._http_timeout, follow_redirects=True) as client:
            response = client.get(ARCHIVE_SEARCH, params=params)
            if response.status_code == 429:
                raise _RateLimited(f"HTTP 429 from {ARCHIVE_SEARCH}")
            if response.status_code >= 400:
                logger.warning(
                    "Archive.org search HTTP %s: %s",
                    response.status_code,
                    response.text[:200],
                )
                return None
            docs = (((response.json() or {}).get("response") or {}).get("docs")) or []

        for doc in docs:
            identifier = doc.get("identifier")
            if not identifier:
                continue
            mp3_url = self._archive_pick_mp3_url(str(identifier))
            if not mp3_url:
                continue
            try:
                self._download(mp3_url, dest)
                if dest.exists() and dest.stat().st_size > 1024:
                    return dest
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Archive.org download failed | id=%s | %s",
                    identifier,
                    exc,
                )
                continue
        return None

    def _archive_pick_mp3_url(self, identifier: str) -> str | None:
        """Resolve a downloadable MP3 URL for an archive.org item."""
        meta_url = ARCHIVE_METADATA.format(identifier=identifier)
        with httpx.Client(timeout=self._http_timeout, follow_redirects=True) as client:
            response = client.get(meta_url)
            if response.status_code >= 400:
                return None
            payload = response.json() or {}

        files = payload.get("files") or []
        mp3_files = [
            f
            for f in files
            if str(f.get("name", "")).lower().endswith(".mp3")
            and "spectrogram" not in str(f.get("name", "")).lower()
        ]
        if not mp3_files:
            return None

        def _size(item: dict[str, Any]) -> int:
            try:
                return int(item.get("size") or 0)
            except (TypeError, ValueError):
                return 0

        mp3_files.sort(key=_size)
        chosen = mp3_files[len(mp3_files) // 2]
        name = chosen.get("name")
        if not name:
            return None
        return f"https://archive.org/download/{identifier}/{name}"


class _RateLimited(Exception):
    """Internal signal that the upstream API returned HTTP 429."""

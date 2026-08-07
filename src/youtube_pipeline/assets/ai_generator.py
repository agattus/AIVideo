"""AI image generation providers (OpenAI Images; extensible for Midjourney/Runway)."""

from __future__ import annotations

from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from youtube_pipeline.assets.image_aspect import aspect_prompt_clause
from youtube_pipeline.exceptions import AssetAcquisitionError, ConfigurationError
from youtube_pipeline.models import MediaAsset, SceneData
from youtube_pipeline.utils.files import ensure_dir, slugify
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

# DALL-E 3 / gpt-image supported sizes closest to each aspect.
_OPENAI_SIZES: dict[str, str] = {
    "16:9": "1792x1024",
    "9:16": "1024x1792",
    "1:1": "1024x1024",
}


def openai_image_size(aspect_ratio: str) -> str:
    return _OPENAI_SIZES.get(aspect_ratio, "1792x1024")


class OpenAIImageProvider:
    """Generate scene stills with OpenAI Images (DALL-E / gpt-image)."""

    name = "openai_image"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required for asset provider 'openai_image'")

    def fetch_for_scene(
        self,
        scene: SceneData,
        output_dir: Path,
        *,
        aspect_ratio: str = "16:9",
    ) -> MediaAsset:
        logger.info("OpenAI image gen | scene=%d | aspect=%s", scene.scene_id, aspect_ratio)
        prompt = f"{scene.visual_prompt}\n\n{aspect_prompt_clause(aspect_ratio)}"
        size = openai_image_size(aspect_ratio)
        try:
            image_bytes = self._generate(prompt, size=size)
        except Exception as exc:  # noqa: BLE001
            raise AssetAcquisitionError(f"OpenAI image generation failed: {exc}") from exc

        dest = ensure_dir(output_dir) / f"scene_{scene.scene_id:02d}_{slugify(scene.visual_prompt)[:40]}.png"
        dest.write_bytes(image_bytes)
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(dest),
            source=self.name,
            media_type="image",
            attribution="AI-generated via OpenAI Images",
        )

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _generate(self, prompt: str, *, size: str = "1792x1024") -> bytes:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        result = client.images.generate(
            model=self.settings.openai_image_model,
            prompt=prompt,
            size=size,
            n=1,
        )
        item = result.data[0]
        # Prefer URL download; fall back to b64 when provided.
        if getattr(item, "b64_json", None):
            import base64

            return base64.b64decode(item.b64_json)

        url = getattr(item, "url", None)
        if not url:
            raise AssetAcquisitionError("OpenAI image response missing url/b64_json")

        with httpx.Client(timeout=60.0, follow_redirects=True) as http:
            response = http.get(url)
            response.raise_for_status()
            return response.content

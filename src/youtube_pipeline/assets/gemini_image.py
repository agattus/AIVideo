"""Gemini native image generation (Nano Banana / flash-image models)."""

from __future__ import annotations

from pathlib import Path

import google.generativeai as genai
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from youtube_pipeline.exceptions import AssetAcquisitionError, ConfigurationError
from youtube_pipeline.models import MediaAsset, SceneData
from youtube_pipeline.utils.files import ensure_dir, slugify
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


class GeminiImageProvider:
    name = "gemini_image"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.gemini_api_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is required for asset provider 'gemini_image'"
            )
        genai.configure(api_key=self.settings.gemini_api_key)

    def fetch_for_scene(self, scene: SceneData, output_dir: Path) -> MediaAsset:
        logger.info("Gemini image gen | scene=%d", scene.scene_id)
        try:
            image_bytes = self._generate(scene.visual_prompt)
        except Exception as exc:  # noqa: BLE001
            raise AssetAcquisitionError(f"Gemini image generation failed: {exc}") from exc

        dest = ensure_dir(output_dir) / (
            f"scene_{scene.scene_id:02d}_{slugify(scene.visual_prompt)[:40]}.png"
        )
        dest.write_bytes(image_bytes)
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(dest),
            source=self.name,
            media_type="image",
            attribution="AI-generated via Gemini",
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        # "No image data" / safety-style failures from _extract_image_bytes are
        # deterministic (same prompt -> same outcome); retrying just burns 3x the
        # API calls and ~30s of backoff for nothing. Only transient errors raised by
        # the SDK/transport itself (timeouts, 429/5xx, etc.) should be retried.
        retry=retry_if_not_exception_type(AssetAcquisitionError),
    )
    def _generate(self, prompt: str) -> bytes:
        model = genai.GenerativeModel(self.settings.gemini_image_model)
        # Image-output models on the v1beta surface require response_modalities to
        # include IMAGE, otherwise a text-only response is a plausible outcome for
        # every scene. This is supported by the installed google-generativeai
        # (legacy) SDK via a plain dict passed through to the underlying proto.
        response = model.generate_content(
            prompt,
            generation_config={"response_modalities": ["TEXT", "IMAGE"]},
        )
        return _extract_image_bytes(response)


def _extract_image_bytes(response: object) -> bytes:
    parts = getattr(response, "parts", None) or []
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline is None:
            continue
        data = getattr(inline, "data", None)
        if data:
            return bytes(data) if not isinstance(data, bytes) else data
    raise AssetAcquisitionError("Gemini response contained no image data")

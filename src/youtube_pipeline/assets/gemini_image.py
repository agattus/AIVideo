"""Gemini native image generation (Nano Banana / flash-image models)."""

from __future__ import annotations

from pathlib import Path

import google.generativeai as genai
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from youtube_pipeline.assets.image_aspect import aspect_prompt_clause, normalize_image_to_aspect
from youtube_pipeline.exceptions import AssetAcquisitionError, ConfigurationError
from youtube_pipeline.models import MediaAsset, SceneData
from youtube_pipeline.utils.files import ensure_dir, slugify
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


def _is_quota_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "429" in text or "quota" in text or "resource_exhausted" in text


def _is_transient_gemini_error(exc: BaseException) -> bool:
    if isinstance(exc, AssetAcquisitionError) or _is_quota_error(exc):
        return False
    if isinstance(exc, TimeoutError):
        return True
    text = str(exc).lower()
    return any(token in text for token in ("timeout", "timed out", "503", "502", "unavailable"))


def _friendly_gemini_error(exc: BaseException) -> str:
    if _is_quota_error(exc):
        return (
            "Gemini API quota exceeded (free tier). "
            "Enable billing at https://ai.google.dev or copy the prompt and upload "
            "an image from Flow. Gemini Plus does not add API image quota."
        )
    text = str(exc).strip()
    if len(text) > 280:
        text = text[:277] + "..."
    return f"Gemini image generation failed: {text}"


def _sdk_supports_aspect_ratio_config() -> bool:
    """True when the active Gemini client exposes typed aspect-ratio generation config."""
    try:
        from google.generativeai.types.generation_types import GenerationConfigDict

        return "aspect_ratio" in GenerationConfigDict.__annotations__
    except (ImportError, AttributeError):
        return False


def _aspect_ratio_generation_config(aspect_ratio: str) -> dict[str, object]:
    if aspect_ratio not in ("16:9", "9:16", "1:1"):
        return {}
    if not _sdk_supports_aspect_ratio_config():
        return {}
    return {"aspect_ratio": aspect_ratio}


class GeminiImageProvider:
    name = "gemini_image"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.gemini_api_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is required for asset provider 'gemini_image'"
            )
        genai.configure(api_key=self.settings.gemini_api_key)

    def fetch_for_scene(
        self,
        scene: SceneData,
        output_dir: Path,
        *,
        aspect_ratio: str = "16:9",
    ) -> MediaAsset:
        logger.info("Gemini image gen | scene=%d | aspect=%s", scene.scene_id, aspect_ratio)
        prompt = f"{scene.visual_prompt}\n\n{aspect_prompt_clause(aspect_ratio)}"
        try:
            image_bytes = self._generate(prompt, aspect_ratio=aspect_ratio)
        except AssetAcquisitionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AssetAcquisitionError(_friendly_gemini_error(exc)) from exc

        try:
            image_bytes = normalize_image_to_aspect(image_bytes, aspect_ratio)
        except Exception as exc:  # noqa: BLE001
            raise AssetAcquisitionError(
                f"Failed to normalize scene image to aspect ratio {aspect_ratio}: {exc}"
            ) from exc

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
        # Only brief transport blips. Quota/429 and empty-image responses are
        # deterministic for this run — retrying burns the free tier faster.
        retry=retry_if_exception(_is_transient_gemini_error),
    )
    def _generate(self, prompt: str, *, aspect_ratio: str = "16:9") -> bytes:
        model = genai.GenerativeModel(self.settings.gemini_image_model)
        generation_config: dict[str, object] = {
            "response_modalities": ["TEXT", "IMAGE"],
            **_aspect_ratio_generation_config(aspect_ratio),
        }
        try:
            response = model.generate_content(
                prompt,
                generation_config=generation_config,
            )
        except Exception as exc:  # noqa: BLE001
            if _is_quota_error(exc):
                raise AssetAcquisitionError(_friendly_gemini_error(exc)) from exc
            raise
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

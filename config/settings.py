"""Centralized application settings loaded from environment variables."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    GEMINI = "gemini"
    GROQ = "groq"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class TTSProvider(str, Enum):
    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"
    GTTS = "gtts"
    EDGE_TTS = "edge-tts"


class AssetProvider(str, Enum):
    """Generative image providers (stock footage removed for era/character lock)."""

    POLLINATIONS = "pollinations"  # free, keyless — default
    OPENAI_IMAGE = "openai_image"  # paid DALL-E 3 optional


class VisualStyle(str, Enum):
    CINEMATIC = "cinematic"
    DOCUMENTARY = "documentary"
    CORPORATE = "corporate"
    FAST_PACED_SHORTS = "fast_paced_shorts"
    ANIMATED = "animated"
    MINIMAL = "minimal"


_API_KEY_FIELDS = (
    "gemini_api_key",
    "groq_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "elevenlabs_api_key",
    "elevenlabs_voice_id",
)


def sanitize_secret(value: str | None) -> str | None:
    """Normalize secrets from .env files (strip whitespace / surrounding quotes)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Common .env footguns: KEY="value" or KEY='value'
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()
    # Invisible BOM / zero-width chars that break auth headers
    text = text.lstrip("\ufeff").replace("\u200b", "").strip()
    return text or None


def mask_secret(value: str | None) -> str:
    """Safe diagnostic preview of a secret (never logs the full key)."""
    if not value:
        return "<unset>"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]} (len={len(value)})"


class Settings(BaseSettings):
    """Runtime configuration for the YouTube automation pipeline."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Allow both GROQ_API_KEY and nested env styles.
        case_sensitive=False,
    )

    # LLM (script generation defaults to Gemini)
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    llm_provider: LLMProvider = LLMProvider.GEMINI
    llm_model: str = "gemini-1.5-flash"

    # TTS
    tts_provider: TTSProvider = TTSProvider.OPENAI
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    # Microsoft Edge neural voices (used when TTS_PROVIDER=edge-tts)
    edge_tts_voice: str = "en-US-ChristopherNeural"

    # Assets — default free Pollinations.ai generative images (no API key)
    asset_provider: AssetProvider = AssetProvider.POLLINATIONS
    openai_image_model: str = "dall-e-3"  # only used when ASSET_PROVIDER=openai_image

    # Output / video
    output_dir: Path = Field(default=Path("./output"))
    assets_cache_dir: Path = Field(default=Path("./assets_cache"))
    video_width: int = 1920
    video_height: int = 1080
    video_fps: int = 30
    default_style: VisualStyle = VisualStyle.CINEMATIC
    log_level: str = "INFO"

    @field_validator(*_API_KEY_FIELDS, mode="before")
    @classmethod
    def _sanitize_api_keys(cls, value: str | None) -> str | None:
        return sanitize_secret(value)

    @field_validator("asset_provider", mode="before")
    @classmethod
    def _coerce_legacy_asset_provider(cls, value: object) -> object:
        """Map pre-merge stock providers onto Pollinations so old .env files still boot."""
        if value is None:
            return AssetProvider.POLLINATIONS
        text = str(value).strip().lower()
        legacy = {
            "pixabay": AssetProvider.POLLINATIONS,
            "pexels": AssetProvider.POLLINATIONS,
            "stock": AssetProvider.POLLINATIONS,
        }
        if text in legacy:
            import logging

            logging.getLogger(__name__).warning(
                "ASSET_PROVIDER=%s is deprecated (stock footage removed); "
                "using 'pollinations' instead. Update your .env.",
                text,
            )
            return legacy[text]
        return value

    @field_validator("output_dir", "assets_cache_dir", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path) -> Path:
        return Path(value)

    def ensure_directories(self) -> None:
        """Create output and cache directories if they do not exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.assets_cache_dir.mkdir(parents=True, exist_ok=True)

    def describe_secrets(self) -> dict[str, str]:
        """Return masked secret diagnostics for CLI troubleshooting."""
        return {
            "GEMINI_API_KEY": mask_secret(self.gemini_api_key),
            "GROQ_API_KEY": mask_secret(self.groq_api_key),
            "OPENAI_API_KEY": mask_secret(self.openai_api_key),
            "ANTHROPIC_API_KEY": mask_secret(self.anthropic_api_key),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings

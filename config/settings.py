"""Centralized application settings loaded from environment variables."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    GROQ = "groq"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class TTSProvider(str, Enum):
    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"


class AssetProvider(str, Enum):
    PEXELS = "pexels"
    PIXABAY = "pixabay"
    OPENAI_IMAGE = "openai_image"


class VisualStyle(str, Enum):
    CINEMATIC = "cinematic"
    DOCUMENTARY = "documentary"
    CORPORATE = "corporate"
    FAST_PACED_SHORTS = "fast_paced_shorts"
    ANIMATED = "animated"
    MINIMAL = "minimal"


class Settings(BaseSettings):
    """Runtime configuration for the YouTube automation pipeline."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM (script generation defaults to Groq free tier)
    groq_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    llm_provider: LLMProvider = LLMProvider.GROQ
    llm_model: str = "llama-3.3-70b-versatile"

    # TTS
    tts_provider: TTSProvider = TTSProvider.OPENAI
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None

    # Assets
    asset_provider: AssetProvider = AssetProvider.PEXELS
    pexels_api_key: str | None = None
    pixabay_api_key: str | None = None
    openai_image_model: str = "dall-e-3"  # DALL·E 3 fallback for asset acquisition

    # Output / video
    output_dir: Path = Field(default=Path("./output"))
    assets_cache_dir: Path = Field(default=Path("./assets_cache"))
    video_width: int = 1920
    video_height: int = 1080
    video_fps: int = 30
    default_style: VisualStyle = VisualStyle.CINEMATIC
    log_level: str = "INFO"

    @field_validator("output_dir", "assets_cache_dir", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path) -> Path:
        return Path(value)

    def ensure_directories(self) -> None:
        """Create output and cache directories if they do not exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.assets_cache_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings

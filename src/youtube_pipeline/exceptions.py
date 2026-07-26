"""Pipeline-specific exceptions."""

from __future__ import annotations


class PipelineError(Exception):
    """Base error for the YouTube automation pipeline."""


class ScriptGenerationError(PipelineError):
    """Raised when the LLM fails to produce a valid script package."""


class AudioGenerationError(PipelineError):
    """Raised when TTS or subtitle generation fails."""


class AssetAcquisitionError(PipelineError):
    """Raised when visual assets cannot be obtained."""


class QuotaExceededError(AssetAcquisitionError):
    """Raised when an image/LLM provider hits a daily/rate quota limit."""


class VideoCompositionError(PipelineError):
    """Raised when MoviePy / FFmpeg composition fails."""


class ConfigurationError(PipelineError):
    """Raised when required API keys or settings are missing."""

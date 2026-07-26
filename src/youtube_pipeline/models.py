"""Shared Pydantic v2 data contracts between pipeline stages."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VisualStyle(str, Enum):
    """Supported visual styles for script prompting and composition."""

    CINEMATIC = "cinematic"
    DOCUMENTARY = "documentary"
    CORPORATE = "corporate"
    FAST_PACED_SHORTS = "fast_paced_shorts"
    ANIMATED = "animated"
    MINIMAL = "minimal"


class AspectRatio(str, Enum):
    LANDSCAPE = "16:9"
    VERTICAL = "9:16"
    SQUARE = "1:1"


class SceneData(BaseModel):
    """One narrative beat: spoken text, visual direction, and timed duration."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    scene_id: int = Field(ge=0, description="Zero-based scene index")
    script_text: str = Field(min_length=1, description="Narration spoken during this scene")
    visual_prompt: str = Field(
        min_length=1,
        description="Detailed image/video generation prompt for this scene",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Stock-search keywords for asset acquisition",
    )
    duration: float = Field(
        default=0.0,
        ge=0.0,
        description="Scene duration in seconds (populated by TTS timing)",
    )

    @field_validator("keywords")
    @classmethod
    def _normalize_keywords(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            kw = raw.strip().lower()
            if not kw or kw in seen:
                continue
            seen.add(kw)
            cleaned.append(kw)
        return cleaned

    @field_validator("script_text", "visual_prompt")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Field must not be blank")
        return value.strip()


class VideoScript(BaseModel):
    """Full voiceover package produced by the script engine and timed by TTS."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=1)
    full_script: str = Field(min_length=1, description="Complete voiceover text")
    style: str = Field(min_length=1, description="Visual style label, e.g. cinematic")
    scenes: list[SceneData] = Field(min_length=1)

    @field_validator("style")
    @classmethod
    def _normalize_style(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def _validate_scene_ids(self) -> VideoScript:
        ids = [scene.scene_id for scene in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("SceneData.scene_id values must be unique")
        # Prefer contiguous 0..N-1 but tolerate any unique non-negative ids.
        return self

    @property
    def total_duration(self) -> float:
        """Sum of per-scene durations (seconds)."""
        return float(sum(scene.duration for scene in self.scenes))

    def scene_by_id(self, scene_id: int) -> SceneData:
        for scene in self.scenes:
            if scene.scene_id == scene_id:
                return scene
        raise KeyError(f"No scene with scene_id={scene_id}")


class PipelineResult(BaseModel):
    """Final artifact contract returned by composition / orchestration."""

    model_config = ConfigDict(extra="forbid")

    video_path: str = Field(min_length=1, description="Filesystem path to the rendered MP4")
    status: str = Field(
        min_length=1,
        description="Pipeline status: success | failed | partial | awaiting_assets | running",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def _normalize_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"success", "failed", "partial", "running", "awaiting_assets"}
        if normalized not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}, got {value!r}")
        return normalized


class PipelineRequest(BaseModel):
    """User-facing inputs that kick off a full render (orchestrator / CLI)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    idea: str = Field(min_length=3, description="Core topic or video idea")
    style: VisualStyle = VisualStyle.CINEMATIC
    aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE
    target_duration_seconds: int | None = Field(default=60, ge=15, le=3600)
    voice: str | None = None
    output_name: str | None = None
    # Raised ceiling so long --duration runs can request 1 scene / 15s.
    max_scenes: int = Field(default=8, ge=2, le=240)
    burn_captions: bool = True
    enable_ken_burns: bool = True


class WordTimestamp(BaseModel):
    """Word-level timing used by subtitle writers and alignment helpers."""

    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _end_after_start(self) -> WordTimestamp:
        if self.end < self.start:
            raise ValueError("WordTimestamp.end must be >= start")
        return self


class SubtitleCue(BaseModel):
    """A single burned-in / sidecar subtitle cue."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _end_after_start(self) -> SubtitleCue:
        if self.end < self.start:
            raise ValueError("SubtitleCue.end must be >= start")
        return self


class MediaAsset(BaseModel):
    """A local visual asset bound to a scene_id."""

    model_config = ConfigDict(extra="forbid")

    scene_id: int = Field(ge=0)
    path: str = Field(min_length=1)
    source: str = Field(min_length=1)
    media_type: str = Field(description="image | video")
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    attribution: str | None = None

    @field_validator("media_type")
    @classmethod
    def _validate_media_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"image", "video"}:
            raise ValueError("media_type must be 'image' or 'video'")
        return normalized

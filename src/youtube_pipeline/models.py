"""Shared domain models for the YouTube automation pipeline."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class VisualStyle(str, Enum):
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


class Scene(BaseModel):
    """A single narrative beat with voiceover text and visual direction."""

    index: int = Field(ge=0)
    narration: str = Field(min_length=1)
    visual_prompt: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    duration_hint_seconds: float | None = Field(default=None, ge=0.5)

    @field_validator("keywords")
    @classmethod
    def _normalize_keywords(cls, value: list[str]) -> list[str]:
        return [kw.strip().lower() for kw in value if kw and kw.strip()]


class ScriptPackage(BaseModel):
    """Full LLM-produced script package for a video."""

    title: str
    idea: str
    style: VisualStyle
    full_script: str
    scenes: list[Scene]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scenes")
    @classmethod
    def _require_scenes(cls, value: list[Scene]) -> list[Scene]:
        if not value:
            raise ValueError("ScriptPackage must contain at least one scene")
        return value


class WordTimestamp(BaseModel):
    word: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, value: float, info: Any) -> float:
        start = info.data.get("start", 0.0)
        if value < start:
            raise ValueError("WordTimestamp.end must be >= start")
        return value


class SubtitleCue(BaseModel):
    index: int = Field(ge=1)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str = Field(min_length=1)


class AudioArtifact(BaseModel):
    """Generated voiceover audio and alignment data."""

    audio_path: Path
    duration_seconds: float = Field(gt=0)
    word_timestamps: list[WordTimestamp] = Field(default_factory=list)
    subtitle_cues: list[SubtitleCue] = Field(default_factory=list)
    srt_path: Path | None = None
    vtt_path: Path | None = None


class MediaAsset(BaseModel):
    """A single visual asset bound to a scene."""

    scene_index: int = Field(ge=0)
    path: Path
    source: str
    media_type: str = Field(description="image | video")
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    attribution: str | None = None


class TimedScene(BaseModel):
    """Scene with resolved start/end times against the voiceover."""

    scene: Scene
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    asset: MediaAsset | None = None

    @property
    def duration(self) -> float:
        return max(0.01, self.end - self.start)


class PipelineRequest(BaseModel):
    """User-facing inputs that kick off a full render."""

    idea: str = Field(min_length=3, description="Core topic or video idea")
    style: VisualStyle = VisualStyle.CINEMATIC
    aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE
    target_duration_seconds: int | None = Field(default=60, ge=15, le=1200)
    voice: str | None = None
    output_name: str | None = None
    max_scenes: int = Field(default=8, ge=2, le=30)
    burn_captions: bool = True
    enable_ken_burns: bool = True


class PipelineResult(BaseModel):
    """Artifacts produced by a successful pipeline run."""

    request: PipelineRequest
    script: ScriptPackage
    audio: AudioArtifact
    timed_scenes: list[TimedScene]
    video_path: Path
    srt_path: Path | None = None
    vtt_path: Path | None = None
    run_dir: Path

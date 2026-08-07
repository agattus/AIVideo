"""Shared Pydantic v2 data contracts between pipeline stages."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AMBIENCE_TAGS = frozenset(
    {"rain", "wind", "forest", "city", "ocean", "fire", "night", "room", "none"}
)
ONESHOT_TAGS = frozenset(
    {"thunder", "footsteps", "door", "birds", "crowd_cheer", "whoosh"}
)


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


class VideoFormat(str, Enum):
    NARRATIVE = "narrative"
    QUIZVERSE = "quizverse"
    DIALOGUE = "dialogue"


class QuizMode(str, Enum):
    COMMENT = "comment"
    REVEAL = "reveal"


class BeatType(str, Enum):
    HOOK = "hook"
    INTRO = "intro"
    QUESTION = "question"
    TIMER = "timer"
    REVEAL = "reveal"
    CTA = "cta"
    OUTRO = "outro"
    NARRATION = "narration"  # default for narrative scenes


class SfxCue(BaseModel):
    """A supported one-shot sound positioned within a scene."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    tag: str
    at: float

    @field_validator("tag")
    @classmethod
    def _normalize_tag(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ONESHOT_TAGS:
            raise ValueError(f"Unsupported SFX tag: {value!r}")
        return normalized

    @field_validator("at")
    @classmethod
    def _clamp_position(cls, value: float) -> float:
        return min(0.85, max(0.15, value))


class SceneData(BaseModel):
    """One narrative beat: spoken text, visual direction, and timed duration."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    scene_id: int = Field(ge=0, description="Zero-based scene index")
    script_text: str = Field(default="", description="Narration spoken during this scene")
    visual_prompt: str = Field(
        min_length=1,
        description="Detailed image/video generation prompt for this scene",
    )
    beat_type: BeatType = BeatType.NARRATION
    quiz_index: int | None = None
    question: str = ""
    choices: list[str] = Field(default_factory=list)
    answer: str = ""
    explain: str = ""
    hold_seconds: float | None = None
    keywords: list[str] = Field(
        default_factory=list,
        description="Stock-search keywords for asset acquisition",
    )
    duration: float = Field(
        default=0.0,
        ge=0.0,
        description="Scene duration in seconds (populated by TTS timing)",
    )
    ambience: str = "none"
    sfx: list[SfxCue] = Field(default_factory=list)
    speaker_id: str | None = None
    speaker_name: str = ""
    line_start: int | None = None
    line_end: int | None = None

    @field_validator("ambience", mode="before")
    @classmethod
    def _normalize_ambience(cls, value: Any) -> str:
        normalized = value.strip().lower() if isinstance(value, str) else "none"
        return normalized if normalized in AMBIENCE_TAGS else "none"

    @field_validator("sfx", mode="before")
    @classmethod
    def _normalize_sfx(cls, value: Any) -> list[SfxCue]:
        if not isinstance(value, list):
            return []
        normalized: list[SfxCue] = []
        for raw in value:
            try:
                cue = raw if isinstance(raw, SfxCue) else SfxCue.model_validate(raw)
            except (TypeError, ValueError):
                continue
            normalized.append(cue)
            if len(normalized) == 2:
                break
        return normalized

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

    @field_validator("visual_prompt")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Field must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def _validate_script_text(self) -> SceneData:
        if self.beat_type != BeatType.TIMER and not self.script_text.strip():
            raise ValueError("Field must not be blank")
        return self


class VideoScript(BaseModel):
    """Full voiceover package produced by the script engine and timed by TTS."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=1)
    full_script: str = Field(min_length=1, description="Complete voiceover text")
    style: str = Field(min_length=1, description="Visual style label, e.g. cinematic")
    format: str = "narrative"
    quiz_mode: str | None = None
    questions_raw: list[dict[str, Any]] = Field(default_factory=list)
    cast: list[dict[str, Any]] = Field(default_factory=list)
    lines: list[dict[str, Any]] = Field(default_factory=list)
    voice_map: dict[str, str] = Field(default_factory=dict)
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
        description="Pipeline status: success | failed | partial | waiting_for_assets | running",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def _normalize_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"success", "failed", "partial", "running", "waiting_for_assets"}
        if normalized not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}, got {value!r}")
        return normalized


class PipelineRequest(BaseModel):
    """User-facing inputs that kick off a full render (orchestrator / CLI)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    idea: str = Field(min_length=3, description="Core topic or video idea")
    format: VideoFormat = VideoFormat.NARRATIVE
    quiz_mode: QuizMode | None = None
    question_count: int | None = Field(default=None, ge=1, le=15)
    style: VisualStyle = VisualStyle.CINEMATIC
    aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE
    target_duration_seconds: int | None = Field(default=60, ge=15, le=3600)
    voice: str | None = None
    language: str = Field(
        default="en",
        description="Narration language code (en, te, hi, ta, …)",
    )
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

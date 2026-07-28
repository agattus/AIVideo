"""Pydantic contracts for the async video-generation REST API."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    WAITING_FOR_ASSETS = "waiting_for_assets"
    COMPLETED = "completed"
    FAILED = "failed"


class GenerateVideoRequest(BaseModel):
    """Mobile / REST payload that kicks off an async render job."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    idea: str = Field(min_length=3, description="Core topic or video idea")
    style: str = Field(default="cinematic", min_length=1)
    duration: int = Field(default=60, ge=15, le=3600, description="Target runtime in seconds")
    max_scenes: int = Field(default=8, ge=2, le=240)
    aspect_ratio: str = Field(
        default="16:9",
        description="16:9 (YouTube), 9:16 (Shorts), or 1:1 (square)",
    )


class DownloadUrls(BaseModel):
    """Public relative paths under the mounted ``/static`` volume."""

    model_config = ConfigDict(extra="forbid")

    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    script_url: Optional[str] = None
    assets_url: Optional[str] = None
    prompts_url: Optional[str] = None  # prompts.json for human-in-the-loop
    subtitles_url: Optional[str] = None  # sidecar .srt when captions are burned


class JobStatusResponse(BaseModel):
    """Realtime job state returned by ``GET /api/v1/status/{job_id}``."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus
    current_stage: str = ""
    progress_percent: int = Field(default=0, ge=0, le=100)
    download_urls: Optional[DownloadUrls] = None
    error: Optional[str] = None
    run_dir: Optional[str] = None
    scene_count: Optional[int] = None
    title: Optional[str] = None
    idea: Optional[str] = None
    updated_at: Optional[str] = None


class JobSummary(BaseModel):
    """Compact card for the previous-jobs library."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus
    title: str = ""
    idea: str = ""
    current_stage: str = ""
    progress_percent: int = 0
    scene_count: Optional[int] = None
    run_dir: Optional[str] = None
    updated_at: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    thumb_url: Optional[str] = None
    can_edit: bool = False


class JobListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[JobSummary] = Field(default_factory=list)
    count: int = 0


class ReopenAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus = JobStatus.WAITING_FOR_ASSETS
    message: str = "Job reopened for editing"


class GenerateVideoAccepted(BaseModel):
    """Immediate ``202 Accepted`` body from ``POST /api/v1/generate``."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus = JobStatus.QUEUED


class UploadAssetsAccepted(BaseModel):
    """Response after a ZIP upload (optionally kicks off resume assembly)."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus = JobStatus.PROCESSING
    message: str = "Assets uploaded — resume assembly started"
    scenes_ready: Optional[int] = None
    scene_count: Optional[int] = None
    all_scenes_ready: Optional[bool] = None


class SceneSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_number: int
    scene_id: int
    filename: str
    visual_prompt: str = ""
    script_text: str = ""
    duration_seconds: float = 0.0
    ready: bool = False
    preview_url: Optional[str] = None


class VoiceOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str


class WorkspaceResponse(BaseModel):
    """Full in-UI job studio: script, audio, scenes, prompts, BGM."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus
    can_edit: bool = False
    run_dir: Optional[str] = None
    idea: str = ""
    title: str = ""
    style: str = ""
    aspect_ratio: str = "16:9"
    scene_count: int = 0
    scenes_ready: int = 0
    all_scenes_ready: bool = False
    audio_ready: bool = False
    script_ready: bool = False
    video_ready: bool = False
    bgm_ready: bool = False
    audio_url: Optional[str] = None
    script_url: Optional[str] = None
    video_url: Optional[str] = None
    subtitles_url: Optional[str] = None
    bgm_url: Optional[str] = None
    prompts_url: Optional[str] = None
    prompts_csv_url: Optional[str] = None
    prompts_txt_url: Optional[str] = None
    current_voice: str = "en-US-ChristopherNeural"
    voice_options: list[VoiceOption] = Field(default_factory=list)
    clipboard_text: str = ""
    scenes: list[SceneSlot] = Field(default_factory=list)


class SceneUploadAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    scene_id: int
    filename: str
    ready: bool = True
    scenes_ready: int
    scene_count: int
    all_scenes_ready: bool
    message: str = "Scene image saved"


class BgmUpdateRequest(BaseModel):
    """Optional JSON body when refetching BGM by style (no file upload)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    style: Optional[str] = Field(
        default=None,
        description="Music style for auto-refetch (cinematic, documentary, …)",
    )


class BgmUpdateAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    bgm_ready: bool
    bgm_url: Optional[str] = None
    message: str = "Background music updated"


class VoiceoverUpdateAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    audio_ready: bool
    audio_url: Optional[str] = None
    current_voice: str = "en-US-ChristopherNeural"
    message: str = "Voiceover updated"


class AssembleAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus = JobStatus.PROCESSING
    message: str = "Assembly started"

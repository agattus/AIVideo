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


class GenerateVideoAccepted(BaseModel):
    """Immediate ``202 Accepted`` body from ``POST /api/v1/generate``."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus = JobStatus.QUEUED


class UploadAssetsAccepted(BaseModel):
    """Response after a ZIP upload kicks off resume assembly."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus = JobStatus.PROCESSING
    message: str = "Assets uploaded — resume assembly started"

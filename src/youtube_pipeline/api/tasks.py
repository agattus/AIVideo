"""Celery worker tasks for asynchronous video pipeline execution."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from celery import Celery

from youtube_pipeline.api.job_store import update_job
from youtube_pipeline.api.schemas import DownloadUrls, JobStatus
from youtube_pipeline.models import PipelineRequest, VisualStyle
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")


def _resolve_static_dir() -> Path:
    preferred = Path(os.getenv("STATIC_DIR", "/app/static"))
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path.cwd() / "static"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


STATIC_DIR = _resolve_static_dir()

# Celery application — broker defaults to the compose-network Redis service.
app = Celery(
    "youtube_pipeline",
    broker=REDIS_URL,
    backend=CELERY_RESULT_BACKEND,
)
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)


def _parse_style(raw: str) -> VisualStyle:
    try:
        return VisualStyle(raw.strip().lower())
    except ValueError:
        logger.warning("Unknown style %r — falling back to cinematic", raw)
        return VisualStyle.CINEMATIC


def _publish_progress(job_id: str, stage: int, stage_label: str, progress: int) -> None:
    """Push realtime stage updates to Redis under ``status:{job_id}``."""
    update_job(
        job_id,
        status=JobStatus.PROCESSING,
        current_stage=stage_label,
        progress_percent=progress,
    )
    logger.info(
        "Job progress | job_id=%s | stage=%d | progress=%d%% | %s",
        job_id,
        stage,
        progress,
        stage_label,
    )


def _publish_artifacts(job_id: str, *, video: Path, audio: Path, script: Path) -> DownloadUrls:
    """Copy finished artifacts into the shared ``/static`` volume for HTTP serving."""
    dest_dir = STATIC_DIR / job_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    video_name = "video.mp4"
    audio_name = "audio.mp3"
    script_name = "script.json"

    shutil.copy2(video, dest_dir / video_name)
    shutil.copy2(audio, dest_dir / audio_name)
    shutil.copy2(script, dest_dir / script_name)

    urls = DownloadUrls(
        video_url=f"/static/{job_id}/{video_name}",
        audio_url=f"/static/{job_id}/{audio_name}",
        script_url=f"/static/{job_id}/{script_name}",
    )
    logger.info("Artifacts published | job_id=%s | urls=%s", job_id, urls.model_dump())
    return urls


@app.task(name="youtube_pipeline.run_video_pipeline", bind=True)
def run_video_pipeline(self, job_id: str, request_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the full video pipeline for ``job_id`` and update Redis state.

    Parameters
    ----------
    job_id:
        UUID assigned by the FastAPI layer.
    request_data:
        Serialized ``GenerateVideoRequest`` fields
        (``idea``, ``style``, ``duration``, ``max_scenes``).
    """
    # Local import keeps Celery worker startup light when only inspecting tasks.
    from youtube_pipeline.orchestrator import VideoPipelineOrchestrator

    update_job(
        job_id,
        status=JobStatus.PROCESSING,
        current_stage="Stage 0/5: Starting pipeline",
        progress_percent=5,
    )

    try:
        pipeline_request = PipelineRequest(
            idea=str(request_data["idea"]),
            style=_parse_style(str(request_data.get("style") or "cinematic")),
            target_duration_seconds=int(request_data.get("duration") or 60),
            max_scenes=int(request_data.get("max_scenes") or 8),
            output_name=job_id,
        )

        orchestrator = VideoPipelineOrchestrator(
            on_progress=lambda stage, label, pct: _publish_progress(job_id, stage, label, pct),
        )
        result = orchestrator.run(pipeline_request)

        video_path = Path(result.video_path)
        meta = result.metadata or {}
        audio_path = Path(meta.get("audio_path") or "")
        script_path = Path(meta.get("script_path") or "")
        run_dir = Path(meta.get("run_dir") or video_path.parent)

        if not audio_path.exists():
            # Prefer the canonical TTS output location inside the run directory.
            candidate = run_dir / "audio" / "voiceover.mp3"
            audio_path = candidate if candidate.exists() else audio_path
        if not script_path.exists():
            candidate = run_dir / "script.json"
            script_path = candidate if candidate.exists() else script_path

        if not video_path.exists():
            raise FileNotFoundError(f"Rendered video missing: {video_path}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Voiceover audio missing: {audio_path}")
        if not script_path.exists():
            raise FileNotFoundError(f"Script JSON missing: {script_path}")

        download_urls = _publish_artifacts(
            job_id,
            video=video_path,
            audio=audio_path,
            script=script_path,
        )
        update_job(
            job_id,
            status=JobStatus.COMPLETED,
            current_stage="Completed",
            progress_percent=100,
            download_urls=download_urls,
            error=None,
        )
        return {
            "job_id": job_id,
            "status": JobStatus.COMPLETED.value,
            "download_urls": download_urls.model_dump(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline task failed | job_id=%s", job_id)
        update_job(
            job_id,
            status=JobStatus.FAILED,
            current_stage="Failed",
            progress_percent=100,
            error=str(exc),
        )
        # Re-raise so Celery marks the task as FAILURE for observability.
        raise

"""Celery worker tasks for asynchronous cinematic video pipeline execution."""

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
from youtube_pipeline.utils.paths import ensure_project_paths

# Critical for Windows / uvicorn thread workers: make ``config`` importable.
ensure_project_paths()

logger = get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")


def _resolve_static_dir() -> Path:
    preferred = Path(os.getenv("STATIC_DIR", "./static"))
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path.cwd() / "static"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


STATIC_DIR = _resolve_static_dir()

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
    """Push realtime stage updates under ``status:{job_id}``."""
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


def _publish_artifacts(
    job_id: str,
    *,
    audio: Path,
    script: Path,
    assets_dir: Path | None = None,
    video: Path | None = None,
) -> DownloadUrls:
    """Copy audio/script/(optional images) into ``/static`` for HTTP serving."""
    dest_dir = STATIC_DIR / job_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    audio_name = "audio.mp3"
    script_name = "script.json"
    shutil.copy2(audio, dest_dir / audio_name)
    shutil.copy2(script, dest_dir / script_name)

    video_url = None
    if video is not None and video.exists() and video.is_file() and video.suffix.lower() == ".mp4":
        video_name = "video.mp4"
        shutil.copy2(video, dest_dir / video_name)
        video_url = f"/static/{job_id}/{video_name}"

    assets_url = None
    if assets_dir is not None and assets_dir.exists():
        assets_dest = dest_dir / "assets"
        assets_dest.mkdir(parents=True, exist_ok=True)
        copied = 0
        for path in sorted(assets_dir.glob("scene_*.*")):
            if path.is_file():
                shutil.copy2(path, assets_dest / path.name)
                copied += 1
        if copied:
            assets_url = f"/static/{job_id}/assets/"

    urls = DownloadUrls(
        video_url=video_url,
        audio_url=f"/static/{job_id}/{audio_name}",
        script_url=f"/static/{job_id}/{script_name}",
        assets_url=assets_url,
    )
    logger.info("Artifacts published | job_id=%s | urls=%s", job_id, urls.model_dump())
    return urls


def _fail_job(job_id: str, exc: BaseException) -> None:
    logger.exception("Pipeline task failed | job_id=%s", job_id)
    try:
        update_job(
            job_id,
            status=JobStatus.FAILED,
            current_stage="Failed",
            progress_percent=100,
            error=str(exc),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not persist failed job state | job_id=%s", job_id)


def execute_video_pipeline(job_id: str, request_data: dict[str, Any]) -> dict[str, Any]:
    """Run the cinematic video pipeline and update job state. Safe for Celery or a thread."""
    ensure_project_paths()

    try:
        update_job(
            job_id,
            status=JobStatus.PROCESSING,
            current_stage="Stage 0/5: Starting cinematic video pipeline",
            progress_percent=5,
        )

        from youtube_pipeline.orchestrator import VideoPipelineOrchestrator

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

        meta = result.metadata or {}
        run_dir = Path(meta.get("run_dir") or "")
        video_path = Path(result.video_path)
        audio_path = Path(meta.get("audio_path") or "")
        script_path = Path(meta.get("script_path") or "")
        assets_dir = Path(meta.get("assets_dir") or (run_dir / "assets" if run_dir else ""))

        if run_dir and not audio_path.exists():
            candidate = run_dir / "audio" / "voiceover.mp3"
            audio_path = candidate if candidate.exists() else audio_path
        if run_dir and not script_path.exists():
            candidate = run_dir / "script.json"
            script_path = candidate if candidate.exists() else script_path

        if not audio_path.exists():
            raise FileNotFoundError(f"Voiceover audio missing: {audio_path}")
        if not script_path.exists():
            raise FileNotFoundError(f"Script JSON missing: {script_path}")
        if not video_path.exists() or video_path.suffix.lower() != ".mp4":
            raise FileNotFoundError(f"Compiled MP4 missing: {video_path}")

        download_urls = _publish_artifacts(
            job_id,
            audio=audio_path,
            script=script_path,
            assets_dir=assets_dir if assets_dir.exists() else None,
            video=video_path,
        )
        update_job(
            job_id,
            status=JobStatus.COMPLETED,
            current_stage="Completed — cinematic video ready",
            progress_percent=100,
            download_urls=download_urls,
            error=None,
        )
        return {
            "job_id": job_id,
            "status": JobStatus.COMPLETED.value,
            "download_urls": download_urls.model_dump(),
            "message": "Cinematic video compiled with AI visuals and BGM sync",
        }
    except Exception as exc:  # noqa: BLE001
        _fail_job(job_id, exc)
        raise


@app.task(name="youtube_pipeline.run_video_pipeline", bind=True)
def run_video_pipeline(self, job_id: str, request_data: dict[str, Any]) -> dict[str, Any]:
    """Celery entrypoint — delegates to ``execute_video_pipeline``."""
    return execute_video_pipeline(job_id, request_data)

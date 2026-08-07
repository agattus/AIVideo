"""Celery worker tasks for human-in-the-loop pause/resume video pipeline."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from celery import Celery

from youtube_pipeline.api.job_store import update_job
from youtube_pipeline.api.schemas import DownloadUrls, JobStatus
from youtube_pipeline.models import (
    AspectRatio,
    PipelineRequest,
    QuizMode,
    VideoFormat,
    VisualStyle,
)
from youtube_pipeline.script_engine.prompts import resolve_auto_scene_budget
from youtube_pipeline.utils.logging import get_logger
from youtube_pipeline.utils.paths import ensure_project_paths

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


def _parse_aspect(raw: str) -> AspectRatio:
    text = (raw or "16:9").strip()
    aliases = {
        "16:9": AspectRatio.LANDSCAPE,
        "landscape": AspectRatio.LANDSCAPE,
        "9:16": AspectRatio.VERTICAL,
        "vertical": AspectRatio.VERTICAL,
        "shorts": AspectRatio.VERTICAL,
        "1:1": AspectRatio.SQUARE,
        "square": AspectRatio.SQUARE,
    }
    return aliases.get(text.lower(), AspectRatio.LANDSCAPE)


def _build_pipeline_request(job_id: str, request_data: dict[str, Any]) -> PipelineRequest:
    raw_format = request_data.get("format") or VideoFormat.NARRATIVE
    video_format = (
        raw_format
        if isinstance(raw_format, VideoFormat)
        else VideoFormat(str(raw_format))
    )
    quiz_mode: QuizMode | None = None
    question_count: int | None = None
    if video_format == VideoFormat.QUIZVERSE:
        raw_mode = request_data.get("quiz_mode") or QuizMode.COMMENT
        quiz_mode = raw_mode if isinstance(raw_mode, QuizMode) else QuizMode(str(raw_mode))
        default_count = 1 if quiz_mode == QuizMode.COMMENT else 5
        raw_count = request_data.get("question_count")
        requested_count = default_count if raw_count is None else int(raw_count)
        maximum = 5 if quiz_mode == QuizMode.COMMENT else 15
        question_count = max(1, min(maximum, requested_count))

    raw_aspect = request_data.get("aspect_ratio")
    if raw_aspect is None or not str(raw_aspect).strip():
        default_aspect = (
            "9:16" if video_format == VideoFormat.DIALOGUE else "16:9"
        )
        aspect_ratio = _parse_aspect(default_aspect)
    else:
        aspect_ratio = _parse_aspect(str(raw_aspect))
    duration, max_scenes = resolve_auto_scene_budget(
        format=video_format,
        aspect_ratio=aspect_ratio,
        quiz_mode=quiz_mode,
        question_count=question_count,
    )
    if video_format == VideoFormat.NARRATIVE:
        if request_data.get("duration") is not None:
            duration = int(request_data["duration"])
        if request_data.get("max_scenes") is not None:
            max_scenes = int(request_data["max_scenes"])

    return PipelineRequest(
        idea=str(request_data["idea"]),
        format=video_format,
        quiz_mode=quiz_mode,
        question_count=question_count,
        style=_parse_style(str(request_data.get("style") or "cinematic")),
        aspect_ratio=aspect_ratio,
        target_duration_seconds=duration,
        max_scenes=max_scenes,
        output_name=job_id,
        voice=(
            str(request_data["voice"]).strip()
            if request_data.get("voice")
            else None
        ),
        language=str(request_data.get("language") or "en"),
    )


def _publish_progress(
    job_id: str,
    stage: int,
    stage_label: str,
    progress: int,
    *,
    status: JobStatus = JobStatus.PROCESSING,
) -> None:
    update_job(
        job_id,
        status=status,
        current_stage=stage_label,
        progress_percent=progress,
    )
    try:
        from youtube_pipeline.api.assemble_progress import (
            build_assemble_progress,
            write_assemble_progress_file,
        )
        from youtube_pipeline.api.job_store import get_job

        job = get_job(job_id)
        if job and job.run_dir:
            payload = build_assemble_progress(job.run_dir, scene_count=job.scene_count)
            if payload:
                payload["current_stage"] = stage_label
                payload["progress_percent"] = progress
                write_assemble_progress_file(STATIC_DIR, job_id, payload)
    except Exception:  # noqa: BLE001
        pass
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
    prompts: Path | None = None,
) -> DownloadUrls:
    dest_dir = STATIC_DIR / job_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(audio, dest_dir / "audio.mp3")
    shutil.copy2(script, dest_dir / "script.json")

    video_url = None
    subtitles_url = None
    if video is not None and video.exists() and video.is_file() and video.suffix.lower() == ".mp4":
        shutil.copy2(video, dest_dir / "video.mp4")
        video_url = f"/static/{job_id}/video.mp4"
        srt = video.with_suffix(".srt")
        if srt.exists():
            shutil.copy2(srt, dest_dir / "video.srt")
            subtitles_url = f"/static/{job_id}/video.srt"

    prompts_url = None
    if prompts is not None and prompts.exists():
        shutil.copy2(prompts, dest_dir / "prompts.json")
        prompts_url = f"/static/{job_id}/prompts.json"
        csv = prompts.with_suffix(".csv")
        if csv.exists():
            shutil.copy2(csv, dest_dir / "prompts.csv")

    assets_url = None
    if assets_dir is not None and assets_dir.exists():
        assets_dest = dest_dir / "assets"
        assets_dest.mkdir(parents=True, exist_ok=True)
        copied = 0
        for path in sorted(assets_dir.glob("scene_*.*")):
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                shutil.copy2(path, assets_dest / path.name)
                copied += 1
        if copied:
            assets_url = f"/static/{job_id}/assets/"

    urls = DownloadUrls(
        video_url=video_url,
        audio_url=f"/static/{job_id}/audio.mp3",
        script_url=f"/static/{job_id}/script.json",
        assets_url=assets_url,
        prompts_url=prompts_url,
        subtitles_url=subtitles_url,
    )
    logger.info("Artifacts published | job_id=%s | urls=%s", job_id, urls.model_dump())
    return urls


def _fail_job(job_id: str, exc: BaseException) -> None:
    logger.exception("Pipeline task failed | job_id=%s", job_id)
    try:
        update_job(
            job_id,
            status=JobStatus.FAILED,
            current_stage="Something went wrong — try again or adjust your idea",
            progress_percent=100,
            error=str(exc),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not persist failed job state | job_id=%s", job_id)


def execute_video_pipeline(job_id: str, request_data: dict[str, Any]) -> dict[str, Any]:
    """Phase 1: script + audio + prompts, then pause at waiting_for_assets."""
    ensure_project_paths()

    try:
        update_job(
            job_id,
            status=JobStatus.PROCESSING,
            current_stage="Getting started on your film…",
            progress_percent=5,
        )

        from youtube_pipeline.i18n import default_voice_for_language, normalize_language
        from youtube_pipeline.orchestrator import VideoPipelineOrchestrator

        language = normalize_language(str(request_data.get("language") or "en"))
        voice = (
            str(request_data["voice"]).strip()
            if request_data.get("voice")
            else default_voice_for_language(language)
        )
        request_data = {**request_data, "language": language, "voice": voice}

        pipeline_request = _build_pipeline_request(job_id, request_data)

        orchestrator = VideoPipelineOrchestrator(
            on_progress=lambda stage, label, pct: _publish_progress(job_id, stage, label, pct),
        )
        result = orchestrator.run(pipeline_request)
        meta = result.metadata or {}
        run_dir = Path(meta.get("run_dir") or result.video_path)
        audio_path = Path(meta.get("audio_path") or (run_dir / "audio" / "voiceover.mp3"))
        script_path = Path(meta.get("script_path") or (run_dir / "script.json"))
        prompts_path = Path(meta.get("prompts_json") or (run_dir / "prompts.json"))

        if not audio_path.exists() or not script_path.exists():
            raise FileNotFoundError("Phase 1 artifacts missing (audio/script)")

        download_urls = _publish_artifacts(
            job_id,
            audio=audio_path,
            script=script_path,
            prompts=prompts_path if prompts_path.exists() else None,
        )
        from config.settings import AssetProvider, get_settings
        from youtube_pipeline.assets.hitl_workspace import (
            auto_fill_scene_images,
            publish_workspace_static,
        )

        publish_workspace_static(job_id, run_dir, STATIC_DIR)
        selected_voice = (
            str(request_data["voice"]).strip()
            if request_data.get("voice")
            else None
        )
        if selected_voice:
            from youtube_pipeline.assets.hitl_workspace import remember_voice

            remember_voice(run_dir, selected_voice, source="tts")
        settings = get_settings()
        if settings.asset_provider == AssetProvider.MANUAL:
            stage = "Your turn — add scene images, then assemble"
            progress = 75
        else:
            update_job(
                job_id,
                status=JobStatus.WAITING_FOR_ASSETS,
                current_stage="Generating scene images…",
                progress_percent=75,
                download_urls=download_urls,
                run_dir=str(run_dir.resolve()),
            )

            def _image_progress(done: int, total: int, label: str) -> None:
                percent = 75 + int(15 * (done / max(total, 1)))
                update_job(
                    job_id,
                    status=JobStatus.WAITING_FOR_ASSETS,
                    current_stage=label,
                    progress_percent=min(percent, 90),
                    run_dir=str(run_dir.resolve()),
                )

            try:
                fill = auto_fill_scene_images(run_dir, on_progress=_image_progress)
                publish_workspace_static(job_id, run_dir, STATIC_DIR)
                failures = fill.get("failed") or []
                if failures:
                    stage = (
                        f"Some images failed ({len(failures)}) — regenerate or upload"
                    )
                else:
                    stage = "Review scene images, then assemble"
            except Exception:  # noqa: BLE001
                logger.exception("Scene image auto-fill crashed | job_id=%s", job_id)
                stage = "Image generation failed — regenerate or upload scene images"
            progress = 92

        update_job(
            job_id,
            status=JobStatus.WAITING_FOR_ASSETS,
            current_stage=stage,
            progress_percent=progress,
            download_urls=download_urls,
            run_dir=str(run_dir.resolve()),
            scene_count=int(meta.get("scene_count") or 0),
            title=str(meta.get("title") or ""),
            idea=str(meta.get("idea") or request_data.get("idea") or ""),
            error=None,
        )
        return {
            "job_id": job_id,
            "status": JobStatus.WAITING_FOR_ASSETS.value,
            "run_dir": str(run_dir.resolve()),
            "download_urls": download_urls.model_dump(),
            "message": meta.get("message"),
            "scene_count": meta.get("scene_count"),
            "prompts_url": download_urls.prompts_url,
        }
    except Exception as exc:  # noqa: BLE001
        _fail_job(job_id, exc)
        raise


def execute_resume_pipeline(job_id: str, zip_path: str | None = None) -> dict[str, Any]:
    """Phase 2: unzip uploaded assets and assemble the final MP4."""
    ensure_project_paths()

    try:
        from youtube_pipeline.api.job_store import get_job
        from youtube_pipeline.orchestrator import VideoPipelineOrchestrator

        job = get_job(job_id)
        if job is None:
            raise FileNotFoundError(f"Unknown job_id: {job_id}")
        if not job.run_dir:
            raise FileNotFoundError(f"Job {job_id} has no run_dir — Phase 1 incomplete")

        update_job(
            job_id,
            status=JobStatus.PROCESSING,
            current_stage="Checking your scene images…",
            progress_percent=80,
            error=None,
        )

        orchestrator = VideoPipelineOrchestrator(
            on_progress=lambda stage, label, pct: _publish_progress(job_id, stage, label, pct),
        )
        result = orchestrator.resume(
            job.run_dir,
            zip_path=Path(zip_path) if zip_path else None,
        )
        meta = result.metadata or {}
        run_dir = Path(meta.get("run_dir") or job.run_dir)
        video_path = Path(result.video_path)
        audio_path = Path(meta.get("audio_path") or (run_dir / "audio" / "voiceover.mp3"))
        script_path = Path(meta.get("script_path") or (run_dir / "script.json"))
        assets_dir = Path(meta.get("assets_dir") or (run_dir / "assets"))
        prompts_path = run_dir / "prompts.json"

        if not video_path.exists() or video_path.suffix.lower() != ".mp4":
            raise FileNotFoundError(f"Compiled MP4 missing: {video_path}")

        update_job(
            job_id,
            status=JobStatus.PROCESSING,
            current_stage="Finishing your film…",
            progress_percent=95,
        )

        download_urls = _publish_artifacts(
            job_id,
            audio=audio_path,
            script=script_path,
            assets_dir=assets_dir if assets_dir.exists() else None,
            video=video_path,
            prompts=prompts_path if prompts_path.exists() else None,
        )
        update_job(
            job_id,
            status=JobStatus.COMPLETED,
            current_stage="Your film is ready",
            progress_percent=100,
            download_urls=download_urls,
            run_dir=str(run_dir.resolve()),
            scene_count=int(meta.get("scene_count") or job.scene_count or 0),
            title=str(meta.get("title") or job.title or ""),
            idea=str(meta.get("idea") or job.idea or ""),
            error=None,
        )
        return {
            "job_id": job_id,
            "status": JobStatus.COMPLETED.value,
            "download_urls": download_urls.model_dump(),
            "video_url": download_urls.video_url,
            "message": "Cinematic video assembled from human-uploaded assets",
        }
    except Exception as exc:  # noqa: BLE001
        _fail_job(job_id, exc)
        raise


@app.task(name="youtube_pipeline.run_video_pipeline", bind=True)
def run_video_pipeline(self, job_id: str, request_data: dict[str, Any]) -> dict[str, Any]:
    """Celery entrypoint — Phase 1 pause pipeline."""
    return execute_video_pipeline(job_id, request_data)


@app.task(name="youtube_pipeline.resume_video_pipeline", bind=True)
def resume_video_pipeline(self, job_id: str, zip_path: str | None = None) -> dict[str, Any]:
    """Celery entrypoint — Phase 2 assemble after ZIP upload."""
    return execute_resume_pipeline(job_id, zip_path=zip_path)

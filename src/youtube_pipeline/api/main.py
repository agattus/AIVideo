"""FastAPI application — web studio UI + human-in-the-loop async job API."""

from __future__ import annotations

import os
import sys
import threading
import uuid
from pathlib import Path

# Bootstrap repo root + src before any config / pipeline imports.
_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP_SRC = _BOOTSTRAP_ROOT / "src"
for _path in (_BOOTSTRAP_ROOT, _BOOTSTRAP_SRC, Path.cwd(), Path.cwd() / "src"):
    _text = str(_path)
    if _path.is_dir() and _text not in sys.path:
        sys.path.insert(0, _text)

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from youtube_pipeline.api.job_store import get_job, init_job, redis_available
from youtube_pipeline.api.schemas import (
    GenerateVideoAccepted,
    GenerateVideoRequest,
    JobStatus,
    JobStatusResponse,
    UploadAssetsAccepted,
)
from youtube_pipeline.api.tasks import (
    execute_resume_pipeline,
    execute_video_pipeline,
    resume_video_pipeline,
    run_video_pipeline,
)
from youtube_pipeline.utils.logging import get_logger, setup_logging
from youtube_pipeline.utils.paths import ensure_project_paths

ensure_project_paths()

logger = get_logger(__name__)
setup_logging(os.getenv("LOG_LEVEL", "INFO"))

ROOT_CANDIDATES = [
    Path(os.getenv("WEB_DIR", "")),
    Path.cwd() / "web",
    Path(__file__).resolve().parents[3] / "web",
    Path("/app/web"),
]


def _find_web_dir() -> Path:
    for candidate in ROOT_CANDIDATES:
        if candidate and (candidate / "index.html").exists():
            return candidate
    return Path.cwd() / "web"


WEB_DIR = _find_web_dir()
UI_ASSETS_DIR = WEB_DIR / "assets"


def _resolve_static_dir() -> Path:
    preferred = Path(os.getenv("STATIC_DIR", "./static"))
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path.cwd() / "static"
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning("STATIC_DIR=%s not writable; using %s", preferred, fallback)
        return fallback


STATIC_DIR = _resolve_static_dir()

app = FastAPI(
    title="AIVideo Pipeline API",
    description=(
        "Human-in-the-loop YouTube video generation. "
        "POST /api/v1/generate → waiting_for_assets → "
        "POST /api/v1/jobs/{job_id}/upload-assets → completed MP4."
    ),
    version="2.0.0",
)

_cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
allow_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if UI_ASSETS_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(UI_ASSETS_DIR)), name="ui")


def _run_job_in_thread(job_id: str, request_data: dict) -> None:
    try:
        ensure_project_paths()
        execute_video_pipeline(job_id, request_data)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background pipeline thread crashed | job_id=%s | %s", job_id, exc)


def _run_resume_in_thread(job_id: str, zip_path: str) -> None:
    try:
        ensure_project_paths()
        execute_resume_pipeline(job_id, zip_path=zip_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background resume thread crashed | job_id=%s | %s", job_id, exc)


def _dispatch_job(job_id: str, request_data: dict) -> str:
    use_celery = os.getenv("FORCE_INLINE_WORKER", "").lower() not in {"1", "true", "yes"}
    if use_celery and redis_available():
        try:
            run_video_pipeline.delay(job_id, request_data)
            logger.info("Dispatched Phase 1 job to Celery | job_id=%s", job_id)
            return "celery"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Celery dispatch failed (%s); falling back to thread", exc)

    thread = threading.Thread(
        target=_run_job_in_thread,
        args=(job_id, request_data),
        name=f"pipeline-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    logger.info("Dispatched Phase 1 job to in-process thread | job_id=%s", job_id)
    return "thread"


def _dispatch_resume(job_id: str, zip_path: Path) -> str:
    use_celery = os.getenv("FORCE_INLINE_WORKER", "").lower() not in {"1", "true", "yes"}
    if use_celery and redis_available():
        try:
            resume_video_pipeline.delay(job_id, str(zip_path))
            logger.info("Dispatched resume job to Celery | job_id=%s", job_id)
            return "celery"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Celery resume dispatch failed (%s); falling back to thread", exc)

    thread = threading.Thread(
        target=_run_resume_in_thread,
        args=(job_id, str(zip_path)),
        name=f"resume-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    logger.info("Dispatched resume job to in-process thread | job_id=%s", job_id)
    return "thread"


@app.get("/", include_in_schema=False)
def studio_home() -> FileResponse:
    index = WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Web UI not found at {index}. Ensure the web/ folder is present.",
        )
    return FileResponse(index)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "redis": redis_available(),
        "ui": (WEB_DIR / "index.html").exists(),
        "mode": "human-in-the-loop",
    }


@app.post(
    "/api/v1/generate",
    response_model=GenerateVideoAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
def generate_video(payload: GenerateVideoRequest) -> GenerateVideoAccepted:
    """Start Phase 1 (script + audio + prompts) and return immediately."""
    job_id = str(uuid.uuid4())
    init_job(job_id)

    request_data = payload.model_dump()
    mode = _dispatch_job(job_id, request_data)
    logger.info(
        "Enqueue generate | job_id=%s | mode=%s | style=%s | aspect=%s | duration=%s | idea=%r",
        job_id,
        mode,
        payload.style,
        payload.aspect_ratio,
        payload.duration,
        payload.idea[:80],
    )
    return GenerateVideoAccepted(job_id=job_id, status=JobStatus.QUEUED)


@app.post(
    "/api/v1/jobs/{job_id}/upload-assets",
    response_model=UploadAssetsAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
async def upload_assets(
    job_id: str,
    file: UploadFile = File(..., description="ZIP of scene_XX.jpg images"),
) -> UploadAssetsAccepted:
    """Accept a ZIP of human-generated scene images and resume FFmpeg assembly."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown job_id: {job_id}",
        )
    if job.status not in {JobStatus.WAITING_FOR_ASSETS, JobStatus.FAILED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Job is {job.status.value}; uploads are accepted when status is "
                "waiting_for_assets"
            ),
        )
    if not job.run_dir:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job has no run_dir — Phase 1 has not finished yet",
        )

    filename = (file.filename or "assets.zip").lower()
    if not filename.endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload must be a .zip file of scene images",
        )

    run_dir = Path(job.run_dir)
    upload_dir = run_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    zip_path = upload_dir / "assets.zip"

    content = await file.read()
    if len(content) < 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded ZIP is empty",
        )
    zip_path.write_bytes(content)
    logger.info(
        "Assets ZIP saved | job_id=%s | path=%s | bytes=%d | scenes_expected=%s",
        job_id,
        zip_path,
        len(content),
        job.scene_count,
    )

    mode = _dispatch_resume(job_id, zip_path)
    logger.info("Resume dispatched | job_id=%s | mode=%s", job_id, mode)
    return UploadAssetsAccepted(
        job_id=job_id,
        status=JobStatus.PROCESSING,
        message="Assets uploaded — resume assembly started",
    )


@app.get(
    "/api/v1/status/{job_id}",
    response_model=JobStatusResponse,
    tags=["jobs"],
)
def get_job_status(job_id: str) -> JobStatusResponse:
    state = get_job(job_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown job_id: {job_id}",
        )
    return state

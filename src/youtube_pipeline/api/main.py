"""FastAPI application — web studio UI + async job API for mobile/local clients."""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from youtube_pipeline.api.job_store import get_job, init_job, redis_available
from youtube_pipeline.api.schemas import (
    GenerateVideoAccepted,
    GenerateVideoRequest,
    JobStatus,
    JobStatusResponse,
)
from youtube_pipeline.api.tasks import execute_video_pipeline, run_video_pipeline
from youtube_pipeline.utils.logging import get_logger, setup_logging

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
    """Prefer ``STATIC_DIR``; default to ./static locally, /app/static in Docker."""
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
        "Web studio + asynchronous YouTube video generation. "
        "Open / for the UI, or POST /api/v1/generate and poll GET /api/v1/status/{job_id}."
    ),
    version="1.0.0",
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

# Completed media artifacts (.mp4 / .mp3 / .json).
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Studio CSS/JS.
if UI_ASSETS_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(UI_ASSETS_DIR)), name="ui")


def _dispatch_job(job_id: str, request_data: dict) -> str:
    """Enqueue via Celery when Redis is up; otherwise run in a background thread."""
    use_celery = os.getenv("FORCE_INLINE_WORKER", "").lower() not in {"1", "true", "yes"}
    if use_celery and redis_available():
        try:
            run_video_pipeline.delay(job_id, request_data)
            logger.info("Dispatched job to Celery | job_id=%s", job_id)
            return "celery"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Celery dispatch failed (%s); falling back to thread", exc)

    thread = threading.Thread(
        target=execute_video_pipeline,
        args=(job_id, request_data),
        name=f"pipeline-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    logger.info("Dispatched job to in-process thread | job_id=%s", job_id)
    return "thread"


@app.get("/", include_in_schema=False)
def studio_home() -> FileResponse:
    """Serve the AIVideo web studio."""
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
    }


@app.post(
    "/api/v1/generate",
    response_model=GenerateVideoAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
def generate_video(payload: GenerateVideoRequest) -> GenerateVideoAccepted:
    """Enqueue a video generation job and return immediately (no HTTP timeout risk)."""
    job_id = str(uuid.uuid4())
    init_job(job_id)

    request_data = payload.model_dump()
    mode = _dispatch_job(job_id, request_data)
    logger.info(
        "Enqueue generate | job_id=%s | mode=%s | style=%s | duration=%s | max_scenes=%s | idea=%r",
        job_id,
        mode,
        payload.style,
        payload.duration,
        payload.max_scenes,
        payload.idea[:80],
    )

    return GenerateVideoAccepted(job_id=job_id, status=JobStatus.QUEUED)


@app.get(
    "/api/v1/status/{job_id}",
    response_model=JobStatusResponse,
    tags=["jobs"],
)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Return the latest job state for UI / mobile polling."""
    state = get_job(job_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown job_id: {job_id}",
        )
    return state

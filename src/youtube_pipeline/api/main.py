"""FastAPI application — async job submission + status polling for mobile clients."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from youtube_pipeline.api.job_store import get_job, init_job
from youtube_pipeline.api.schemas import (
    GenerateVideoAccepted,
    GenerateVideoRequest,
    JobStatus,
    JobStatusResponse,
)
from youtube_pipeline.api.tasks import run_video_pipeline
from youtube_pipeline.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)
setup_logging(os.getenv("LOG_LEVEL", "INFO"))


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
        "Asynchronous YouTube video generation service. "
        "Submit a job via POST /api/v1/generate and poll GET /api/v1/status/{job_id}."
    ),
    version="1.0.0",
)

# CORS wide-open for mobile / Expo / React Native clients during development.
_cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
allow_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve completed artifacts (.mp4 / .mp3 / .json) from the shared volume.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


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
    logger.info(
        "Enqueue generate | job_id=%s | style=%s | duration=%s | max_scenes=%s | idea=%r",
        job_id,
        payload.style,
        payload.duration,
        payload.max_scenes,
        payload.idea[:80],
    )

    # Celery async dispatch — worker picks this up independently of the API process.
    run_video_pipeline.delay(job_id, request_data)

    return GenerateVideoAccepted(job_id=job_id, status=JobStatus.QUEUED)


@app.get(
    "/api/v1/status/{job_id}",
    response_model=JobStatusResponse,
    tags=["jobs"],
)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Return the latest Redis-backed job state for mobile polling."""
    state = get_job(job_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown job_id: {job_id}",
        )
    return state

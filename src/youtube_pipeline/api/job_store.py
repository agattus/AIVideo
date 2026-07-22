"""Redis-backed job state helpers (key pattern: ``status:{job_id}``)."""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import redis

from youtube_pipeline.api.schemas import DownloadUrls, JobStatus, JobStatusResponse

DEFAULT_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JOB_KEY_PREFIX = "status:"
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", str(7 * 24 * 3600)))


def redis_client(url: str | None = None) -> redis.Redis:
    """Return a Redis client (decode_responses for JSON string payloads)."""
    return redis.Redis.from_url(url or DEFAULT_REDIS_URL, decode_responses=True)


def job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def init_job(job_id: str, *, client: redis.Redis | None = None) -> JobStatusResponse:
    """Create the initial queued job record in Redis."""
    state = JobStatusResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        current_stage="Queued",
        progress_percent=0,
    )
    save_job(state, client=client)
    return state


def save_job(state: JobStatusResponse, *, client: redis.Redis | None = None) -> None:
    r = client or redis_client()
    r.set(job_key(state.job_id), state.model_dump_json(), ex=JOB_TTL_SECONDS)


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    current_stage: str | None = None,
    progress_percent: int | None = None,
    download_urls: DownloadUrls | dict[str, Any] | None = None,
    error: str | None = None,
    client: redis.Redis | None = None,
) -> JobStatusResponse:
    """Merge fields into the existing Redis job record (or create if missing)."""
    r = client or redis_client()
    existing = get_job(job_id, client=r)
    if existing is None:
        existing = JobStatusResponse(job_id=job_id, status=JobStatus.QUEUED)

    data = existing.model_dump()
    if status is not None:
        data["status"] = status
    if current_stage is not None:
        data["current_stage"] = current_stage
    if progress_percent is not None:
        data["progress_percent"] = max(0, min(100, int(progress_percent)))
    if download_urls is not None:
        if isinstance(download_urls, DownloadUrls):
            data["download_urls"] = download_urls.model_dump()
        else:
            data["download_urls"] = download_urls
    if error is not None:
        data["error"] = error

    state = JobStatusResponse.model_validate(data)
    save_job(state, client=r)
    return state


def get_job(job_id: str, *, client: redis.Redis | None = None) -> Optional[JobStatusResponse]:
    r = client or redis_client()
    raw = r.get(job_key(job_id))
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return JobStatusResponse.model_validate(payload)

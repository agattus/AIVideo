"""Redis-backed job state with an in-memory fallback for local UI runs."""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

from youtube_pipeline.api.schemas import DownloadUrls, JobStatus, JobStatusResponse

DEFAULT_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JOB_KEY_PREFIX = "status:"
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", str(7 * 24 * 3600)))

_memory_lock = threading.Lock()
_memory_jobs: dict[str, str] = {}
_redis_available: bool | None = None


class _MemoryRedis:
    """Tiny Redis-compatible subset used when the broker is offline."""

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        with _memory_lock:
            _memory_jobs[key] = value
        return True

    def get(self, key: str) -> str | None:
        with _memory_lock:
            return _memory_jobs.get(key)

    def ping(self) -> bool:
        return True


def redis_available(url: str | None = None) -> bool:
    """Return True when Redis accepts a ping (cached briefly via module flag)."""
    global _redis_available
    if _redis_available is not None:
        return _redis_available
    try:
        import redis

        client = redis.Redis.from_url(url or DEFAULT_REDIS_URL, decode_responses=True)
        client.ping()
        _redis_available = True
    except Exception:  # noqa: BLE001
        _redis_available = False
    return _redis_available


def reset_redis_availability_cache() -> None:
    global _redis_available
    _redis_available = None


def redis_client(url: str | None = None):
    """Return a Redis client, or an in-memory stand-in if Redis is unreachable."""
    if not redis_available(url):
        return _MemoryRedis()
    import redis

    return redis.Redis.from_url(url or DEFAULT_REDIS_URL, decode_responses=True)


def job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def init_job(job_id: str, *, client=None) -> JobStatusResponse:
    """Create the initial queued job record."""
    state = JobStatusResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        current_stage="Queued",
        progress_percent=0,
    )
    save_job(state, client=client)
    return state


def save_job(state: JobStatusResponse, *, client=None) -> None:
    r = client or redis_client()
    payload = state.model_dump_json()
    if hasattr(r, "set") and not isinstance(r, _MemoryRedis):
        r.set(job_key(state.job_id), payload, ex=JOB_TTL_SECONDS)
    else:
        r.set(job_key(state.job_id), payload)


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    current_stage: str | None = None,
    progress_percent: int | None = None,
    download_urls: DownloadUrls | dict[str, Any] | None = None,
    error: str | None = None,
    run_dir: str | None = None,
    scene_count: int | None = None,
    client=None,
) -> JobStatusResponse:
    """Merge fields into the existing job record (or create if missing)."""
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
    if run_dir is not None:
        data["run_dir"] = run_dir
    if scene_count is not None:
        data["scene_count"] = int(scene_count)

    state = JobStatusResponse.model_validate(data)
    save_job(state, client=r)
    return state


def get_job(job_id: str, *, client=None) -> Optional[JobStatusResponse]:
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

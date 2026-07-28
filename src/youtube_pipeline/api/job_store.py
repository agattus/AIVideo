"""Redis-backed job state with an in-memory fallback for local UI runs."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from youtube_pipeline.api.schemas import DownloadUrls, JobStatus, JobStatusResponse, JobSummary
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

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

    def keys(self, pattern: str = "*") -> list[str]:
        prefix = pattern.rstrip("*")
        with _memory_lock:
            if pattern.endswith("*"):
                return [k for k in _memory_jobs if k.startswith(prefix)]
            return [k for k in _memory_jobs if k == pattern]

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jobs_index_path() -> Path:
    return Path(os.getenv("OUTPUT_DIR", "./output")) / "jobs_index.json"


def _persist_job_index(state: JobStatusResponse) -> None:
    """Append/update a durable on-disk index so jobs survive process restarts."""
    try:
        path = _jobs_index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        index: dict[str, Any] = {}
        if path.exists():
            try:
                index = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                index = {}
        if not isinstance(index, dict):
            index = {}
        index[state.job_id] = {
            "job_id": state.job_id,
            "status": state.status.value if isinstance(state.status, JobStatus) else state.status,
            "title": state.title,
            "idea": state.idea,
            "run_dir": state.run_dir,
            "scene_count": state.scene_count,
            "updated_at": state.updated_at or _utc_now(),
            "current_stage": state.current_stage,
            "progress_percent": state.progress_percent,
            "download_urls": state.download_urls.model_dump() if state.download_urls else None,
        }
        path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not persist jobs_index.json: %s", exc)


def init_job(job_id: str, *, client=None) -> JobStatusResponse:
    """Create the initial queued job record."""
    state = JobStatusResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        current_stage="Queued",
        progress_percent=0,
        updated_at=_utc_now(),
    )
    save_job(state, client=client)
    return state


def save_job(state: JobStatusResponse, *, client=None) -> None:
    if not state.updated_at:
        state = state.model_copy(update={"updated_at": _utc_now()})
    r = client or redis_client()
    payload = state.model_dump_json()
    if hasattr(r, "set") and not isinstance(r, _MemoryRedis):
        r.set(job_key(state.job_id), payload, ex=JOB_TTL_SECONDS)
    else:
        r.set(job_key(state.job_id), payload)
    _persist_job_index(state)


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
    title: str | None = None,
    idea: str | None = None,
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
    if title is not None:
        data["title"] = title
    if idea is not None:
        data["idea"] = idea
    data["updated_at"] = _utc_now()

    state = JobStatusResponse.model_validate(data)
    save_job(state, client=r)
    return state


def get_job(job_id: str, *, client=None) -> Optional[JobStatusResponse]:
    r = client or redis_client()
    raw = r.get(job_key(job_id))
    if not raw:
        # Fall back to durable index / filesystem discovery.
        recovered = _recover_job_from_disk(job_id)
        if recovered is not None:
            save_job(recovered, client=r)
            return recovered
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return JobStatusResponse.model_validate(payload)


def _recover_job_from_disk(job_id: str) -> JobStatusResponse | None:
    index_path = _jobs_index_path()
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            entry = index.get(job_id) if isinstance(index, dict) else None
            if isinstance(entry, dict):
                return _summary_dict_to_status(entry)
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    for root in _candidate_output_roots():
        run_dir = root / job_id
        if run_dir.is_dir() and (run_dir / "request.json").exists():
            return _job_from_run_dir(job_id, run_dir)
    return None


def _candidate_output_roots() -> list[Path]:
    roots: list[Path] = []
    for raw in (
        os.getenv("OUTPUT_DIR", "./output"),
        "./output",
        str(Path.cwd() / "output"),
    ):
        path = Path(raw)
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def _job_from_run_dir(job_id: str, run_dir: Path) -> JobStatusResponse:
    title = ""
    idea = ""
    scene_count = None
    status = JobStatus.WAITING_FOR_ASSETS
    try:
        req = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
        idea = str(req.get("idea") or "")
    except Exception:  # noqa: BLE001
        pass
    for name in ("script_timed.json", "script.json", "prompts.json", "result.json"):
        path = run_dir / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            title = str(data.get("title") or title)
            if "scene_count" in data:
                scene_count = int(data["scene_count"])
            elif isinstance(data.get("scenes"), list):
                scene_count = len(data["scenes"])
            if name == "result.json" and data.get("status") == "success":
                status = JobStatus.COMPLETED
            break
        except Exception:  # noqa: BLE001
            continue

    if list(run_dir.glob("*.mp4")):
        status = JobStatus.COMPLETED

    video = next(iter(sorted(run_dir.glob("*.mp4"))), None)
    download_urls = None
    if video or (run_dir / "audio" / "voiceover.mp3").exists():
        download_urls = DownloadUrls(
            video_url=f"/static/{job_id}/video.mp4" if video else None,
            audio_url=f"/static/{job_id}/audio.mp3",
            script_url=f"/static/{job_id}/script.json",
            prompts_url=f"/static/{job_id}/prompts.json",
        )

    mtime = datetime.fromtimestamp(run_dir.stat().st_mtime, tz=timezone.utc).isoformat()
    return JobStatusResponse(
        job_id=job_id,
        status=status,
        current_stage="Recovered from disk",
        progress_percent=100 if status == JobStatus.COMPLETED else 75,
        run_dir=str(run_dir.resolve()),
        scene_count=scene_count,
        title=title or idea[:80] or job_id,
        idea=idea,
        updated_at=mtime,
        download_urls=download_urls,
    )


def _summary_dict_to_status(entry: dict[str, Any]) -> JobStatusResponse:
    urls = entry.get("download_urls")
    return JobStatusResponse(
        job_id=str(entry["job_id"]),
        status=JobStatus(entry.get("status") or JobStatus.WAITING_FOR_ASSETS.value),
        current_stage=str(entry.get("current_stage") or ""),
        progress_percent=int(entry.get("progress_percent") or 0),
        run_dir=entry.get("run_dir"),
        scene_count=entry.get("scene_count"),
        title=entry.get("title"),
        idea=entry.get("idea"),
        updated_at=entry.get("updated_at"),
        download_urls=DownloadUrls.model_validate(urls) if urls else None,
    )


def list_jobs(*, limit: int = 50, client=None) -> list[JobStatusResponse]:
    """Return recent jobs from Redis, durable index, and output folders."""
    r = client or redis_client()
    by_id: dict[str, JobStatusResponse] = {}

    # 1) Live Redis / memory store
    try:
        keys = r.keys(f"{JOB_KEY_PREFIX}*")
    except Exception:  # noqa: BLE001
        keys = []
    for key in keys or []:
        key_text = key.decode("utf-8") if isinstance(key, bytes) else str(key)
        job_id = key_text[len(JOB_KEY_PREFIX) :]
        job = get_job(job_id, client=r)
        if job is not None:
            by_id[job_id] = job

    # 2) Durable index
    index_path = _jobs_index_path()
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(index, dict):
                for job_id, entry in index.items():
                    if job_id in by_id or not isinstance(entry, dict):
                        continue
                    by_id[job_id] = _summary_dict_to_status(entry)
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    # 3) Scan output directories for any missing runs
    for root in _candidate_output_roots():
        try:
            for child in root.iterdir():
                if not child.is_dir() or child.name.startswith("."):
                    continue
                if child.name == "jobs_index.json":
                    continue
                if not (child / "request.json").exists():
                    continue
                job_id = child.name
                if job_id in by_id:
                    # Fill missing run_dir if needed.
                    existing = by_id[job_id]
                    if not existing.run_dir:
                        by_id[job_id] = existing.model_copy(
                            update={"run_dir": str(child.resolve())}
                        )
                    continue
                by_id[job_id] = _job_from_run_dir(job_id, child)
        except OSError:
            continue

    jobs = list(by_id.values())
    jobs.sort(key=lambda j: j.updated_at or "", reverse=True)
    return jobs[: max(1, int(limit))]


def to_job_summary(job: JobStatusResponse, *, static_dir: Path | None = None) -> JobSummary:
    urls = job.download_urls
    video_url = urls.video_url if urls else None
    audio_url = urls.audio_url if urls else None
    thumb_url = None
    if static_dir is not None:
        assets = static_dir / job.job_id / "assets"
        if assets.is_dir():
            for candidate in sorted(assets.glob("scene_00.*")):
                thumb_url = f"/static/{job.job_id}/assets/{candidate.name}"
                break
        if video_url is None and (static_dir / job.job_id / "video.mp4").exists():
            video_url = f"/static/{job.job_id}/video.mp4"
        if audio_url is None and (static_dir / job.job_id / "audio.mp3").exists():
            audio_url = f"/static/{job.job_id}/audio.mp3"

    can_edit = job.status in {
        JobStatus.WAITING_FOR_ASSETS,
        JobStatus.FAILED,
        JobStatus.COMPLETED,
    } and bool(job.run_dir)

    return JobSummary(
        job_id=job.job_id,
        status=job.status,
        title=job.title or (job.idea[:80] if job.idea else job.job_id),
        idea=job.idea or "",
        current_stage=job.current_stage,
        progress_percent=job.progress_percent,
        scene_count=job.scene_count,
        run_dir=job.run_dir,
        updated_at=job.updated_at,
        video_url=video_url,
        audio_url=audio_url,
        thumb_url=thumb_url,
        can_edit=can_edit,
    )

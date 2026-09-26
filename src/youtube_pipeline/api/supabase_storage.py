"""Upload durable job artifacts to Supabase Storage and issue signed URLs."""

from __future__ import annotations

from pathlib import Path

from youtube_pipeline.api.supabase_client import (
    create_signed_url,
    get_job_row,
    supabase_configured,
    upload_bytes,
    upsert_job_row,
)
from youtube_pipeline.api.supabase_jobs import storage_prefix_for
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".json": "application/json",
}


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def upload_job_file(
    *,
    user_id: str,
    job_id: str,
    relative_key: str,
    path: Path,
) -> str | None:
    """Upload ``path`` to ``{user_id}/{job_id}/{relative_key}``. Returns object key."""
    if not supabase_configured() or not path.is_file():
        return None
    object_path = f"{storage_prefix_for(user_id, job_id).rstrip('/')}/{relative_key.lstrip('/')}"
    ok = upload_bytes(
        object_path=object_path,
        data=path.read_bytes(),
        content_type=_content_type(path),
    )
    if not ok:
        return None
    return object_path


def sync_completed_artifacts(
    job_id: str,
    *,
    video_path: Path | None = None,
    thumb_path: Path | None = None,
) -> dict[str, str | None]:
    """Upload final video (+ optional thumb) and patch the jobs row paths."""
    out: dict[str, str | None] = {"result_video_path": None, "thumb_path": None, "video_url": None}
    if not supabase_configured():
        return out
    row = get_job_row(job_id)
    if not row:
        return out
    user_id = str(row.get("user_id") or "").strip()
    if not user_id or user_id == "local-dev":
        return out

    patch: dict[str, object] = {"id": job_id, "user_id": user_id}
    if video_path and video_path.is_file():
        key = upload_job_file(
            user_id=user_id,
            job_id=job_id,
            relative_key="video/final.mp4",
            path=video_path,
        )
        if key:
            patch["result_video_path"] = key
            out["result_video_path"] = key
            out["video_url"] = create_signed_url(key, expires_in=3600)
    if thumb_path and thumb_path.is_file():
        key = upload_job_file(
            user_id=user_id,
            job_id=job_id,
            relative_key="video/thumb.jpg",
            path=thumb_path,
        )
        if key:
            patch["thumb_path"] = key
            out["thumb_path"] = key

    if "result_video_path" in patch or "thumb_path" in patch:
        upsert_job_row(patch)
        logger.info(
            "Synced artifacts to Supabase Storage | job_id=%s | video=%s",
            job_id,
            out.get("result_video_path"),
        )
    return out


def signed_urls_for_job_row(row: dict) -> tuple[str | None, str | None]:
    video_key = row.get("result_video_path")
    thumb_key = row.get("thumb_path")
    video_url = create_signed_url(str(video_key), expires_in=3600) if video_key else None
    thumb_url = create_signed_url(str(thumb_key), expires_in=3600) if thumb_key else None
    return video_url, thumb_url

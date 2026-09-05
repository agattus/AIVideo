"""Map pipeline job state ↔ Supabase ``jobs`` rows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from youtube_pipeline.api.schemas import JobStatus, JobStatusResponse, JobSummary
from youtube_pipeline.api.supabase_client import (
    get_job_row,
    list_job_rows,
    supabase_configured,
    upsert_job_row,
)
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


def storage_prefix_for(user_id: str, job_id: str) -> str:
    return f"{user_id}/{job_id}"


def persist_job_to_supabase(
    state: JobStatusResponse,
    *,
    user_id: str | None,
    idea: str | None = None,
    format_name: str | None = None,
    style: str | None = None,
    aspect_ratio: str | None = None,
    language: str | None = None,
) -> None:
    if not user_id or not supabase_configured():
        return
    now = datetime.now(timezone.utc).isoformat()
    row: dict[str, Any] = {
        "id": state.job_id,
        "user_id": user_id,
        "status": state.status.value if hasattr(state.status, "value") else str(state.status),
        "title": state.title,
        "idea": idea or state.idea,
        "error": state.error,
        "progress_percent": int(state.progress_percent or 0),
        "current_stage": state.current_stage,
        "run_dir": state.run_dir,
        "storage_prefix": storage_prefix_for(user_id, state.job_id),
        "updated_at": now,
    }
    if format_name:
        row["format"] = format_name
    if style:
        row["style"] = style
    if aspect_ratio:
        row["aspect_ratio"] = aspect_ratio
    if language:
        row["language"] = language
    # created_at only on first write — merge-duplicates keeps existing
    row["created_at"] = now
    upsert_job_row(row)


def summaries_for_user(user_id: str, *, limit: int = 40) -> list[JobSummary]:
    rows = list_job_rows(user_id=user_id, limit=limit)
    out: list[JobSummary] = []
    for row in rows:
        try:
            status_raw = str(row.get("status") or "queued")
            try:
                status = JobStatus(status_raw)
            except ValueError:
                status = JobStatus.PROCESSING
            video_url = None
            thumb_url = None
            try:
                from youtube_pipeline.api.supabase_storage import signed_urls_for_job_row

                video_url, thumb_url = signed_urls_for_job_row(row)
            except Exception:  # noqa: BLE001
                pass
            out.append(
                JobSummary(
                    job_id=str(row["id"]),
                    status=status,
                    title=str(row.get("title") or ""),
                    idea=str(row.get("idea") or ""),
                    current_stage=str(row.get("current_stage") or ""),
                    progress_percent=int(row.get("progress_percent") or 0),
                    updated_at=str(row.get("updated_at") or ""),
                    can_edit=status
                    in {
                        JobStatus.WAITING_FOR_ASSETS,
                        JobStatus.FAILED,
                        JobStatus.COMPLETED,
                    },
                    video_url=video_url,
                    thumb_url=thumb_url,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skip bad job row | %s | %s", row.get("id"), exc)
    return out


def user_owns_job(job_id: str, user_id: str) -> bool:
    if user_id == "local-dev":
        return True
    if not supabase_configured():
        return True
    row = get_job_row(job_id)
    if row is None:
        # Job may exist only on disk/redis during transition.
        return True
    return str(row.get("user_id") or "") == user_id

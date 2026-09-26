"""Tests for Supabase job persistence helpers (mocked HTTP)."""

from __future__ import annotations

from youtube_pipeline.api.schemas import JobStatus, JobStatusResponse
from youtube_pipeline.api.supabase_jobs import (
    persist_job_to_supabase,
    storage_prefix_for,
    summaries_for_user,
    user_owns_job,
)


def test_storage_prefix() -> None:
    assert storage_prefix_for("u1", "j1") == "u1/j1"


def test_persist_noop_without_config(monkeypatch) -> None:
    monkeypatch.setattr(
        "youtube_pipeline.api.supabase_jobs.supabase_configured",
        lambda: False,
    )
    state = JobStatusResponse(job_id="j1", status=JobStatus.QUEUED)
    persist_job_to_supabase(state, user_id="u1")  # should not raise


def test_user_owns_job_local_dev() -> None:
    assert user_owns_job("any", "local-dev") is True


def test_summaries_for_user(monkeypatch) -> None:
    monkeypatch.setattr(
        "youtube_pipeline.api.supabase_jobs.list_job_rows",
        lambda *, user_id, limit=40: [
            {
                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "status": "waiting_for_assets",
                "title": "Night Run",
                "idea": "a chase",
                "current_stage": "Review",
                "progress_percent": 80,
                "updated_at": "2026-08-15T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        "youtube_pipeline.api.supabase_storage.signed_urls_for_job_row",
        lambda row: (None, None),
    )
    rows = summaries_for_user("user-1", limit=10)
    assert len(rows) == 1
    assert rows[0].title == "Night Run"
    assert rows[0].can_edit is True

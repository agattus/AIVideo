"""Tests for previous-jobs library listing and reopen/edit."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from youtube_pipeline.api.job_store import (
    get_job,
    init_job,
    list_jobs,
    to_job_summary,
    update_job,
)
from youtube_pipeline.api.schemas import JobStatus


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def keys(self, pattern: str = "*") -> list[str]:
        prefix = pattern.rstrip("*")
        if pattern.endswith("*"):
            return [k for k in self._store if k.startswith(prefix)]
        return [k for k in self._store if k == pattern]


def _seed_run_dir(
    run_dir: Path,
    *,
    title: str = "Old Film",
    idea: str = "A myth story",
    with_request: bool = True,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "assets").mkdir(exist_ok=True)
    if with_request:
        (run_dir / "request.json").write_text(
            json.dumps({"idea": idea, "style": "cinematic", "duration": 60}),
            encoding="utf-8",
        )
    (run_dir / "script.json").write_text(
        json.dumps(
            {
                "title": title,
                "full_script": "Once upon a time.",
                "scenes": [
                    {
                        "scene_id": 0,
                        "script_text": "Once upon a time.",
                        "visual_prompt": "A temple at dawn",
                        "keywords": ["temple"],
                        "duration": 4.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "prompts.json").write_text(
        json.dumps(
            {
                "title": title,
                "style": "cinematic",
                "scene_count": 1,
                "scenes": [
                    {
                        "scene_number": 1,
                        "scene_id": 0,
                        "filename": "scene_00.jpg",
                        "visual_prompt": "A temple at dawn",
                        "script_text": "Once upon a time.",
                        "duration_seconds": 4.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "audio").mkdir(exist_ok=True)
    (run_dir / "audio" / "voiceover.mp3").write_bytes(b"x" * 512)
    (run_dir / "WAITING_FOR_ASSETS.txt").write_text("waiting", encoding="utf-8")


def test_list_jobs_from_memory_store(tmp_path: Path) -> None:
    fake = _FakeRedis()
    run = tmp_path / "lib-a"
    _seed_run_dir(run, title="Matsya", idea="Matsya Avatar")
    init_job("lib-a", client=fake)  # type: ignore[arg-type]
    update_job(
        "lib-a",
        status=JobStatus.WAITING_FOR_ASSETS,
        title="Matsya",
        idea="Matsya Avatar",
        run_dir=str(run),
        scene_count=3,
        client=fake,  # type: ignore[arg-type]
    )
    init_job("lib-b", client=fake)  # type: ignore[arg-type]

    # Queued job without a run folder is hidden from the library view.
    jobs = list_jobs(limit=10, client=fake, require_run_dir=True)  # type: ignore[arg-type]
    ids = {j.job_id for j in jobs}
    assert "lib-a" in ids
    assert "lib-b" not in ids
    matsya = next(j for j in jobs if j.job_id == "lib-a")
    assert matsya.title == "Matsya"
    assert matsya.status == JobStatus.WAITING_FOR_ASSETS


def test_list_jobs_discovers_output_folders(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "output"
    job_dir = out / "disk-job-1"
    _seed_run_dir(job_dir, title="Disk Film", idea="Recovered idea")
    monkeypatch.setenv("OUTPUT_DIR", str(out))

    # Clear settings cache so OUTPUT_DIR is picked up if settings is consulted.
    from config.settings import get_settings

    get_settings.cache_clear()

    fake = _FakeRedis()
    jobs = list_jobs(limit=20, client=fake, require_run_dir=True)  # type: ignore[arg-type]
    found = next((j for j in jobs if j.job_id == "disk-job-1"), None)
    assert found is not None
    assert found.title == "Disk Film"
    assert found.idea == "Recovered idea"
    assert found.run_dir is not None
    assert Path(found.run_dir) == job_dir.resolve()


def test_list_jobs_discovers_without_request_json(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "output"
    job_dir = out / "20250726T120000Z_cli-film"
    _seed_run_dir(job_dir, title="CLI Film", idea="from cli", with_request=False)
    # No request.json — still discoverable via script.json
    assert not (job_dir / "request.json").exists()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    from config.settings import get_settings

    get_settings.cache_clear()

    jobs = list_jobs(limit=20, client=_FakeRedis(), require_run_dir=True)  # type: ignore[arg-type]
    found = next((j for j in jobs if j.job_id == "20250726T120000Z_cli-film"), None)
    assert found is not None
    assert found.title == "CLI Film"


def test_list_jobs_uses_project_output_when_cwd_differs(
    tmp_path: Path, monkeypatch
) -> None:
    """Relative ./output must resolve via Settings / project root, not only cwd."""
    out = tmp_path / "output"
    job_dir = out / "cwd-independent"
    _seed_run_dir(job_dir, title="Elsewhere", idea="idea")

    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)

    from config.settings import get_settings

    get_settings.cache_clear()

    with patch(
        "youtube_pipeline.api.job_store._settings_output_dir",
        return_value=out,
    ):
        jobs = list_jobs(limit=20, client=_FakeRedis(), require_run_dir=True)  # type: ignore[arg-type]

    found = next((j for j in jobs if j.job_id == "cwd-independent"), None)
    assert found is not None
    assert found.title == "Elsewhere"
    get_settings.cache_clear()


def test_to_job_summary_can_edit_flags(tmp_path: Path) -> None:
    fake = _FakeRedis()
    run = tmp_path / "sum-1"
    _seed_run_dir(run)
    init_job("sum-1", client=fake)  # type: ignore[arg-type]
    waiting = update_job(
        "sum-1",
        status=JobStatus.WAITING_FOR_ASSETS,
        title="Edit Me",
        idea="idea",
        run_dir=str(run),
        client=fake,  # type: ignore[arg-type]
    )
    summary = to_job_summary(waiting, static_dir=tmp_path / "static")
    assert summary.can_edit is True
    assert summary.title == "Edit Me"

    queued = update_job(
        "sum-1",
        status=JobStatus.QUEUED,
        client=fake,  # type: ignore[arg-type]
    )
    assert to_job_summary(queued).can_edit is False


def test_get_jobs_and_reopen_endpoints(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "output"
    run_dir = out / "api-job"
    _seed_run_dir(run_dir, title="API Film", idea="API idea")
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    from config.settings import get_settings

    get_settings.cache_clear()

    fake = _FakeRedis()
    init_job("api-job", client=fake)  # type: ignore[arg-type]
    update_job(
        "api-job",
        status=JobStatus.COMPLETED,
        title="API Film",
        idea="API idea",
        run_dir=str(run_dir),
        scene_count=1,
        progress_percent=100,
        current_stage="Done",
        client=fake,  # type: ignore[arg-type]
    )

    with (
        patch(
            "youtube_pipeline.api.main.list_jobs",
            side_effect=lambda limit=40, require_run_dir=True: list_jobs(
                limit=limit, client=fake, require_run_dir=require_run_dir
            ),  # type: ignore[arg-type]
        ),
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch(
            "youtube_pipeline.api.main.update_job",
            side_effect=lambda jid, **kw: update_job(jid, client=fake, **kw),  # type: ignore[arg-type]
        ),
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
        patch("youtube_pipeline.api.main.redis_available", return_value=False),
    ):
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        listed = client.get("/api/v1/jobs?limit=10")
        assert listed.status_code == 200
        body = listed.json()
        assert body["count"] >= 1
        match = next(j for j in body["jobs"] if j["job_id"] == "api-job")
        assert match["title"] == "API Film"
        assert match["can_edit"] is True

        reopened = client.post("/api/v1/jobs/api-job/reopen")
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "waiting_for_assets"

        job = get_job("api-job", client=fake)  # type: ignore[arg-type]
        assert job is not None
        assert job.status == JobStatus.WAITING_FOR_ASSETS
        assert "Reopened" in job.current_stage

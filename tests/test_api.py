"""Tests for the async FastAPI + Celery job layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from youtube_pipeline.api.job_store import get_job, init_job, job_key, update_job
from youtube_pipeline.api.schemas import (
    GenerateVideoRequest,
    JobStatus,
    JobStatusResponse,
)
from youtube_pipeline.orchestrator import STAGE_PROGRESS, VideoPipelineOrchestrator
from youtube_pipeline.models import PipelineRequest, VisualStyle


class _FakeRedis:
    """Minimal in-memory Redis stand-in for job_store tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self._store.get(key)


def test_generate_video_request_defaults() -> None:
    req = GenerateVideoRequest(idea="Matsya Avatar myth")
    assert req.style == "cinematic"
    assert req.duration == 60
    assert req.max_scenes == 8


def test_job_store_roundtrip() -> None:
    client = _FakeRedis()
    state = init_job("job-123", client=client)  # type: ignore[arg-type]
    assert state.status == JobStatus.QUEUED
    assert client.get(job_key("job-123"))

    updated = update_job(
        "job-123",
        status=JobStatus.PROCESSING,
        current_stage="Stage 1/5: Generating Script",
        progress_percent=20,
        client=client,  # type: ignore[arg-type]
    )
    assert updated.progress_percent == 20
    loaded = get_job("job-123", client=client)  # type: ignore[arg-type]
    assert loaded is not None
    assert loaded.current_stage.startswith("Stage 1/5")


def test_orchestrator_emits_stage_progress(tmp_path: Path) -> None:
    from config.settings import Settings
    from tests.test_orchestrator import (
        FakeAssetService,
        FakeAudioEngine,
        FakeScriptEngine,
        FakeVideoComposer,
    )

    events: list[tuple[int, str, int]] = []

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        openai_api_key="test",
        gemini_api_key="test",
    )
    settings.ensure_directories()

    orch = VideoPipelineOrchestrator(
        settings=settings,
        script_engine=FakeScriptEngine(),  # type: ignore[arg-type]
        audio_engine=FakeAudioEngine(),  # type: ignore[arg-type]
        asset_service=FakeAssetService(),  # type: ignore[arg-type]
        video_composer=FakeVideoComposer(),  # type: ignore[arg-type]
        on_progress=lambda stage, label, pct: events.append((stage, label, pct)),
    )
    orch.run(
        PipelineRequest(
            idea="The future of renewable energy",
            style=VisualStyle.CINEMATIC,
            output_name="renewable",
        )
    )

    assert [e[0] for e in events] == [1, 2, 3, 4, 5]
    assert events[0][2] == STAGE_PROGRESS[1]
    assert all("/5:" in e[1] or e[1].startswith("Stage ") for e in events)


def test_post_generate_returns_202_and_enqueues(tmp_path: Path) -> None:
    fake = _FakeRedis()

    with (
        patch("youtube_pipeline.api.main.init_job", side_effect=lambda job_id: init_job(job_id, client=fake)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.redis_available", return_value=True),
        patch("youtube_pipeline.api.main.run_video_pipeline") as mock_task,
    ):
        mock_task.delay = MagicMock()
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/generate",
            json={
                "idea": "Ancient Matsya Avatar story",
                "style": "cinematic",
                "duration": 90,
                "max_scenes": 10,
            },
        )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert "job_id" in body
    mock_task.delay.assert_called_once()
    args, _kwargs = mock_task.delay.call_args
    assert args[0] == body["job_id"]
    assert args[1]["idea"] == "Ancient Matsya Avatar story"
    assert args[1]["duration"] == 90


def test_post_generate_falls_back_to_thread_without_redis() -> None:
    with (
        patch("youtube_pipeline.api.main.redis_available", return_value=False),
        patch("youtube_pipeline.api.main.init_job") as mock_init,
        patch("youtube_pipeline.api.main.threading.Thread") as mock_thread,
    ):
        mock_init.side_effect = lambda job_id: JobStatusResponse(
            job_id=job_id, status=JobStatus.QUEUED
        )
        thread_instance = MagicMock()
        mock_thread.return_value = thread_instance
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/generate",
            json={"idea": "Local thread fallback story", "duration": 30, "max_scenes": 4},
        )

    assert response.status_code == 202
    mock_thread.assert_called_once()
    thread_instance.start.assert_called_once()


def test_studio_home_serves_ui() -> None:
    from youtube_pipeline.api.main import app

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "AIVideo" in response.text
    assert "Generate video" in response.text


def test_healthz_reports_ui() -> None:
    from youtube_pipeline.api.main import app

    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ui"] is True


def test_get_status_404_for_unknown_job() -> None:
    with patch("youtube_pipeline.api.main.get_job", return_value=None):
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        response = client.get("/api/v1/status/does-not-exist")
    assert response.status_code == 404


def test_get_status_returns_job_payload() -> None:
    state = JobStatusResponse(
        job_id="abc",
        status=JobStatus.PROCESSING,
        current_stage="Stage 2/5: Synthesizing Audio",
        progress_percent=40,
    )
    with patch("youtube_pipeline.api.main.get_job", return_value=state):
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        response = client.get("/api/v1/status/abc")
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "abc"
    assert body["progress_percent"] == 40
    assert body["status"] == "processing"


def test_publish_artifacts_copies_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from youtube_pipeline.api import tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "STATIC_DIR", tmp_path / "static")

    audio = tmp_path / "voiceover.mp3"
    script = tmp_path / "script.json"
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "scene_00.jpg").write_bytes(b"jpg")
    audio.write_bytes(b"mp3")
    script.write_text(json.dumps({"title": "t"}), encoding="utf-8")

    urls = tasks_mod._publish_artifacts(
        "job-xyz",
        audio=audio,
        script=script,
        assets_dir=assets,
    )
    assert urls.video_url is None
    assert urls.audio_url == "/static/job-xyz/audio.mp3"
    assert urls.script_url == "/static/job-xyz/script.json"
    assert urls.assets_url == "/static/job-xyz/assets/"
    assert (tmp_path / "static" / "job-xyz" / "audio.mp3").exists()
    assert (tmp_path / "static" / "job-xyz" / "script.json").exists()
    assert (tmp_path / "static" / "job-xyz" / "assets" / "scene_00.jpg").exists()

"""Tests for the async FastAPI + Celery human-in-the-loop job layer."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from youtube_pipeline.api.job_store import get_job, init_job, job_key, update_job
from youtube_pipeline.api.schemas import (
    GenerateVideoRequest,
    JobStatus,
)
from youtube_pipeline.models import PipelineRequest, VisualStyle
from youtube_pipeline.orchestrator import STAGE_PROGRESS, VideoPipelineOrchestrator


class _FakeRedis:
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
    assert req.aspect_ratio == "16:9"


def test_job_store_roundtrip_waiting_for_assets() -> None:
    client = _FakeRedis()
    state = init_job("job-123", client=client)  # type: ignore[arg-type]
    assert state.status == JobStatus.QUEUED

    updated = update_job(
        "job-123",
        status=JobStatus.WAITING_FOR_ASSETS,
        current_stage="Waiting for assets",
        progress_percent=75,
        run_dir="/tmp/run",
        scene_count=4,
        client=client,  # type: ignore[arg-type]
    )
    assert updated.status == JobStatus.WAITING_FOR_ASSETS
    assert updated.run_dir == "/tmp/run"
    assert updated.scene_count == 4
    loaded = get_job("job-123", client=client)  # type: ignore[arg-type]
    assert loaded is not None
    assert loaded.status == JobStatus.WAITING_FOR_ASSETS


def test_orchestrator_emits_phase1_stage_progress(tmp_path: Path) -> None:
    from config.settings import Settings
    from tests.test_orchestrator import FakeAssetService, FakeAudioEngine, FakeComposer, FakeScriptEngine

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
        video_composer=FakeComposer(),  # type: ignore[arg-type]
        on_progress=lambda stage, label, pct: events.append((stage, label, pct)),
    )
    orch.run(
        PipelineRequest(
            idea="The future of renewable energy",
            style=VisualStyle.CINEMATIC,
            output_name="renewable",
        )
    )

    assert [e[0] for e in events] == [1, 2, 3]
    assert events[0][2] == STAGE_PROGRESS[1]
    assert all("/3:" in e[1] for e in events)


def test_post_generate_returns_202_and_enqueues(tmp_path: Path) -> None:
    fake = _FakeRedis()

    with (
        patch(
            "youtube_pipeline.api.main.init_job",
            side_effect=lambda job_id: init_job(job_id, client=fake),  # type: ignore[arg-type]
        ),
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
                "aspect_ratio": "9:16",
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        assert "job_id" in body
        mock_task.delay.assert_called_once()
        args = mock_task.delay.call_args[0]
        assert args[1]["aspect_ratio"] == "9:16"


def test_upload_assets_endpoint_dispatches_resume(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "job-upload-1"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "prompts.json").write_text(
        '{"title":"t","style":"cinematic","aspect_ratio":"16:9","scene_count":2,'
        '"scenes":[{"scene_number":1,"scene_id":0,"filename":"scene_00.jpg",'
        '"visual_prompt":"a"},{"scene_number":2,"scene_id":1,"filename":"scene_01.jpg",'
        '"visual_prompt":"b"}]}',
        encoding="utf-8",
    )
    init_job(job_id, client=fake)  # type: ignore[arg-type]
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        run_dir=str(run_dir),
        scene_count=2,
        client=fake,  # type: ignore[arg-type]
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(2):
            img_buf = io.BytesIO()
            Image.new("RGB", (32, 32), (i * 50, 80, 120)).save(img_buf, format="JPEG")
            zf.writestr(f"scene_{i:02d}.jpg", img_buf.getvalue())
    buf.seek(0)

    with (
        patch("youtube_pipeline.api.main.get_job", side_effect=lambda jid: get_job(jid, client=fake)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.redis_available", return_value=False),
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
        patch("youtube_pipeline.api.main._dispatch_resume", return_value="thread") as mock_dispatch,
    ):
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        response = client.post(
            f"/api/v1/jobs/{job_id}/upload-assets",
            files={"file": ("assets.zip", buf.getvalue(), "application/zip")},
        )
        assert response.status_code == 202
        assert response.json()["status"] == "processing"
        mock_dispatch.assert_called_once_with(job_id, zip_path=None)
        zip_saved = run_dir / "uploads" / "assets.zip"
        assert zip_saved.exists()
        assert zip_saved.stat().st_size > 64
        assert (run_dir / "assets" / "scene_00.jpg").exists()

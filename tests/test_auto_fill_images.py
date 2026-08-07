"""Tests for automatic scene-image generation in the HITL workspace."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from config.settings import AssetProvider
from tests.test_hitl_workspace import _FakeRedis, _make_run
from youtube_pipeline.api.job_store import get_job, init_job, update_job
from youtube_pipeline.api.schemas import JobStatus, SceneSlot
from youtube_pipeline.assets.hitl_workspace import (
    auto_fill_scene_images,
    save_scene_image,
    workspace_status,
)
from youtube_pipeline.exceptions import ConfigurationError
from youtube_pipeline.models import MediaAsset, PipelineResult


def _jpeg_bytes(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=color).save(buf, format="JPEG")
    return buf.getvalue()


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.name = "gemini_image"

    def fake_fetch(scene, output_dir, *, aspect_ratio="16:9"):
        dest = Path(output_dir) / f"raw_{scene.scene_id}.jpg"
        dest.write_bytes(_jpeg_bytes())
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(dest),
            source="gemini_image",
            media_type="image",
        )

    provider.fetch_for_scene.side_effect = fake_fetch
    return provider


def _gemini_settings() -> SimpleNamespace:
    return SimpleNamespace(asset_provider=AssetProvider.GEMINI_IMAGE)


def _phase1_result(run: Path) -> PipelineResult:
    audio = run / "audio" / "voiceover.mp3"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    script = run / "script.json"
    script.write_text('{"title": "Test", "scenes": []}', encoding="utf-8")
    prompts = run / "prompts.json"
    prompts.write_text(
        '{"title":"Test","style":"cinematic","aspect_ratio":"16:9",'
        '"scene_count":2,"scenes":[]}',
        encoding="utf-8",
    )
    return PipelineResult(
        video_path=str(run),
        status="waiting_for_assets",
        metadata={
            "run_dir": str(run),
            "audio_path": str(audio),
            "script_path": str(script),
            "prompts_json": str(prompts),
            "scene_count": 2,
            "title": "Test",
            "idea": "Test idea",
        },
    )


def test_execute_video_pipeline_calls_auto_fill_and_reports_progress(tmp_path: Path) -> None:
    from youtube_pipeline.api import tasks

    run = tmp_path / "run"
    run.mkdir()
    result = _phase1_result(run)
    updates: list[dict[str, object]] = []

    def fake_auto_fill(run_dir, *, on_progress):
        assert Path(run_dir) == run
        on_progress(1, 2, "Generating scene 1/2")
        on_progress(2, 2, "Generating scene 2/2")
        return {"filled": 2, "skipped": 0, "failed": [], "provider": "gemini_image"}

    with (
        patch(
            "youtube_pipeline.orchestrator.VideoPipelineOrchestrator",
            return_value=SimpleNamespace(run=MagicMock(return_value=result)),
        ),
        patch("config.settings.get_settings", return_value=_gemini_settings()),
        patch(
            "youtube_pipeline.assets.hitl_workspace.auto_fill_scene_images",
            side_effect=fake_auto_fill,
        ) as mock_fill,
        patch.object(tasks, "STATIC_DIR", tmp_path / "static"),
        patch.object(tasks, "update_job", side_effect=lambda _job_id, **data: updates.append(data)),
    ):
        response = tasks.execute_video_pipeline(
            "job-auto-fill",
            {"idea": "Test idea", "max_scenes": 2},
        )

    mock_fill.assert_called_once()
    assert response["status"] == "waiting_for_assets"
    assert [
        (update["current_stage"], update["progress_percent"], update["status"])
        for update in updates
        if "/" in str(update.get("current_stage", ""))
    ] == [
        ("Generating scene 1/2", 82, tasks.JobStatus.WAITING_FOR_ASSETS),
        ("Generating scene 2/2", 90, tasks.JobStatus.WAITING_FOR_ASSETS),
    ]
    assert updates[-1]["status"] == tasks.JobStatus.WAITING_FOR_ASSETS
    assert updates[-1]["current_stage"] == "Review scene images, then assemble"
    assert updates[-1]["progress_percent"] == 92


def test_execute_video_pipeline_manual_provider_skips_auto_fill(tmp_path: Path) -> None:
    from youtube_pipeline.api import tasks

    run = tmp_path / "run"
    run.mkdir()
    updates: list[dict[str, object]] = []

    with (
        patch(
            "youtube_pipeline.orchestrator.VideoPipelineOrchestrator",
            return_value=SimpleNamespace(
                run=MagicMock(return_value=_phase1_result(run))
            ),
        ),
        patch(
            "config.settings.get_settings",
            return_value=SimpleNamespace(asset_provider=AssetProvider.MANUAL),
        ),
        patch("youtube_pipeline.assets.hitl_workspace.auto_fill_scene_images") as mock_fill,
        patch.object(tasks, "STATIC_DIR", tmp_path / "static"),
        patch.object(tasks, "update_job", side_effect=lambda _job_id, **data: updates.append(data)),
    ):
        response = tasks.execute_video_pipeline(
            "job-manual",
            {"idea": "Test idea", "max_scenes": 2},
        )

    mock_fill.assert_not_called()
    assert response["status"] == "waiting_for_assets"
    assert updates[-1]["status"] == tasks.JobStatus.WAITING_FOR_ASSETS
    assert updates[-1]["current_stage"] == "Your turn — add scene images, then assemble"
    assert updates[-1]["progress_percent"] == 75


def test_execute_video_pipeline_soft_fails_when_auto_fill_crashes(tmp_path: Path) -> None:
    from youtube_pipeline.api import tasks

    run = tmp_path / "run"
    run.mkdir()
    updates: list[dict[str, object]] = []

    with (
        patch(
            "youtube_pipeline.orchestrator.VideoPipelineOrchestrator",
            return_value=SimpleNamespace(
                run=MagicMock(return_value=_phase1_result(run))
            ),
        ),
        patch("config.settings.get_settings", return_value=_gemini_settings()),
        patch(
            "youtube_pipeline.assets.hitl_workspace.auto_fill_scene_images",
            side_effect=RuntimeError("generator offline"),
        ),
        patch.object(tasks, "STATIC_DIR", tmp_path / "static"),
        patch.object(tasks, "update_job", side_effect=lambda _job_id, **data: updates.append(data)),
    ):
        response = tasks.execute_video_pipeline(
            "job-soft-fail",
            {"idea": "Test idea", "max_scenes": 2},
        )

    assert response["status"] == "waiting_for_assets"
    assert updates[-1]["status"] == tasks.JobStatus.WAITING_FOR_ASSETS
    assert updates[-1]["current_stage"] == (
        "Image generation failed — regenerate or upload scene images"
    )
    assert updates[-1]["progress_percent"] == 92
    assert all(update.get("status") != tasks.JobStatus.FAILED for update in updates)


def test_auto_fill_writes_missing_scenes_and_reports_progress(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=2)
    provider = _provider()
    progress: list[tuple[int, int, str]] = []

    with (
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=_gemini_settings(),
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
            return_value=provider,
        ),
    ):
        result = auto_fill_scene_images(run, on_progress=lambda *args: progress.append(args))

    assert result == {
        "filled": 2,
        "skipped": 0,
        "failed": [],
        "errors": {},
        "provider": "gemini_image",
    }
    assert (run / "assets" / "scene_00.jpg").stat().st_size > 256
    assert (run / "assets" / "scene_01.jpg").stat().st_size > 256
    assert progress == [
        (1, 2, "Generating scene 1/2"),
        (2, 2, "Generating scene 2/2"),
    ]

    status = workspace_status(run)
    assert [scene["source"] for scene in status["scenes"]] == ["gemini", "gemini"]
    assert [scene["error"] for scene in status["scenes"]] == [None, None]
    sources = json.loads(
        (run / "assets" / "scene_sources.json").read_text(encoding="utf-8")
    )
    assert sources == {"0": "gemini", "1": "gemini"}
    SceneSlot.model_validate(status["scenes"][0])


def test_workspace_source_is_none_when_scene_has_no_source(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=1)

    assert workspace_status(run)["scenes"][0]["source"] is None


def test_auto_fill_skips_ready_scene_unless_forced(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=2)
    save_scene_image(run, 0, _jpeg_bytes((100, 20, 30)), source_name="upload.png")
    provider = _provider()

    with (
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=_gemini_settings(),
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
            return_value=provider,
        ),
    ):
        first = auto_fill_scene_images(run)
        forced = auto_fill_scene_images(run, force=True)

    assert first["filled"] == 1
    assert first["skipped"] == 1
    assert forced["filled"] == 2
    assert forced["skipped"] == 0
    assert provider.fetch_for_scene.call_count == 3


def test_auto_fill_continues_after_failure_and_persists_error(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=2)
    provider = _provider()
    successful_fetch = provider.fetch_for_scene.side_effect

    def fail_first(scene, output_dir, *, aspect_ratio="16:9"):
        if scene.scene_id == 0:
            raise RuntimeError("generation unavailable")
        return successful_fetch(scene, output_dir, aspect_ratio=aspect_ratio)

    provider.fetch_for_scene.side_effect = fail_first

    with (
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=_gemini_settings(),
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
            return_value=provider,
        ),
    ):
        result = auto_fill_scene_images(run)

    assert result["filled"] == 1
    assert result["failed"] == [{"scene_id": 0, "error": "generation unavailable"}]
    assert not (run / "assets" / "scene_00.jpg").exists()
    assert (run / "assets" / "scene_01.jpg").exists()
    errors = json.loads((run / "assets" / "scene_errors.json").read_text(encoding="utf-8"))
    assert errors == {"0": "generation unavailable"}
    assert workspace_status(run)["scenes"][0]["error"] == "generation unavailable"


def test_successful_retry_clears_scene_error(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=1)
    errors_path = run / "assets" / "scene_errors.json"
    errors_path.write_text('{"0": "old failure"}', encoding="utf-8")

    with (
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=_gemini_settings(),
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
            return_value=_provider(),
        ),
    ):
        result = auto_fill_scene_images(run)

    assert result["filled"] == 1
    assert json.loads(errors_path.read_text(encoding="utf-8")) == {}
    assert workspace_status(run)["scenes"][0]["error"] is None


def test_manual_scene_save_clears_error_and_records_upload_source(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=1)
    errors_path = run / "assets" / "scene_errors.json"
    errors_path.write_text('{"0": "generation failed"}', encoding="utf-8")

    save_scene_image(run, 0, _jpeg_bytes(), source_name="replacement.png")

    scene = workspace_status(run)["scenes"][0]
    assert scene["source"] == "upload"
    assert scene["error"] is None
    assert json.loads(errors_path.read_text(encoding="utf-8")) == {}


def test_manual_provider_skips_auto_fill(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=2)

    with patch(
        "youtube_pipeline.assets.hitl_workspace.get_settings",
        return_value=SimpleNamespace(asset_provider=AssetProvider.MANUAL),
    ):
        result = auto_fill_scene_images(run)

    assert result == {
        "filled": 0,
        "skipped": 0,
        "failed": [],
        "provider": "manual",
        "skipped_manual": True,
    }
    assert not (run / "assets" / "scene_00.jpg").exists()


def _init_api_job(fake: _FakeRedis, job_id: str, run: Path, scenes: int) -> None:
    init_job(job_id, client=fake)  # type: ignore[arg-type]
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        run_dir=str(run),
        scene_count=scenes,
        client=fake,  # type: ignore[arg-type]
    )


def test_generate_one_scene_endpoint_force_replaces_and_publishes(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "job-generate-one"
    run = _make_run(tmp_path, scenes=2)
    save_scene_image(run, 0, _jpeg_bytes((200, 10, 10)), source_name="upload.jpg")
    before = (run / "assets" / "scene_00.jpg").read_bytes()
    _init_api_job(fake, job_id, run, scenes=2)

    with (
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=_gemini_settings(),
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
            return_value=_provider(),
        ),
    ):
        from youtube_pipeline.api.main import app

        response = TestClient(app).post(
            f"/api/v1/jobs/{job_id}/scenes/0/generate"
        )

    assert response.status_code == 200
    assert response.json() == {
        "job_id": job_id,
        "filled": 1,
        "skipped": 0,
        "failed": [],
        "provider": "gemini_image",
        "message": "Generated image for scene 1",
    }
    assert (run / "assets" / "scene_00.jpg").read_bytes() != before
    assert (tmp_path / "static" / job_id / "assets" / "scene_00.jpg").exists()


def test_generate_images_endpoint_fills_only_missing_by_default(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "job-generate-missing"
    run = _make_run(tmp_path, scenes=2)
    save_scene_image(run, 0, _jpeg_bytes((100, 20, 30)), source_name="upload.jpg")
    _init_api_job(fake, job_id, run, scenes=2)
    provider = _provider()

    with (
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=_gemini_settings(),
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
            return_value=provider,
        ),
    ):
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        response = client.post(
            f"/api/v1/jobs/{job_id}/generate-images"
        )
        forced = client.post(
            f"/api/v1/jobs/{job_id}/generate-images?force=true"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert body["filled"] == 1
    assert body["skipped"] == 1
    assert body["failed"] == []
    assert body["provider"] == "gemini_image"
    assert (run / "assets" / "scene_01.jpg").exists()
    assert (tmp_path / "static" / job_id / "assets" / "scene_01.jpg").exists()
    assert forced.status_code == 200
    assert forced.json()["filled"] == 2
    assert forced.json()["skipped"] == 0
    assert provider.fetch_for_scene.call_count == 3


def test_generate_images_endpoint_rejects_manual_provider(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "job-generate-manual"
    run = _make_run(tmp_path, scenes=1)
    _init_api_job(fake, job_id, run, scenes=1)

    with (
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=SimpleNamespace(asset_provider=AssetProvider.MANUAL),
        ),
    ):
        from youtube_pipeline.api.main import app

        response = TestClient(app).post(
            f"/api/v1/jobs/{job_id}/generate-images"
        )

    assert response.status_code == 400
    assert "upload" in response.json()["detail"].lower()
    assert "provider" in response.json()["detail"].lower()


def _failing_provider(error: str = "Gemini response contained no image data") -> MagicMock:
    provider = MagicMock()
    provider.name = "gemini_image"
    provider.fetch_for_scene.side_effect = RuntimeError(error)
    return provider


def test_generate_one_scene_endpoint_reports_failure_message(tmp_path: Path) -> None:
    """F2: a failed generate must never claim success in `message`, even with HTTP 200."""
    fake = _FakeRedis()
    job_id = "job-generate-one-fail"
    run = _make_run(tmp_path, scenes=1)
    _init_api_job(fake, job_id, run, scenes=1)

    with (
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=_gemini_settings(),
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
            return_value=_failing_provider(),
        ),
    ):
        from youtube_pipeline.api.main import app

        response = TestClient(app).post(f"/api/v1/jobs/{job_id}/scenes/0/generate")

    assert response.status_code == 200
    body = response.json()
    assert body["filled"] == 0
    assert body["failed"] == [{"scene_id": 0, "error": "Gemini response contained no image data"}]
    assert "fail" in body["message"].lower()
    assert "regenerated" not in body["message"].lower()
    assert "scene 1" in body["message"].lower()


def test_generate_images_endpoint_reports_failure_message(tmp_path: Path) -> None:
    """F2: the bulk endpoint must also surface failures instead of a blanket success line."""
    fake = _FakeRedis()
    job_id = "job-generate-bulk-fail"
    run = _make_run(tmp_path, scenes=1)
    _init_api_job(fake, job_id, run, scenes=1)

    with (
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=_gemini_settings(),
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
            return_value=_failing_provider(),
        ),
    ):
        from youtube_pipeline.api.main import app

        response = TestClient(app).post(f"/api/v1/jobs/{job_id}/generate-images")

    assert response.status_code == 200
    body = response.json()
    assert body["filled"] == 0
    assert len(body["failed"]) == 1
    assert "fail" in body["message"].lower()
    assert "finished" not in body["message"].lower() or "fail" in body["message"].lower()


def test_generate_one_scene_endpoint_missing_api_key_returns_400(tmp_path: Path) -> None:
    """F3: a missing/invalid GEMINI_API_KEY must surface as a clear 400, not a 500."""
    fake = _FakeRedis()
    job_id = "job-generate-one-no-key"
    run = _make_run(tmp_path, scenes=1)
    _init_api_job(fake, job_id, run, scenes=1)

    with (
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=_gemini_settings(),
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
            side_effect=ConfigurationError("GEMINI_API_KEY is required for asset provider 'gemini_image'"),
        ),
    ):
        from youtube_pipeline.api.main import app

        response = TestClient(app).post(f"/api/v1/jobs/{job_id}/scenes/0/generate")

    assert response.status_code == 400
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_generate_images_endpoint_missing_api_key_returns_400(tmp_path: Path) -> None:
    """F3: same clear-4xx behavior for the bulk generate-images endpoint."""
    fake = _FakeRedis()
    job_id = "job-generate-bulk-no-key"
    run = _make_run(tmp_path, scenes=1)
    _init_api_job(fake, job_id, run, scenes=1)

    with (
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.get_settings",
            return_value=_gemini_settings(),
        ),
        patch(
            "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
            side_effect=ConfigurationError("GEMINI_API_KEY is required for asset provider 'gemini_image'"),
        ),
    ):
        from youtube_pipeline.api.main import app

        response = TestClient(app).post(f"/api/v1/jobs/{job_id}/generate-images")

    assert response.status_code == 400
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_workspace_response_exposes_image_provider(tmp_path: Path) -> None:
    """F5: the studio needs the active provider to decide whether to show Regenerate."""
    fake = _FakeRedis()
    job_id = "job-workspace-provider"
    run = _make_run(tmp_path, scenes=1)
    _init_api_job(fake, job_id, run, scenes=1)

    with (
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
        patch("config.settings.get_settings", return_value=_gemini_settings()),
    ):
        from youtube_pipeline.api.main import app

        response = TestClient(app).get(f"/api/v1/jobs/{job_id}/workspace")

    assert response.status_code == 200
    assert response.json()["image_provider"] == "gemini_image"

"""Tests for automatic scene-image generation in the HITL workspace."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from config.settings import AssetProvider
from tests.test_hitl_workspace import _make_run
from youtube_pipeline.api.schemas import SceneSlot
from youtube_pipeline.assets.hitl_workspace import (
    auto_fill_scene_images,
    save_scene_image,
    workspace_status,
)
from youtube_pipeline.models import MediaAsset, PipelineResult


def _jpeg_bytes(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=color).save(buf, format="JPEG")
    return buf.getvalue()


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.name = "gemini_image"

    def fake_fetch(scene, output_dir):
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

    def fail_first(scene, output_dir):
        if scene.scene_id == 0:
            raise RuntimeError("generation unavailable")
        return successful_fetch(scene, output_dir)

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

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
from youtube_pipeline.models import MediaAsset


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
    SceneSlot.model_validate(status["scenes"][0])


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

"""Tests for HITL workspace orchestration (prompts pack, scene save, BGM)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from youtube_pipeline.api.job_store import get_job, init_job, update_job
from youtube_pipeline.api.schemas import JobStatus
from youtube_pipeline.assets.hitl_workspace import (
    clipboard_text,
    save_bgm_file,
    save_scene_image,
    workspace_status,
    write_prompt_pack,
)


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self._store.get(key)


def _make_run(tmp_path: Path, scenes: int = 2) -> Path:
    run = tmp_path / "job-run"
    (run / "assets").mkdir(parents=True)
    (run / "audio").mkdir(parents=True)
    (run / "audio" / "voiceover.mp3").write_bytes(b"x" * 2048)
    payload = {
        "title": "Test Film",
        "style": "cinematic",
        "aspect_ratio": "16:9",
        "scene_count": scenes,
        "scenes": [
            {
                "scene_number": i + 1,
                "scene_id": i,
                "filename": f"scene_{i:02d}.jpg",
                "visual_prompt": f"Prompt for scene {i}",
                "script_text": f"Narration {i}",
                "duration_seconds": 3.0,
                "aspect_ratio": "16:9",
            }
            for i in range(scenes)
        ],
    }
    (run / "prompts.json").write_text(json.dumps(payload), encoding="utf-8")
    (run / "request.json").write_text(
        json.dumps(
            {
                "idea": "test",
                "style": "cinematic",
                "aspect_ratio": "16:9",
                "target_duration_seconds": 60,
                "max_scenes": scenes,
            }
        ),
        encoding="utf-8",
    )
    return run


def _jpeg_bytes(color: tuple[int, int, int] = (40, 90, 140)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="JPEG")
    return buf.getvalue()


def test_write_prompt_pack_and_clipboard(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=2)
    pack = write_prompt_pack(run)
    assert Path(pack["prompts_all_txt"]).exists()
    assert (run / "prompts" / "scene_00.txt").exists()
    text = clipboard_text(run)
    assert "Prompt for scene 0" in text
    assert "scene_00.jpg" in text


def test_save_scene_image_to_assets_slot(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=2)
    dest = save_scene_image(run, 1, _jpeg_bytes((10, 200, 30)), source_name="shot.png")
    assert dest.name == "scene_01.jpg"
    assert dest.exists() and dest.stat().st_size > 256
    ws = workspace_status(run, job_id="abc")
    assert ws["scenes_ready"] == 1
    assert ws["all_scenes_ready"] is False
    assert ws["scenes"][1]["ready"] is True


def test_save_bgm_file(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    path = save_bgm_file(run, b"m" * 4096, source_name="custom.mp3")
    assert path.name == "bgm.mp3"
    assert workspace_status(run)["bgm_ready"] is True


def test_workspace_and_scene_upload_endpoints(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "job-hitl-1"
    run = _make_run(tmp_path, scenes=2)
    init_job(job_id, client=fake)  # type: ignore[arg-type]
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        run_dir=str(run),
        scene_count=2,
        client=fake,  # type: ignore[arg-type]
    )

    with (
        patch("youtube_pipeline.api.main.get_job", side_effect=lambda jid: get_job(jid, client=fake)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.update_job", side_effect=lambda jid, **kw: update_job(jid, client=fake, **kw)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
    ):
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        ws = client.get(f"/api/v1/jobs/{job_id}/workspace")
        assert ws.status_code == 200
        body = ws.json()
        assert body["scene_count"] == 2
        assert body["scenes_ready"] == 0
        assert "Prompt for scene 0" in body["clipboard_text"]

        txt = client.get(f"/api/v1/jobs/{job_id}/prompts.txt")
        assert txt.status_code == 200
        assert "Prompt for scene 1" in txt.text

        up = client.post(
            f"/api/v1/jobs/{job_id}/scenes/0",
            files={"file": ("a.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        assert up.status_code == 200
        assert up.json()["filename"] == "scene_00.jpg"
        assert (run / "assets" / "scene_00.jpg").exists()


def test_bgm_upload_and_assemble_gate(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "job-hitl-2"
    run = _make_run(tmp_path, scenes=1)
    init_job(job_id, client=fake)  # type: ignore[arg-type]
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        run_dir=str(run),
        scene_count=1,
        client=fake,  # type: ignore[arg-type]
    )

    with (
        patch("youtube_pipeline.api.main.get_job", side_effect=lambda jid: get_job(jid, client=fake)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.update_job", side_effect=lambda jid, **kw: update_job(jid, client=fake, **kw)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
        patch("youtube_pipeline.api.main._dispatch_resume", return_value="thread") as mock_dispatch,
    ):
        from youtube_pipeline.api.main import app

        client = TestClient(app)

        blocked = client.post(f"/api/v1/jobs/{job_id}/assemble")
        assert blocked.status_code == 400

        client.post(
            f"/api/v1/jobs/{job_id}/scenes/0",
            files={"file": ("s.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        bgm = client.post(
            f"/api/v1/jobs/{job_id}/bgm",
            files={"file": ("bed.mp3", b"z" * 4096, "audio/mpeg")},
        )
        assert bgm.status_code == 200
        assert bgm.json()["bgm_ready"] is True
        assert (run / "assets" / "bgm.mp3").exists()

        ok = client.post(f"/api/v1/jobs/{job_id}/assemble")
        assert ok.status_code == 202
        mock_dispatch.assert_called_once_with(job_id, zip_path=None)


def test_zip_upload_assemble_false_places_images(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "job-hitl-3"
    run = _make_run(tmp_path, scenes=2)
    init_job(job_id, client=fake)  # type: ignore[arg-type]
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        run_dir=str(run),
        scene_count=2,
        client=fake,  # type: ignore[arg-type]
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(2):
            zf.writestr(f"scene_{i:02d}.jpg", _jpeg_bytes((i * 40, 80, 120)))
    buf.seek(0)

    with (
        patch("youtube_pipeline.api.main.get_job", side_effect=lambda jid: get_job(jid, client=fake)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.update_job", side_effect=lambda jid, **kw: update_job(jid, client=fake, **kw)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
        patch("youtube_pipeline.api.main._dispatch_resume") as mock_dispatch,
    ):
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        response = client.post(
            f"/api/v1/jobs/{job_id}/upload-assets?assemble=false",
            files={"file": ("assets.zip", buf.getvalue(), "application/zip")},
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "waiting_for_assets"
        assert body["all_scenes_ready"] is True
        mock_dispatch.assert_not_called()
        assert (run / "assets" / "scene_00.jpg").exists()
        assert (run / "assets" / "scene_01.jpg").exists()

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
    script = {
        "title": "Test Film",
        "full_script": " ".join(f"Narration {i}" for i in range(scenes)),
        "style": "cinematic",
        "scenes": [
            {
                "scene_id": i,
                "script_text": f"Narration {i} is short.",
                "visual_prompt": f"Prompt for scene {i}",
                "keywords": ["test"],
                "duration": 3.0,
            }
            for i in range(scenes)
        ],
    }
    (run / "script.json").write_text(json.dumps(script), encoding="utf-8")
    (run / "script_timed.json").write_text(json.dumps(script), encoding="utf-8")
    (run / "request.json").write_text(
        json.dumps(
            {
                "idea": "test",
                "style": "cinematic",
                "aspect_ratio": "16:9",
                "target_duration_seconds": 60,
                "max_scenes": scenes,
                "voice": "en-US-ChristopherNeural",
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
        # Create audio so studio exposes voiceover URL.
        (run / "audio" / "voiceover.mp3").write_bytes(b"x" * 2048)
        (run / "script.json").write_text(
            json.dumps({"title": "Test Film", "scenes": []}),
            encoding="utf-8",
        )

        ws = client.get(f"/api/v1/jobs/{job_id}/workspace")
        assert ws.status_code == 200
        body = ws.json()
        assert body["scene_count"] == 2
        assert body["scenes_ready"] == 0
        assert body["can_edit"] is True
        assert body["audio_url"]
        assert body["script_url"]
        assert "Prompt for scene 0" in body["clipboard_text"]
        assert body["scenes"][0]["visual_prompt"]

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


def test_ambience_endpoint_persists_and_reloads_workspace(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "job-hitl-ambience"
    run = _make_run(tmp_path, scenes=2)
    for name in ("script.json", "script_timed.json"):
        script = json.loads((run / name).read_text(encoding="utf-8"))
        script["scenes"][1]["ambience"] = "forest"
        script["scenes"][1]["sfx"] = [{"tag": "birds", "at": 0.4}]
        (run / name).write_text(json.dumps(script), encoding="utf-8")
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
        updated = client.post(
            f"/api/v1/jobs/{job_id}/scenes/1/ambience",
            json={"ambience": " Rain "},
        )
        assert updated.status_code == 200
        assert updated.json()["ambience"] == "rain"

        for name in ("script.json", "script_timed.json"):
            script = json.loads((run / name).read_text(encoding="utf-8"))
            assert script["scenes"][1]["ambience"] == "rain"

        workspace = client.get(f"/api/v1/jobs/{job_id}/workspace")
        assert workspace.status_code == 200
        scene = workspace.json()["scenes"][1]
        assert scene["ambience"] == "rain"
        assert scene["sfx"] == [{"tag": "birds", "at": 0.4}]

        published = json.loads(
            (tmp_path / "static" / job_id / "script.json").read_text(encoding="utf-8")
        )
        assert published["scenes"][1]["ambience"] == "rain"


def test_voiceover_upload_and_regenerate(tmp_path: Path) -> None:
    from youtube_pipeline.assets.hitl_workspace import save_voiceover_file
    from youtube_pipeline.models import SceneData, VideoScript
    from youtube_pipeline.audio.tts import TTSResult

    fake = _FakeRedis()
    job_id = "job-hitl-voice"
    run = _make_run(tmp_path, scenes=2)
    init_job(job_id, client=fake)  # type: ignore[arg-type]
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        run_dir=str(run),
        scene_count=2,
        client=fake,  # type: ignore[arg-type]
    )

    # Unit: custom upload retimes scenes.
    path = save_voiceover_file(run, b"v" * 4096, source_name="mine.mp3")
    assert path.name == "voiceover.mp3"
    assert (run / "voiceover_meta.json").exists()
    timed = json.loads((run / "script_timed.json").read_text(encoding="utf-8"))
    assert len(timed["scenes"]) == 2

    with (
        patch("youtube_pipeline.api.main.get_job", side_effect=lambda jid: get_job(jid, client=fake)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.update_job", side_effect=lambda jid, **kw: update_job(jid, client=fake, **kw)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
        patch("youtube_pipeline.audio.tts.AudioEngine") as mock_engine_cls,
    ):
        engine = MagicMock()
        mock_engine_cls.return_value = engine
        timed_script = VideoScript(
            title="Test Film",
            full_script="a b",
            style="cinematic",
            scenes=[
                SceneData(scene_id=0, script_text="Hello world here.", visual_prompt="v0", duration=1.0),
                SceneData(scene_id=1, script_text="Second line spoken.", visual_prompt="v1", duration=1.0),
            ],
        )
        out_audio = run / "audio" / "voiceover.mp3"
        out_audio.write_bytes(b"n" * 4096)
        engine.synthesize.return_value = TTSResult(
            audio_path=out_audio,
            duration_seconds=2.0,
            script=timed_script,
            timing={"total_duration": 2.0},
        )

        from youtube_pipeline.api.main import app

        client = TestClient(app)
        regen = client.post(
            f"/api/v1/jobs/{job_id}/voiceover",
            data={"voice": "en-US-JennyNeural"},
        )
        assert regen.status_code == 200
        body = regen.json()
        assert body["audio_ready"] is True
        assert body["current_voice"] == "en-US-JennyNeural"
        engine.synthesize.assert_called_once()
        assert engine.synthesize.call_args.kwargs["voice"] == "en-US-JennyNeural"

    with (
        patch("youtube_pipeline.api.main.get_job", side_effect=lambda jid: get_job(jid, client=fake)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.update_job", side_effect=lambda jid, **kw: update_job(jid, client=fake, **kw)),  # type: ignore[arg-type]
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
    ):
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        upload = client.post(
            f"/api/v1/jobs/{job_id}/voiceover",
            files={"file": ("custom.mp3", b"z" * 4096, "audio/mpeg")},
        )
        assert upload.status_code == 200
        assert (run / "audio" / "voiceover.mp3").exists()
        meta = json.loads((run / "voiceover_meta.json").read_text(encoding="utf-8"))
        assert meta["voice"] == "custom_upload"


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

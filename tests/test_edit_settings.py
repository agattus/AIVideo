from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.test_api import _FakeRedis
from youtube_pipeline.api.job_store import get_job, init_job, update_job
from youtube_pipeline.api.schemas import JobStatus
from youtube_pipeline.assets.edit_settings import load_edit_settings, save_edit_settings


def test_load_defaults_when_missing(tmp_path: Path) -> None:
    data = load_edit_settings(tmp_path)
    assert data["burn_captions"] is True
    assert data["caption_size"] == "m"
    assert data["caption_position"] == "bottom"


def test_save_roundtrip(tmp_path: Path) -> None:
    saved = save_edit_settings(
        tmp_path,
        {"burn_captions": False, "caption_size": "l", "caption_position": "lower_third"},
    )
    assert saved["burn_captions"] is False
    assert load_edit_settings(tmp_path)["caption_size"] == "l"


def test_rejects_invalid_size(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError):
        save_edit_settings(tmp_path, {"caption_size": "xl"})


def _api_job(tmp_path: Path) -> tuple[str, Path, _FakeRedis]:
    from youtube_pipeline.utils.files import write_json

    job_id = "job-edit-api"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    scenes = [
        {
            "scene_id": 0,
            "script_text": "First scene.",
            "visual_prompt": "first",
            "duration": 2.0,
        },
        {
            "scene_id": 1,
            "script_text": "Second scene.",
            "visual_prompt": "second",
            "duration": 3.0,
        },
    ]
    script = {
        "title": "Edit API",
        "style": "cinematic",
        "aspect_ratio": "16:9",
        "scenes": scenes,
        "full_script": "First scene. Second scene.",
    }
    write_json(run_dir / "script.json", script)
    write_json(run_dir / "script_timed.json", script)
    write_json(
        run_dir / "timing.json",
        {
            "scenes": [
                {"scene_id": 0, "start": 0.0, "end": 2.0, "duration": 2.0},
                {"scene_id": 1, "start": 2.0, "end": 5.0, "duration": 3.0},
            ]
        },
    )
    fake = _FakeRedis()
    init_job(job_id, client=fake)  # type: ignore[arg-type]
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        run_dir=str(run_dir),
        scene_count=2,
        client=fake,  # type: ignore[arg-type]
    )
    return job_id, run_dir, fake


def test_edit_settings_routes_and_workspace_field(tmp_path: Path) -> None:
    job_id, run_dir, fake = _api_job(tmp_path)

    with (
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch("youtube_pipeline.api.main.user_owns_job", return_value=True),
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"),
    ):
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        defaults = client.get(f"/api/v1/jobs/{job_id}/edit-settings")
        assert defaults.status_code == 200
        assert defaults.json() == {
            "burn_captions": True,
            "caption_size": "m",
            "caption_position": "bottom",
        }

        updated = client.put(
            f"/api/v1/jobs/{job_id}/edit-settings",
            json={
                "burn_captions": False,
                "caption_size": "l",
                "caption_position": "lower_third",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["burn_captions"] is False
        assert updated.json()["caption_size"] == "l"
        assert load_edit_settings(run_dir)["caption_position"] == "lower_third"

        workspace = client.get(f"/api/v1/jobs/{job_id}/workspace")
        assert workspace.status_code == 200
        assert workspace.json()["edit_settings"] == updated.json()


def test_reorder_scenes_route_persists_requested_order(tmp_path: Path) -> None:
    job_id, run_dir, fake = _api_job(tmp_path)

    with (
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch("youtube_pipeline.api.main.user_owns_job", return_value=True),
    ):
        from youtube_pipeline.api.main import app
        from youtube_pipeline.utils.files import read_json

        response = TestClient(app).post(
            f"/api/v1/jobs/{job_id}/scenes/reorder",
            json={"scene_ids": [1, 0]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "job_id": job_id,
        "scene_ids": [1, 0],
        "message": "Scenes reordered",
    }
    assert [scene["scene_id"] for scene in read_json(run_dir / "script.json")["scenes"]] == [1, 0]

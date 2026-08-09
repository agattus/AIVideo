"""API tests for quality review workspace fields, approve, regen, and assemble gate."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from tests.test_hitl_workspace import _FakeRedis, _make_run
from tests.test_auto_fill_images import _init_api_job
from youtube_pipeline.api.job_store import get_job
from youtube_pipeline.quality.models import (
    ImageReview,
    QualityReview,
    ScriptReview,
    TimingReview,
)
from youtube_pipeline.quality.store import save_quality_review
from youtube_pipeline.assets.hitl_workspace import save_scene_image


def _jpeg_bytes(color: tuple[int, int, int] = (40, 90, 140)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="JPEG")
    return buf.getvalue()


def _write_quality_review(
    run: Path,
    *,
    script: str = "needs_approval",
    timing: str = "pass",
    images: str = "pass",
) -> None:
    review = QualityReview(
        script_review=ScriptReview(status=script, issues=["weak_hook"] if script != "pass" else []),
        timing_review=TimingReview(status=timing),
        image_review=ImageReview(status=images, scenes={"0": {"score": 2}} if images != "pass" else {}),
    )
    save_quality_review(run, review)


def _ready_run(tmp_path: Path, scenes: int = 2) -> Path:
    run = _make_run(tmp_path, scenes=scenes)
    for scene_id in range(scenes):
        save_scene_image(run, scene_id, _jpeg_bytes(), source_name=f"scene_{scene_id}.jpg")
    return run


def _client_context(fake: _FakeRedis, tmp_path: Path):
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        )
    )
    stack.enter_context(patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path / "static"))
    stack.enter_context(
        patch(
            "youtube_pipeline.quality.image_review.maybe_run_image_quality_gate",
            return_value=None,
        )
    )
    return stack


def test_workspace_includes_quality_review_and_assemble_allowed(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "quality-workspace"
    run = _make_run(tmp_path, scenes=2)
    _write_quality_review(run, script="pass", timing="pass", images="pass")
    _init_api_job(fake, job_id, run, scenes=2)

    with _client_context(fake, tmp_path):
        from youtube_pipeline.api.main import app

        response = TestClient(app).get(f"/api/v1/jobs/{job_id}/workspace")

    assert response.status_code == 200
    body = response.json()
    assert body["assemble_allowed"] is True
    assert body["quality_review"]["script_review"]["status"] == "pass"
    assert body["quality_review"]["timing_review"]["status"] == "pass"
    assert body["quality_review"]["image_review"]["status"] == "pass"


def test_workspace_assemble_allowed_false_when_stage_pending(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "quality-pending"
    run = _make_run(tmp_path, scenes=1)
    _init_api_job(fake, job_id, run, scenes=1)

    with _client_context(fake, tmp_path):
        from youtube_pipeline.api.main import app

        response = TestClient(app).get(f"/api/v1/jobs/{job_id}/workspace")

    assert response.status_code == 200
    assert response.json()["assemble_allowed"] is False


def test_approve_quality_stage_sets_overridden(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "quality-approve"
    run = _make_run(tmp_path, scenes=1)
    _write_quality_review(run, script="needs_approval", timing="pass", images="pass")
    _init_api_job(fake, job_id, run, scenes=1)

    with _client_context(fake, tmp_path):
        from youtube_pipeline.api.main import app

        response = TestClient(app).post(
            f"/api/v1/jobs/{job_id}/quality/approve",
            json={"stage": "script"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "script"
    assert body["assemble_allowed"] is True
    assert body["quality_review"]["script_review"]["status"] == "overridden"
    assert body["quality_review"]["approvals"]["script"] is True
    persisted = json.loads((run / "quality_review.json").read_text(encoding="utf-8"))
    assert persisted["script_review"]["status"] == "overridden"
    assert persisted["approvals"]["script"] is True


def test_assemble_returns_409_when_quality_gate_blocks(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "quality-assemble-block"
    run = _ready_run(tmp_path, scenes=2)
    _write_quality_review(run, script="needs_approval", timing="pass", images="pass")
    _init_api_job(fake, job_id, run, scenes=2)

    with _client_context(fake, tmp_path), patch(
        "youtube_pipeline.api.main._dispatch_resume"
    ) as dispatch:
        from youtube_pipeline.api.main import app

        response = TestClient(app).post(f"/api/v1/jobs/{job_id}/assemble")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["assemble_allowed"] is False
    assert detail["quality_review"]["script_review"]["status"] == "needs_approval"
    dispatch.assert_not_called()


def test_regen_script_endpoint_calls_helper(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "quality-regen-script"
    run = _make_run(tmp_path, scenes=2)
    _init_api_job(fake, job_id, run, scenes=2)

    with _client_context(fake, tmp_path), patch(
        "youtube_pipeline.api.main.regenerate_script_with_quality_gate",
        return_value=ScriptReview(status="pass"),
    ) as regen:
        from youtube_pipeline.api.main import app

        response = TestClient(app).post(f"/api/v1/jobs/{job_id}/quality/regen-script")

    assert response.status_code == 200
    regen.assert_called_once()
    assert response.json()["quality_review"]["script_review"]["status"] == "pass"


def test_regen_images_endpoint_regenerates_failing_scenes(tmp_path: Path) -> None:
    fake = _FakeRedis()
    job_id = "quality-regen-images"
    run = _ready_run(tmp_path, scenes=2)
    _write_quality_review(run, script="pass", timing="pass", images="needs_approval")
    _init_api_job(fake, job_id, run, scenes=2)

    with _client_context(fake, tmp_path), patch(
        "youtube_pipeline.api.main.regenerate_weak_scene_images",
        return_value=(
            ImageReview(status="pass", scenes={"0": {"score": 4}, "1": {"score": 4}}),
            [0],
        ),
    ) as regen:
        from youtube_pipeline.api.main import app

        response = TestClient(app).post(f"/api/v1/jobs/{job_id}/quality/regen-images")

    assert response.status_code == 200
    regen.assert_called_once()
    assert response.json()["assemble_allowed"] is True
    assert response.json()["quality_review"]["image_review"]["status"] == "pass"

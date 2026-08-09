"""End-to-end smoke: mocked quality pass unlocks assemble; fail path needs override."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from config.settings import LLMProvider, Settings
from tests.test_auto_fill_images import _init_api_job
from tests.test_hitl_workspace import _FakeRedis
from tests.test_orchestrator import (
    FakeAssetService,
    FakeAudioEngine,
    FakeScriptEngine,
)
from youtube_pipeline.api.job_store import get_job
from youtube_pipeline.assets.hitl_workspace import save_bgm_file, save_scene_image, workspace_status
from youtube_pipeline.models import PipelineRequest, VisualStyle
from youtube_pipeline.orchestrator import VideoPipelineOrchestrator
from youtube_pipeline.quality.models import ScriptReview


RUBRIC_KEYS = (
    "idea_fit",
    "hook",
    "ending",
    "pacing_emotion",
    "format_rules",
)


def _jpeg_bytes(color: tuple[int, int, int] = (40, 90, 140)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="JPEG")
    return buf.getvalue()


def _passing_critique(_script, _request) -> ScriptReview:
    return ScriptReview(
        status="pass",
        scores={key: 4 for key in RUBRIC_KEYS},
    )


def _failing_critique(_script, _request) -> ScriptReview:
    return ScriptReview(
        status="needs_approval",
        scores={key: 2 for key in RUBRIC_KEYS},
        issues=["low_score:hook"],
    )


def _run_phase1(
    tmp_path: Path,
    *,
    critique_fn,
) -> Path:
    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        gemini_api_key="offline-test-key",
        llm_provider=LLMProvider.GEMINI,
        _env_file=None,
    )
    settings.ensure_directories()
    orchestrator = VideoPipelineOrchestrator(
        settings,
        script_engine=FakeScriptEngine(),  # type: ignore[arg-type]
        audio_engine=FakeAudioEngine(),  # type: ignore[arg-type]
        asset_service=FakeAssetService(),  # type: ignore[arg-type]
        video_composer=SimpleNamespace(),  # type: ignore[arg-type]
        script_critique=critique_fn,
        script_rewrite=lambda script, _request, _review: script,
    )
    result = orchestrator.run(
        PipelineRequest(
            idea="A lighthouse keeper hears an impossible storm",
            style=VisualStyle.CINEMATIC,
            target_duration_seconds=None,
            output_name="quality-e2e-smoke",
        )
    )
    return Path(result.metadata["run_dir"])


def _seed_ready_assets(run: Path, *, scenes: int = 2) -> None:
    for scene_id in range(scenes):
        save_scene_image(run, scene_id, _jpeg_bytes(), source_name=f"scene_{scene_id}.jpg")
    save_bgm_file(run, b"z" * 4096, source_name="bed.mp3")


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
    return stack


@pytest.fixture
def passing_run(tmp_path: Path) -> Path:
    run = _run_phase1(tmp_path, critique_fn=_passing_critique)
    _seed_ready_assets(run, scenes=2)
    return run


def test_quality_e2e_pass_path_unlocks_assemble(passing_run: Path) -> None:
    with patch(
        "youtube_pipeline.quality.image_review.score_scene_aptness",
        return_value=4,
    ):
        workspace = workspace_status(passing_run, job_id="quality-e2e-pass")

    assert workspace["all_scenes_ready"] is True
    assert workspace["bgm_ready"] is True
    assert workspace["quality_review"]["script_review"]["status"] == "pass"
    assert workspace["quality_review"]["timing_review"]["status"] == "pass"
    assert workspace["quality_review"]["image_review"]["status"] == "pass"
    assert workspace["assemble_allowed"] is True


def test_quality_e2e_fail_path_requires_override_before_assemble(
    tmp_path: Path,
) -> None:
    run = _run_phase1(tmp_path, critique_fn=_failing_critique)
    _seed_ready_assets(run, scenes=2)

    with patch(
        "youtube_pipeline.quality.image_review.score_scene_aptness",
        return_value=4,
    ):
        blocked = workspace_status(run, job_id="quality-e2e-fail")

    assert blocked["assemble_allowed"] is False
    assert blocked["quality_review"]["script_review"]["status"] == "needs_approval"

    fake = _FakeRedis()
    job_id = "quality-e2e-fail"
    _init_api_job(fake, job_id, run, scenes=2)

    with _client_context(fake, tmp_path), patch(
        "youtube_pipeline.api.main._dispatch_resume",
        return_value="thread",
    ) as dispatch:
        from youtube_pipeline.api.main import app

        client = TestClient(app)

        assemble_blocked = client.post(f"/api/v1/jobs/{job_id}/assemble")
        assert assemble_blocked.status_code == 409

        approve = client.post(
            f"/api/v1/jobs/{job_id}/quality/approve",
            json={"stage": "script"},
        )
        assert approve.status_code == 200
        assert approve.json()["assemble_allowed"] is True
        assert approve.json()["quality_review"]["script_review"]["status"] == "overridden"

        assemble_ok = client.post(f"/api/v1/jobs/{job_id}/assemble")
        assert assemble_ok.status_code == 202
        dispatch.assert_called_once_with(job_id, zip_path=None)

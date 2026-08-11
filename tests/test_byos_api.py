"""API acceptance for bring-your-own-script create payload."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from youtube_pipeline.api.main import app
from youtube_pipeline.models import (
    PipelineRequest,
    SceneData,
    VideoFormat,
    VideoScript,
    VisualStyle,
)
from youtube_pipeline.quality.models import ScriptReview
from youtube_pipeline.quality.script_review import run_script_quality_gate


def test_generate_rejects_provided_without_script():
    with patch("youtube_pipeline.api.main._dispatch_job", return_value="thread"):
        res = TestClient(app).post(
            "/api/v1/generate",
            json={
                "idea": "something long enough",
                "script_source": "provided",
                "style": "cinematic",
                "duration": 45,
                "language": "en",
                "voice": "en-US-JennyNeural",
                "format": "narrative",
            },
        )
    assert res.status_code == 422


def test_generate_accepts_provided_plain_text():
    captured: dict = {}

    def fake_dispatch(job_id: str, request_data: dict) -> str:
        captured["job_id"] = job_id
        captured["request"] = request_data
        return "thread"

    with patch("youtube_pipeline.api.main._dispatch_job", side_effect=fake_dispatch):
        res = TestClient(app).post(
            "/api/v1/generate",
            json={
                "idea": "",
                "script_source": "provided",
                "user_script_text": "First beat spoken.\n\nSecond beat spoken.",
                "style": "cinematic",
                "duration": 45,
                "language": "en",
                "voice": "en-US-JennyNeural",
                "format": "narrative",
                "aspect_ratio": "16:9",
            },
        )
    assert res.status_code == 202, res.text
    assert captured["request"]["script_source"] == "provided"
    assert "First beat spoken" in captured["request"]["user_script_text"]
    assert captured["request"]["idea"]


def test_pipeline_request_provided_idea_optional():
    req = PipelineRequest(
        idea="",
        script_source="provided",
        user_script_text="Hello world narration for a short film.",
        format=VideoFormat.NARRATIVE,
        style=VisualStyle.CINEMATIC,
        max_scenes=4,
    )
    assert req.idea
    assert req.script_source == "provided"


def test_run_script_quality_gate_allow_rewrite_default_still_rewrites():
    original = VideoScript(
        title="T",
        full_script="a b",
        style="cinematic",
        scenes=[
            SceneData(scene_id=0, script_text="a", visual_prompt="v0"),
            SceneData(scene_id=1, script_text="b", visual_prompt="v1"),
        ],
    )
    rewritten = original.model_copy(
        update={
            "scenes": [
                SceneData(scene_id=0, script_text="CHANGED", visual_prompt="v0"),
                SceneData(scene_id=1, script_text="b", visual_prompt="v1"),
            ]
        }
    )

    def critique(script, request):
        del request
        low = script.scenes[0].script_text != "CHANGED"
        return ScriptReview(
            status="needs_approval" if low else "pass",
            scores={
                "idea_fit": 2 if low else 5,
                "hook": 2 if low else 5,
                "ending": 2 if low else 5,
                "pacing_emotion": 2 if low else 5,
                "format_rules": 2 if low else 5,
            },
            issues=["x"] if low else [],
        )

    out, review = run_script_quality_gate(
        original,
        PipelineRequest(idea="abc idea", max_scenes=4),
        critique_fn=critique,
        rewrite_fn=lambda s, r, rev: rewritten,
        allow_rewrite=True,
    )
    assert out.scenes[0].script_text == "CHANGED"
    assert review.retries == 1

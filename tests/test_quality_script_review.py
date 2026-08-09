from __future__ import annotations

import json

from youtube_pipeline.models import PipelineRequest, SceneData, VideoScript
from youtube_pipeline.quality.models import ScriptReview


RUBRIC_KEYS = {
    "idea_fit",
    "hook",
    "ending",
    "pacing_emotion",
    "format_rules",
}


def _script(title: str = "Original") -> VideoScript:
    return VideoScript(
        title=title,
        full_script="A warning arrives. The truth changes everything.",
        style="cinematic",
        scenes=[
            SceneData(
                scene_id=0,
                script_text="A warning arrives.",
                visual_prompt="A sealed warning on a dark desk",
            ),
            SceneData(
                scene_id=1,
                script_text="The truth changes everything.",
                visual_prompt="A stunned witness in dramatic light",
            ),
        ],
    )


def _request() -> PipelineRequest:
    return PipelineRequest(idea="A mysterious warning changes history")


def _review(score: int, *, issue: str = "") -> ScriptReview:
    return ScriptReview(
        status="pass" if score >= 3 else "needs_approval",
        scores={key: score for key in RUBRIC_KEYS},
        issues=[issue] if issue else [],
    )


def test_critique_script_parses_complete_passing_rubric() -> None:
    from youtube_pipeline.quality.script_review import critique_script

    def llm_call(user_prompt: str, *, system_prompt: str) -> str:
        assert "A mysterious warning changes history" in user_prompt
        assert "A warning arrives." in user_prompt
        assert RUBRIC_KEYS == {
            key
            for key in RUBRIC_KEYS
            if key in system_prompt
        }
        return json.dumps(
            {
                "scores": {
                    "idea_fit": 5,
                    "hook": 4,
                    "ending": 3,
                    "pacing_emotion": 4,
                    "format_rules": 5,
                },
                "issues": [],
            }
        )

    review = critique_script(_script(), _request(), llm_call=llm_call)

    assert review.status == "pass"
    assert review.scores == {
        "idea_fit": 5,
        "hook": 4,
        "ending": 3,
        "pacing_emotion": 4,
        "format_rules": 5,
    }
    assert review.issues == []


def test_critique_script_fails_when_rubric_score_is_missing() -> None:
    from youtube_pipeline.quality.script_review import critique_script

    def llm_call(user_prompt: str, *, system_prompt: str) -> str:
        del user_prompt, system_prompt
        return json.dumps(
            {
                "scores": {
                    "idea_fit": 5,
                    "hook": 4,
                    "ending": 4,
                    "pacing_emotion": 4,
                },
                "issues": [],
            }
        )

    review = critique_script(_script(), _request(), llm_call=llm_call)

    assert review.status == "needs_approval"
    assert review.scores == {
        "idea_fit": 5,
        "hook": 4,
        "ending": 4,
        "pacing_emotion": 4,
    }
    assert "missing_score:format_rules" in review.issues


def test_critique_script_reports_low_score_as_failure_issue() -> None:
    from youtube_pipeline.quality.script_review import critique_script

    def llm_call(user_prompt: str, *, system_prompt: str) -> str:
        del user_prompt, system_prompt
        return json.dumps(
            {
                "scores": {
                    "idea_fit": 5,
                    "hook": 2,
                    "ending": 4,
                    "pacing_emotion": 4,
                    "format_rules": 5,
                },
                "issues": [],
            }
        )

    review = critique_script(_script(), _request(), llm_call=llm_call)

    assert review.status == "needs_approval"
    assert any("low_score" in issue for issue in review.issues)


def test_critique_script_reports_parse_failure() -> None:
    from youtube_pipeline.quality.script_review import critique_script

    review = critique_script(
        _script(),
        _request(),
        llm_call=lambda user_prompt, *, system_prompt: "not json",
    )

    assert review.status == "needs_approval"
    assert review.scores == {}
    assert review.issues == ["critique_parse_error"]


def test_rewrite_script_once_generates_from_critique_feedback() -> None:
    from youtube_pipeline.quality.script_review import rewrite_script_once

    rewritten = _script("Rewritten")
    received_idea = ""

    def generate_fn(request: PipelineRequest) -> VideoScript:
        nonlocal received_idea
        received_idea = request.idea
        return rewritten

    result = rewrite_script_once(
        _script(),
        _request(),
        _review(2, issue="Hook is too slow"),
        generate_fn=generate_fn,
    )

    assert result is rewritten
    assert "A mysterious warning changes history" in received_idea
    assert "A warning arrives." in received_idea
    assert "Hook is too slow" in received_idea


def test_run_script_quality_gate_retries_once_then_needs_approval() -> None:
    from youtube_pipeline.quality.script_review import run_script_quality_gate

    original = _script()
    rewritten = _script("Rewritten")
    reviews = iter(
        [
            _review(2, issue="Weak opening"),
            _review(2, issue="Ending remains flat"),
        ]
    )
    rewrite_calls = 0

    def critique_fn(script: VideoScript, request: PipelineRequest) -> ScriptReview:
        del script, request
        return next(reviews)

    def rewrite_fn(
        script: VideoScript,
        request: PipelineRequest,
        critique: ScriptReview,
    ) -> VideoScript:
        nonlocal rewrite_calls
        del script, request, critique
        rewrite_calls += 1
        return rewritten

    result_script, review = run_script_quality_gate(
        original,
        _request(),
        critique_fn=critique_fn,
        rewrite_fn=rewrite_fn,
    )

    assert result_script is rewritten
    assert review.status == "needs_approval"
    assert review.retries == 1
    assert review.issues == ["Ending remains flat"]
    assert rewrite_calls == 1


def test_run_script_quality_gate_passes_after_rewrite() -> None:
    from youtube_pipeline.quality.script_review import run_script_quality_gate

    rewritten = _script("Rewritten")
    reviews = iter([_review(2, issue="Weak opening"), _review(4)])

    def critique_fn(script: VideoScript, request: PipelineRequest) -> ScriptReview:
        del script, request
        return next(reviews)

    def rewrite_fn(
        script: VideoScript,
        request: PipelineRequest,
        critique: ScriptReview,
    ) -> VideoScript:
        del script, request, critique
        return rewritten

    result_script, review = run_script_quality_gate(
        _script(),
        _request(),
        critique_fn=critique_fn,
        rewrite_fn=rewrite_fn,
    )

    assert result_script is rewritten
    assert review.status == "pass"
    assert review.retries == 1


def test_run_script_quality_gate_passes_without_rewrite() -> None:
    from youtube_pipeline.quality.script_review import run_script_quality_gate

    original = _script()

    def unexpected_rewrite(
        script: VideoScript,
        request: PipelineRequest,
        critique: ScriptReview,
    ) -> VideoScript:
        raise AssertionError("passing scripts must not be rewritten")

    result_script, review = run_script_quality_gate(
        original,
        _request(),
        critique_fn=lambda script, request: _review(3),
        rewrite_fn=unexpected_rewrite,
    )

    assert result_script is original
    assert review.status == "pass"
    assert review.retries == 0

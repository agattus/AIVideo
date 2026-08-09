"""LLM-backed script critique and single-rewrite quality gate."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from youtube_pipeline.models import PipelineRequest, VideoScript
from youtube_pipeline.quality.models import ScriptReview, StageReview


RUBRIC_KEYS = (
    "idea_fit",
    "hook",
    "ending",
    "pacing_emotion",
    "format_rules",
)
PASSING_SCORE = 3

LlmCall = Callable[..., str]
GenerateFn = Callable[[PipelineRequest], VideoScript]
CritiqueFn = Callable[[VideoScript, PipelineRequest], StageReview]
RewriteFn = Callable[[VideoScript, PipelineRequest, StageReview], VideoScript]


def _scores_pass(scores: Mapping[str, int]) -> bool:
    return all(
        key in scores
        and isinstance(scores[key], int)
        and not isinstance(scores[key], bool)
        and scores[key] >= PASSING_SCORE
        for key in RUBRIC_KEYS
    )


def _critique_system_prompt() -> str:
    rubric = "\n".join(f"- {key}: integer score from 1 to 5" for key in RUBRIC_KEYS)
    return (
        "You are a strict short-form video script editor. Evaluate the supplied "
        "script against every rubric item below.\n"
        f"{rubric}\n"
        'Return only JSON in this shape: {"scores": {"idea_fit": 1, "hook": 1, '
        '"ending": 1, "pacing_emotion": 1, "format_rules": 1}, '
        '"issues": ["specific actionable problem"]}.'
    )


def _critique_user_prompt(script: VideoScript, request: PipelineRequest) -> str:
    return (
        f"Original video idea: {request.idea}\n"
        f"Requested format: {request.format.value}\n"
        f"Requested duration: {request.target_duration_seconds}\n"
        "Script JSON:\n"
        f"{script.model_dump_json()}"
    )


def _parse_critique(raw: str) -> tuple[dict[str, int], list[str]]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Critique root must be an object")

    raw_scores = payload.get("scores")
    raw_issues = payload.get("issues", [])
    if not isinstance(raw_scores, dict) or not isinstance(raw_issues, list):
        raise ValueError("Critique scores and issues have invalid types")
    if any(not isinstance(issue, str) for issue in raw_issues):
        raise ValueError("Critique issues must be strings")

    scores: dict[str, int] = {}
    for key in RUBRIC_KEYS:
        if key not in raw_scores:
            continue
        score = raw_scores[key]
        if (
            not isinstance(score, int)
            or isinstance(score, bool)
            or not 1 <= score <= 5
        ):
            raise ValueError(f"Invalid score for {key}")
        scores[key] = score
    return scores, [issue.strip() for issue in raw_issues if issue.strip()]


def critique_script(
    script: VideoScript,
    request: PipelineRequest,
    *,
    llm_call: LlmCall,
) -> StageReview:
    """Critique a script with the five-item quality rubric."""
    raw = llm_call(
        _critique_user_prompt(script, request),
        system_prompt=_critique_system_prompt(),
    )
    try:
        scores, issues = _parse_critique(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ScriptReview(
            status="needs_approval",
            issues=["critique_parse_error"],
        )

    missing = [key for key in RUBRIC_KEYS if key not in scores]
    low = [key for key in RUBRIC_KEYS if key in scores and scores[key] < PASSING_SCORE]
    issues.extend(f"missing_score:{key}" for key in missing)
    issues.extend(f"low_score:{key}" for key in low)
    return ScriptReview(
        status="pass" if _scores_pass(scores) else "needs_approval",
        scores=scores,
        issues=issues,
    )


def rewrite_script_once(
    script: VideoScript,
    request: PipelineRequest,
    critique: StageReview,
    *,
    generate_fn: GenerateFn,
) -> VideoScript:
    """Generate one replacement script using the critique as explicit feedback."""
    feedback = {
        "scores": getattr(critique, "scores", {}),
        "issues": critique.issues,
    }
    rewrite_idea = (
        f"{request.idea}\n\n"
        "Rewrite the following existing video script once. Preserve the core idea "
        "and requested format, while fixing every critique item.\n"
        f"Critique JSON: {json.dumps(feedback, ensure_ascii=False)}\n"
        f"Existing script JSON: {script.model_dump_json()}"
    )
    rewrite_request = request.model_copy(update={"idea": rewrite_idea})
    return generate_fn(rewrite_request)


def run_script_quality_gate(
    script: VideoScript,
    request: PipelineRequest,
    *,
    critique_fn: CritiqueFn,
    rewrite_fn: RewriteFn,
) -> tuple[VideoScript, StageReview]:
    """Critique, rewrite at most once, then return the final script and review."""
    initial_review = critique_fn(script, request)
    initial_scores: dict[str, Any] = getattr(initial_review, "scores", {})
    if _scores_pass(initial_scores):
        final_review = ScriptReview(
            status="pass",
            scores=dict(initial_scores),
            issues=list(initial_review.issues),
            retries=0,
        )
        return script, final_review

    rewritten = rewrite_fn(script, request, initial_review)
    second_review = critique_fn(rewritten, request)
    second_scores: dict[str, Any] = getattr(second_review, "scores", {})
    final_review = ScriptReview(
        status="pass" if _scores_pass(second_scores) else "needs_approval",
        scores=dict(second_scores),
        issues=list(second_review.issues),
        retries=1,
    )
    return rewritten, final_review

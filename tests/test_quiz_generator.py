from __future__ import annotations

import json

import pytest

from config.settings import LLMProvider, Settings
from youtube_pipeline.models import PipelineRequest, QuizMode, VideoFormat
from youtube_pipeline.script_engine.generator import ScriptEngine


def test_quizverse_generate_expands_questions_into_reveal_beats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = ScriptEngine(
        Settings(
            gemini_api_key="gemini-test-key",
            llm_provider=LLMProvider.GEMINI,
        )
    )
    payload = {
        "title": "Greek Gods Quiz",
        "questions": [
            {
                "question": "Who is the king of the Greek gods?",
                "choices": ["Apollo", "Zeus"],
                "answer": "Zeus",
                "explain": "Zeus rules Olympus.",
            }
        ],
    }
    monkeypatch.setattr(engine, "_call_llm", lambda *args, **kwargs: json.dumps(payload))
    request = PipelineRequest(
        idea="Greek gods",
        format=VideoFormat.QUIZVERSE,
        quiz_mode=QuizMode.REVEAL,
        question_count=1,
        max_scenes=3,
    )

    script = engine.generate(request)

    assert script.format == "quizverse"
    assert script.quiz_mode == "reveal"
    assert [scene.beat_type.value for scene in script.scenes] == [
        "question",
        "timer",
        "reveal",
    ]
    assert script.full_script == (
        "Who is the king of the Greek gods? Choices: Apollo, Zeus. "
        "Zeus. Zeus rules Olympus."
    )


def test_comment_prompts_require_answers_for_studio_key() -> None:
    from youtube_pipeline.script_engine.quiz_prompts import (
        build_quiz_system_prompt,
        build_quiz_user_prompt,
    )

    system_prompt = build_quiz_system_prompt(QuizMode.COMMENT, "en", 2)
    user_prompt = build_quiz_user_prompt("Greek gods", QuizMode.COMMENT, 2, "en")

    for prompt in (system_prompt, user_prompt):
        assert "exactly 2" in prompt
        assert "answer" in prompt
        assert "explain" in prompt
    assert "studio" in system_prompt.lower()


def test_quiz_schema_requires_question_answer_and_explanation() -> None:
    from youtube_pipeline.script_engine.schema import QUIZ_SCRIPT_SCHEMA

    assert QUIZ_SCRIPT_SCHEMA["required"] == ["title", "questions"]
    question_schema = QUIZ_SCRIPT_SCHEMA["properties"]["questions"]["items"]
    assert question_schema["required"] == ["question", "answer", "explain"]
    assert question_schema["properties"]["choices"]["minItems"] == 2
    assert question_schema["properties"]["choices"]["maxItems"] == 4

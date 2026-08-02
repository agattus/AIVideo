"""Prompt builders for structured Quizverse question generation."""

from __future__ import annotations

import json

from youtube_pipeline.models import QuizMode
from youtube_pipeline.script_engine.schema import QUIZ_SCRIPT_SCHEMA


def build_quiz_system_prompt(
    mode: QuizMode,
    language: str,
    question_count: int,
) -> str:
    """Build the format-specific system instruction for Quizverse."""
    mode_instruction = (
        "Answers will not appear in the video, but answer and explain are still required "
        "for the private studio answer key."
        if mode == QuizMode.COMMENT
        else "Answers and explanations will be revealed after each timer."
    )
    return (
        "You create accurate, engaging quiz questions as strict JSON. "
        f"Return exactly {question_count} questions in language {language}. "
        "Every item must contain question, answer, and explain. "
        "Choices are optional; when included, use 2 to 4. "
        "Keep each explanation to 25 words or fewer. "
        f"{mode_instruction} Return only JSON matching this schema: "
        f"{json.dumps(QUIZ_SCRIPT_SCHEMA, separators=(',', ':'))}"
    )


def build_quiz_user_prompt(
    idea: str,
    mode: QuizMode,
    question_count: int,
    language: str,
) -> str:
    """Build the user prompt for one Quizverse request."""
    return (
        f"Create exactly {question_count} {mode.value}-mode quiz questions about: {idea}\n"
        f"Write the title, question, choices, answer, and explain fields in {language}. "
        "Include answer and explain for every question, including comment mode. "
        "Return a single JSON object with title and questions."
    )

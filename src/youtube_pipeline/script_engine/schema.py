"""JSON Schema helpers for OpenAI Structured Outputs → VideoScript."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from youtube_pipeline.models import AMBIENCE_TAGS, ONESHOT_TAGS


class _QuizQuestionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1)
    choices: list[str] = Field(default_factory=list, min_length=2, max_length=4)
    answer: str = Field(min_length=1)
    explain: str = Field(min_length=1, json_schema_extra={"maxWords": 25})

    @field_validator("choices")
    @classmethod
    def _validate_choices(cls, choices: list[str]) -> list[str]:
        cleaned = [choice.strip() for choice in choices]
        if any(not choice for choice in cleaned):
            raise ValueError("choices must contain non-empty strings")
        return cleaned

    @field_validator("explain")
    @classmethod
    def _limit_explanation_words(cls, explain: str) -> str:
        if len(explain.split()) > 25:
            raise ValueError("explain must contain at most 25 words")
        return explain


class _QuizScriptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1)
    questions: list[_QuizQuestionPayload] = Field(min_length=1)


_quiz_model_schema = _QuizScriptPayload.model_json_schema()
_question_schema = _quiz_model_schema.pop("$defs")["_QuizQuestionPayload"]
QUIZ_SCRIPT_SCHEMA: dict[str, Any] = deepcopy(_quiz_model_schema)
QUIZ_SCRIPT_SCHEMA["properties"]["questions"]["items"] = _question_schema


def validate_quiz_script_payload(
    payload: dict[str, Any],
    *,
    question_count: int,
) -> dict[str, Any]:
    """Validate and normalize generated Quizverse JSON against its schema model."""
    validated = _QuizScriptPayload.model_validate(payload)
    if len(validated.questions) != question_count:
        raise ValueError(
            f"Expected exactly {question_count} quiz questions, "
            f"got {len(validated.questions)}"
        )
    return validated.model_dump()


def video_script_json_schema() -> dict[str, Any]:
    """Strict JSON Schema accepted by OpenAI ``json_schema`` response_format.

    Kept hand-authored (rather than raw ``model_json_schema()``) so every object
    sets ``additionalProperties: false`` and lists all properties as required —
    constraints OpenAI Structured Outputs enforces in strict mode.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "full_script": {"type": "string", "minLength": 1},
            "style": {"type": "string", "minLength": 1},
            "scenes": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "scene_id": {"type": "integer", "minimum": 0},
                        "script_text": {"type": "string", "minLength": 1},
                        "visual_prompt": {"type": "string", "minLength": 1},
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "duration": {"type": "number", "minimum": 0},
                        "ambience": {
                            "type": "string",
                            "enum": sorted(AMBIENCE_TAGS),
                            "default": "none",
                        },
                        "sfx": {
                            "type": "array",
                            "maxItems": 2,
                            "default": [],
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "tag": {
                                        "type": "string",
                                        "enum": sorted(ONESHOT_TAGS),
                                    },
                                    "at": {
                                        "type": "number",
                                        "minimum": 0.15,
                                        "maximum": 0.85,
                                    },
                                },
                                "required": ["tag", "at"],
                            },
                        },
                    },
                    "required": [
                        "scene_id",
                        "script_text",
                        "visual_prompt",
                        "keywords",
                        "duration",
                        "ambience",
                        "sfx",
                    ],
                },
            },
        },
        "required": ["title", "full_script", "style", "scenes"],
    }


def openai_response_format() -> dict[str, Any]:
    """OpenAI chat ``response_format`` using strict Structured Outputs."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "video_script",
            "strict": True,
            "schema": video_script_json_schema(),
        },
    }

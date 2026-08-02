"""JSON Schema helpers for OpenAI Structured Outputs → VideoScript."""

from __future__ import annotations

from typing import Any

from youtube_pipeline.models import AMBIENCE_TAGS, ONESHOT_TAGS


QUIZ_SCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "questions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "question": {"type": "string", "minLength": 1},
                    "choices": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 4,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "answer": {"type": "string", "minLength": 1},
                    "explain": {"type": "string", "minLength": 1},
                },
                "required": ["question", "answer", "explain"],
            },
        },
    },
    "required": ["title", "questions"],
}


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

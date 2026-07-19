"""JSON Schema helpers for OpenAI Structured Outputs → VideoScript."""

from __future__ import annotations

from typing import Any


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
                    },
                    "required": [
                        "scene_id",
                        "script_text",
                        "visual_prompt",
                        "keywords",
                        "duration",
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

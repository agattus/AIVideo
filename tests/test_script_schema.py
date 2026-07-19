from __future__ import annotations

from youtube_pipeline.models import VideoScript
from youtube_pipeline.script_engine.schema import openai_response_format, video_script_json_schema


def test_json_schema_is_strict() -> None:
    schema = video_script_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"title", "full_script", "style", "scenes"}
    scene_schema = schema["properties"]["scenes"]["items"]
    assert scene_schema["additionalProperties"] is False
    assert "script_text" in scene_schema["required"]


def test_openai_response_format_wrapper() -> None:
    fmt = openai_response_format()
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["name"] == "video_script"


def test_schema_compatible_payload_validates() -> None:
    payload = {
        "title": "Black Holes",
        "full_script": "Space bends. Light follows.",
        "style": "cinematic",
        "scenes": [
            {
                "scene_id": 0,
                "script_text": "Space bends.",
                "visual_prompt": "Warped starlight around a dark sphere",
                "keywords": ["black hole", "space"],
                "duration": 0,
            },
            {
                "scene_id": 1,
                "script_text": "Light follows.",
                "visual_prompt": "Photons tracing curved paths",
                "keywords": ["light", "gravity"],
                "duration": 0,
            },
        ],
    }
    script = VideoScript.model_validate(payload)
    assert len(script.scenes) == 2
    assert script.style == "cinematic"

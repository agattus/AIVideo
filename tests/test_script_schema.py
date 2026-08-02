from __future__ import annotations

from config.settings import LLMProvider, Settings
from youtube_pipeline.models import AMBIENCE_TAGS, ONESHOT_TAGS, PipelineRequest, VideoScript
from youtube_pipeline.script_engine.generator import ScriptEngine
from youtube_pipeline.script_engine.schema import openai_response_format, video_script_json_schema


def test_json_schema_is_strict() -> None:
    schema = video_script_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"title", "full_script", "style", "scenes"}
    scene_schema = schema["properties"]["scenes"]["items"]
    assert scene_schema["additionalProperties"] is False
    assert set(scene_schema["required"]) == {
        "scene_id",
        "script_text",
        "visual_prompt",
        "keywords",
        "duration",
        "ambience",
        "sfx",
    }
    assert scene_schema["properties"]["ambience"] == {
        "type": "string",
        "enum": sorted(AMBIENCE_TAGS),
        "default": "none",
    }
    sfx_schema = scene_schema["properties"]["sfx"]
    assert sfx_schema["type"] == "array"
    assert sfx_schema["maxItems"] == 2
    assert sfx_schema["default"] == []
    assert sfx_schema["items"]["additionalProperties"] is False
    assert set(sfx_schema["items"]["required"]) == {"tag", "at"}
    assert sfx_schema["items"]["properties"]["tag"]["enum"] == sorted(ONESHOT_TAGS)


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
                "ambience": "none",
                "sfx": [],
            },
            {
                "scene_id": 1,
                "script_text": "Light follows.",
                "visual_prompt": "Photons tracing curved paths",
                "keywords": ["light", "gravity"],
                "duration": 0,
                "ambience": "none",
                "sfx": [],
            },
        ],
    }
    script = VideoScript.model_validate(payload)
    assert len(script.scenes) == 2
    assert script.style == "cinematic"


def test_script_parser_preserves_llm_tags_and_fills_missing_tags() -> None:
    engine = ScriptEngine(
        Settings(
            gemini_api_key="test-key",
            llm_provider=LLMProvider.GEMINI,
        )
    )
    request = PipelineRequest(
        idea="A storm enters a forest cabin",
        max_scenes=2,
        target_duration_seconds=16,
    )
    payload = {
        "title": "The Storm",
        "scenes": [
            {
                "scene_id": 0,
                "narration": "Thunder rolls through the rain.",
                "visual_prompt": "Lightning above a flooded road",
                "ambience": "none",
                "sfx": [],
            },
            {
                "scene_id": 1,
                "narration": "The cabin door opens.",
                "visual_prompt": "Dark forest cabin doorway",
                "ambience": "forest",
                "sfx": [{"tag": "door", "at": 0.5}],
            },
        ],
    }

    script = engine._to_video_script(payload, request, target_scenes=2)

    assert script.scenes[0].ambience == "rain"
    assert [cue.model_dump() for cue in script.scenes[0].sfx] == [
        {"tag": "thunder", "at": 0.45}
    ]
    assert script.scenes[1].ambience == "forest"
    assert [cue.model_dump() for cue in script.scenes[1].sfx] == [
        {"tag": "door", "at": 0.5}
    ]

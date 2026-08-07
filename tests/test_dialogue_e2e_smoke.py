"""Offline smoke coverage for dialogue generation, captions, and create UX."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from config.settings import LLMProvider, Settings
from youtube_pipeline.api.main import app
from youtube_pipeline.models import AspectRatio, PipelineRequest, VideoFormat
from youtube_pipeline.script_engine.generator import ScriptEngine
from youtube_pipeline.video.text_clips import scene_caption_timeline


def _dialogue_payload() -> dict:
    cast = [
        {"id": "ravi", "name": "Ravi", "gender_hint": "male"},
        {"id": "maya", "name": "Maya", "gender_hint": "female"},
        {"id": "guard", "name": "Guard", "gender_hint": "male"},
    ]
    lines = [
        {"speaker_id": cast[index % len(cast)]["id"], "text": f"Spoken line {index}."}
        for index in range(8)
    ]
    return {
        "title": "The Open Gate",
        "cast": cast,
        "lines": lines,
        "visual_beats": [
            {
                "line_start": start,
                "line_end": start + 1,
                "visual_prompt": f"Gate conversation beat {start // 2 + 1}",
            }
            for start in range(0, 8, 2)
        ],
    }


@pytest.fixture
def generated_dialogue(monkeypatch: pytest.MonkeyPatch):
    engine = ScriptEngine(
        Settings(
            gemini_api_key="offline-test-key",
            llm_provider=LLMProvider.GEMINI,
            _env_file=None,
        )
    )
    payload = _dialogue_payload()
    monkeypatch.setattr(
        engine,
        "_call_llm",
        lambda _user_prompt, *, system_prompt: json.dumps(payload),
    )

    return engine.generate(
        PipelineRequest(
            idea="Three strangers debate whether to enter an open gate",
            format=VideoFormat.DIALOGUE,
            language="en",
        )
    )


def test_mocked_llm_dialogue_path_builds_shot_synced_scenes_and_voice_map(
    generated_dialogue,
) -> None:
    script = generated_dialogue

    assert script.format == "dialogue"
    assert len(script.scenes) == len(script.lines)
    assert [(scene.line_start, scene.line_end) for scene in script.scenes] == [
        (0, 0),
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (6, 6),
        (7, 7),
    ]
    assert [
        scene.visual_prompt.split(". Focus on ", maxsplit=1)[0]
        for scene in script.scenes
    ] == [
        "Gate conversation beat 1",
        "Gate conversation beat 1",
        "Gate conversation beat 2",
        "Gate conversation beat 2",
        "Gate conversation beat 3",
        "Gate conversation beat 3",
        "Gate conversation beat 4",
        "Gate conversation beat 4",
    ]
    assert set(script.voice_map) == {"ravi", "maya", "guard"}
    assert all(script.voice_map.values())


def test_dialogue_speaker_lines_feed_caption_inputs(generated_dialogue) -> None:
    script = generated_dialogue

    caption_text = []
    for scene in script.scenes:
        cues = scene_caption_timeline(
            scene.script_text,
            scene_duration=4.0,
        )
        caption_text.extend(text for text, _start, _end in cues)

    all_captions = " ".join(caption_text)
    for line in script.lines:
        assert line["text"] in all_captions


def test_narrative_generate_without_duration_still_returns_accepted() -> None:
    with (
        patch("youtube_pipeline.api.main.init_job") as init_job,
        patch(
            "youtube_pipeline.api.main._dispatch_job",
            return_value="mocked",
        ) as dispatch_job,
    ):
        response = TestClient(app).post(
            "/api/v1/generate",
            json={"idea": "A lighthouse keeper sees an impossible storm"},
        )

    assert response.status_code == 202
    init_job.assert_called_once()
    request_data = dispatch_job.call_args.args[1]
    assert request_data["format"] == VideoFormat.NARRATIVE
    assert request_data["duration"] is None
    assert request_data["max_scenes"] is None


def test_narrative_generation_clamps_duration_boundary_to_global_scene_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = ScriptEngine(
        Settings(
            gemini_api_key="offline-test-key",
            llm_provider=LLMProvider.GEMINI,
            _env_file=None,
        )
    )
    payload = {
        "title": "A Long Night",
        "full_script": " ".join(f"Beat {index}." for index in range(240)),
        "style": "cinematic",
        "scenes": [
            {
                "scene_id": index,
                "narration": f"Beat {index}.",
                "visual_prompt": f"Night scene {index}",
                "keywords": ["night"],
                "duration": 0,
                "ambience": "night",
                "sfx": [],
            }
            for index in range(240)
        ],
    }
    prompts: list[str] = []

    def fake_llm(user_prompt: str, *, system_prompt: str) -> str:
        prompts.extend((user_prompt, system_prompt))
        return json.dumps(payload)

    monkeypatch.setattr(engine, "_call_llm", fake_llm)

    script = engine.generate(
        PipelineRequest(
            idea="A mystery unfolding through one very long night",
            format=VideoFormat.NARRATIVE,
            aspect_ratio=AspectRatio.LANDSCAPE,
            target_duration_seconds=3600,
            max_scenes=240,
        )
    )

    assert len(script.scenes) == 240
    assert all("exactly 240 scenes" in prompt for prompt in prompts)

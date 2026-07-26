from __future__ import annotations

from types import SimpleNamespace

import pytest

from youtube_pipeline.models import PipelineRequest, VisualStyle
from youtube_pipeline.script_engine.generator import ScriptEngine


class _FakeGeminiModel:
    instances: list["_FakeGeminiModel"] = []
    last_kwargs: dict = {}

    def __init__(self, *args, **kwargs) -> None:
        _FakeGeminiModel.last_kwargs = kwargs
        _FakeGeminiModel.instances.append(self)

    def generate_content(self, prompt: str):
        return SimpleNamespace(
            text="""
            {
              "title": "Black Holes",
              "full_script": "Space bends. Light follows.",
              "style": "cinematic",
              "scenes": [
                {
                  "scene_id": 0,
                  "narration": "Space bends.",
                  "visual_prompt": "Warped starlight around a dark sphere",
                  "keywords": ["black hole", "space"],
                  "duration": 0
                },
                {
                  "scene_id": 1,
                  "narration": "Light follows.",
                  "visual_prompt": "Photons tracing curved paths",
                  "keywords": ["light", "gravity"],
                  "duration": 0
                }
              ]
            }
            """
        )


def test_gemini_uses_json_mime_type(monkeypatch: pytest.MonkeyPatch) -> None:
    from config.settings import LLMProvider, Settings

    fake_genai = SimpleNamespace(
        configure=lambda **kwargs: None,
        GenerativeModel=_FakeGeminiModel,
    )
    monkeypatch.setitem(__import__("sys").modules, "google.generativeai", fake_genai)
    monkeypatch.setitem(__import__("sys").modules, "google", SimpleNamespace(generativeai=fake_genai))

    settings = Settings(
        gemini_api_key="gemini-test-key",
        llm_provider=LLMProvider.GEMINI,
        llm_model="gemini-1.5-flash",
    )
    _FakeGeminiModel.instances.clear()

    engine = ScriptEngine(settings)
    script = engine.generate(
        PipelineRequest(
            idea="How black holes warp spacetime",
            style=VisualStyle.CINEMATIC,
            max_scenes=2,
            target_duration_seconds=16,
        )
    )

    assert script.title == "Black Holes"
    assert len(script.scenes) == 2
    assert script.scenes[0].script_text == "Space bends."
    assert "continuous character design" in script.scenes[0].visual_prompt
    assert _FakeGeminiModel.last_kwargs["generation_config"]["response_mime_type"] == "application/json"
    assert _FakeGeminiModel.last_kwargs["model_name"] == "gemini-1.5-flash"
    assert "exactly 2 scenes" in (_FakeGeminiModel.last_kwargs.get("system_instruction") or "")


def test_gemini_accepts_bare_scenes_array(monkeypatch: pytest.MonkeyPatch) -> None:
    from config.settings import LLMProvider, Settings

    class _ArrayModel:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def generate_content(self, prompt: str):
            return SimpleNamespace(
                text="""
                [
                  {"narration": "One.", "visual_prompt": "scene one visual"},
                  {"narration": "Two.", "visual_prompt": "scene two visual"}
                ]
                """
            )

    fake_genai = SimpleNamespace(
        configure=lambda **kwargs: None,
        GenerativeModel=_ArrayModel,
    )
    monkeypatch.setitem(__import__("sys").modules, "google.generativeai", fake_genai)
    monkeypatch.setitem(__import__("sys").modules, "google", SimpleNamespace(generativeai=fake_genai))

    settings = Settings(
        gemini_api_key="gemini-test-key",
        llm_provider=LLMProvider.GEMINI,
        llm_model="gemini-1.5-flash",
    )
    engine = ScriptEngine(settings)
    script = engine.generate(
        PipelineRequest(
            idea="RAG in AI",
            style=VisualStyle.DOCUMENTARY,
            max_scenes=2,
            target_duration_seconds=16,
        )
    )
    assert len(script.scenes) == 2
    assert script.scenes[0].script_text == "One."


def test_gemini_requires_api_key() -> None:
    from config.settings import LLMProvider, Settings
    from youtube_pipeline.exceptions import ConfigurationError

    settings = Settings(
        gemini_api_key=None,
        llm_provider=LLMProvider.GEMINI,
    )
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        ScriptEngine(settings)

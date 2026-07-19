from __future__ import annotations

from types import SimpleNamespace

import pytest

from youtube_pipeline.models import PipelineRequest, VisualStyle
from youtube_pipeline.script_engine.generator import GROQ_BASE_URL, ScriptEngine


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


class _FakeChat:
    def __init__(self, content: str) -> None:
        self.completions = _FakeCompletions(content)


class _FakeOpenAI:
    instances: list["_FakeOpenAI"] = []

    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.chat = _FakeChat(
            """
            {
              "title": "Black Holes",
              "full_script": "Space bends. Light follows.",
              "style": "cinematic",
              "scenes": [
                {
                  "scene_id": 0,
                  "script_text": "Space bends.",
                  "visual_prompt": "Warped starlight around a dark sphere",
                  "keywords": ["black hole", "space"],
                  "duration": 0
                },
                {
                  "scene_id": 1,
                  "script_text": "Light follows.",
                  "visual_prompt": "Photons tracing curved paths",
                  "keywords": ["light", "gravity"],
                  "duration": 0
                }
              ]
            }
            """
        )
        _FakeOpenAI.instances.append(self)


def test_groq_client_uses_base_url_and_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    from config.settings import LLMProvider, Settings

    settings = Settings(
        groq_api_key="gsk_test",
        openai_api_key="sk_test",
        llm_provider=LLMProvider.GROQ,
        llm_model="llama-3.3-70b-versatile",
    )
    _FakeOpenAI.instances.clear()
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)

    engine = ScriptEngine(settings)
    script = engine.generate(
        PipelineRequest(
            idea="How black holes warp spacetime",
            style=VisualStyle.CINEMATIC,
            max_scenes=4,
        )
    )

    assert script.title == "Black Holes"
    assert len(script.scenes) == 2
    assert script.scenes[0].script_text == "Space bends."
    assert script.style == "cinematic"

    assert len(_FakeOpenAI.instances) == 1
    client = _FakeOpenAI.instances[0]
    assert client.api_key == "gsk_test"
    assert client.base_url == GROQ_BASE_URL

    call = client.chat.completions.calls[0]
    assert call["model"] == "llama-3.3-70b-versatile"
    assert call["response_format"] == {"type": "json_object"}


def test_groq_requires_api_key() -> None:
    from config.settings import LLMProvider, Settings
    from youtube_pipeline.exceptions import ConfigurationError

    settings = Settings(
        groq_api_key=None,
        llm_provider=LLMProvider.GROQ,
    )
    with pytest.raises(ConfigurationError, match="GROQ_API_KEY"):
        ScriptEngine(settings)

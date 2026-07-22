from __future__ import annotations

from types import SimpleNamespace

import pytest

from youtube_pipeline.models import PipelineRequest, VisualStyle
from youtube_pipeline.script_engine.generator import ScriptEngine


class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
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


class _FakeClient:
    instances: list["_FakeClient"] = []

    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key
        self.models = _FakeModels()
        _FakeClient.instances.append(self)


def _install_fake_google_genai(monkeypatch: pytest.MonkeyPatch, client_cls=_FakeClient) -> None:
    fake_types = SimpleNamespace(
        GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    fake_genai = SimpleNamespace(Client=client_cls)
    monkeypatch.setitem(__import__("sys").modules, "google.genai", SimpleNamespace(types=fake_types))
    monkeypatch.setitem(__import__("sys").modules, "google.genai.types", fake_types)
    # ``from google import genai`` resolves google.genai via package attribute in some setups;
    # also stub top-level google package.
    monkeypatch.setitem(
        __import__("sys").modules,
        "google",
        SimpleNamespace(genai=fake_genai),
    )
    monkeypatch.setattr("google.genai.Client", client_cls, raising=False)


def test_gemini_uses_json_mime_type(monkeypatch: pytest.MonkeyPatch) -> None:
    from config.settings import LLMProvider, Settings

    # Patch where generator imports from.
    fake_types = SimpleNamespace(
        GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )

    class _Mod:
        Client = _FakeClient

    monkeypatch.setitem(__import__("sys").modules, "google", SimpleNamespace(genai=_Mod))
    monkeypatch.setitem(__import__("sys").modules, "google.genai", _Mod)
    monkeypatch.setitem(__import__("sys").modules, "google.genai.types", fake_types)

    # Ensure ``from google.genai import types`` works.
    import sys

    sys.modules["google.genai"].types = fake_types  # type: ignore[attr-defined]

    settings = Settings(
        gemini_api_key="gemini-test-key",
        llm_provider=LLMProvider.GEMINI,
        llm_model="gemini-1.5-flash",
    )
    _FakeClient.instances.clear()

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
    assert "continuous character design" in script.scenes[0].visual_prompt

    assert len(_FakeClient.instances) == 1
    assert _FakeClient.instances[0].api_key == "gemini-test-key"
    call = _FakeClient.instances[0].models.calls[0]
    assert call["model"] == "gemini-1.5-flash"
    assert call["config"].response_mime_type == "application/json"


def test_gemini_accepts_bare_scenes_array(monkeypatch: pytest.MonkeyPatch) -> None:
    from config.settings import LLMProvider, Settings

    class _ArrayModels:
        def generate_content(self, **kwargs):
            return SimpleNamespace(
                text="""
                [
                  {"narration": "One.", "visual_prompt": "scene one visual"},
                  {"narration": "Two.", "visual_prompt": "scene two visual"}
                ]
                """
            )

    class _ArrayClient:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.models = _ArrayModels()

    fake_types = SimpleNamespace(
        GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    mod = SimpleNamespace(Client=_ArrayClient, types=fake_types)
    monkeypatch.setitem(__import__("sys").modules, "google", SimpleNamespace(genai=mod))
    monkeypatch.setitem(__import__("sys").modules, "google.genai", mod)
    monkeypatch.setitem(__import__("sys").modules, "google.genai.types", fake_types)

    settings = Settings(
        gemini_api_key="gemini-test-key",
        llm_provider=LLMProvider.GEMINI,
        llm_model="gemini-1.5-flash",
    )
    engine = ScriptEngine(settings)
    script = engine.generate(
        PipelineRequest(idea="RAG in AI", style=VisualStyle.DOCUMENTARY, max_scenes=4)
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

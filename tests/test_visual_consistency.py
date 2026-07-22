"""Tests for global visual style anchor / character lock."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from youtube_pipeline.models import AspectRatio, PipelineRequest, VisualStyle
from youtube_pipeline.script_engine.generator import ScriptEngine
from youtube_pipeline.script_engine.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    build_visual_style_anchor,
    ensure_visual_prompt_has_anchor,
)


def test_system_prompt_requires_narration_and_visual_prompt() -> None:
    assert "master documentary scriptwriter" in SYSTEM_PROMPT
    assert "narration" in SYSTEM_PROMPT
    assert "visual_prompt" in SYSTEM_PROMPT
    assert "continuous character design" in SYSTEM_PROMPT
    assert "Edge-TTS" in SYSTEM_PROMPT
    assert "Pollinations" in SYSTEM_PROMPT


def test_user_prompt_embeds_global_visual_style_anchor() -> None:
    idea = "The Matsya Avatar and Manu's ancient wooden ark"
    prompt = build_user_prompt(
        idea=idea,
        style=VisualStyle.CINEMATIC,
        aspect_ratio=AspectRatio.LANDSCAPE,
        target_duration_seconds=120,
        max_scenes=8,
    )
    assert "GLOBAL VISUAL STYLE ANCHOR" in prompt
    assert "continuous character design" in prompt
    assert "narration" in prompt
    assert idea in prompt


def test_build_visual_style_anchor_includes_idea_and_style() -> None:
    anchor = build_visual_style_anchor(
        idea="Matsya Avatar saving Manu",
        style=VisualStyle.CINEMATIC,
    )
    assert anchor.startswith("(Epic cinematic portrayal of")
    assert "Matsya Avatar saving Manu" in anchor
    assert "continuous character design" in anchor


def test_ensure_visual_prompt_has_anchor_prepends_when_missing() -> None:
    anchor = build_visual_style_anchor(idea="Matsya", style=VisualStyle.CINEMATIC)
    out = ensure_visual_prompt_has_anchor("golden divine fish in floodwaters", anchor)
    assert out.startswith(anchor)
    assert "golden divine fish" in out


def test_ensure_visual_prompt_has_anchor_keeps_existing_lock() -> None:
    locked = (
        "(Epic cinematic ancient Indian mythology, hyper-detailed, "
        "continuous character design: wooden ark)"
    )
    out = ensure_visual_prompt_has_anchor(locked, "(other anchor)")
    assert out == locked


def test_generator_enforces_anchor_on_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    from config.settings import LLMProvider, Settings

    class _FakeModels:
        def generate_content(self, **kwargs):
            return SimpleNamespace(
                text="""
                {
                  "title": "Matsya",
                  "full_script": "Manu listens. The fish grows.",
                  "style": "cinematic",
                  "scenes": [
                    {
                      "scene_id": 0,
                      "narration": "Manu listens.",
                      "visual_prompt": "a man beside a river fish",
                      "keywords": ["manu", "river"],
                      "duration": 0
                    },
                    {
                      "scene_id": 1,
                      "narration": "The fish grows.",
                      "visual_prompt": "a giant fish in floodwaters",
                      "keywords": ["matsya", "flood"],
                      "duration": 0
                    }
                  ]
                }
                """
            )

    class _FakeClient:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.models = _FakeModels()

    fake_types = SimpleNamespace(
        GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    mod = SimpleNamespace(Client=_FakeClient, types=fake_types)
    monkeypatch.setitem(__import__("sys").modules, "google", SimpleNamespace(genai=mod))
    monkeypatch.setitem(__import__("sys").modules, "google.genai", mod)
    monkeypatch.setitem(__import__("sys").modules, "google.genai.types", fake_types)

    settings = Settings(
        gemini_api_key="gemini-test",
        llm_provider=LLMProvider.GEMINI,
        llm_model="gemini-1.5-flash",
    )
    engine = ScriptEngine(settings)
    request = PipelineRequest(
        idea="Matsya Avatar and Manu's ancient wooden ark",
        style=VisualStyle.CINEMATIC,
        max_scenes=4,
    )
    script = engine.generate(request)
    anchor = build_visual_style_anchor(idea=request.idea, style=request.style)

    assert len(script.scenes) == 2
    for scene in script.scenes:
        assert "continuous character design" in scene.visual_prompt
        assert scene.visual_prompt.startswith(anchor) or "continuous character design" in scene.visual_prompt

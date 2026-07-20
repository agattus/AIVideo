"""Tests for global visual style anchor / character lock."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from youtube_pipeline.models import PipelineRequest, VisualStyle
from youtube_pipeline.script_engine.generator import ScriptEngine
from youtube_pipeline.script_engine.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    build_visual_style_anchor,
    ensure_visual_prompt_has_anchor,
)
from youtube_pipeline.models import AspectRatio


def test_system_prompt_requires_style_anchor_and_bans_modern_terms() -> None:
    assert "continuous character design" in SYSTEM_PROMPT
    assert "Do NOT use modern terms" in SYSTEM_PROMPT
    assert "ancient materials" in SYSTEM_PROMPT
    assert "stock footage" in SYSTEM_PROMPT.lower() or "NOT stock" in SYSTEM_PROMPT


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
    assert "Do not use modern terms" in prompt
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

    class _FakeCompletions:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="""
                            {
                              "title": "Matsya",
                              "full_script": "Manu listens. The fish grows.",
                              "style": "cinematic",
                              "scenes": [
                                {
                                  "scene_id": 0,
                                  "script_text": "Manu listens.",
                                  "visual_prompt": "a man beside a river fish",
                                  "keywords": ["manu", "river"],
                                  "duration": 0
                                },
                                {
                                  "scene_id": 1,
                                  "script_text": "The fish grows.",
                                  "visual_prompt": "a giant fish in floodwaters",
                                  "keywords": ["matsya", "flood"],
                                  "duration": 0
                                }
                              ]
                            }
                            """
                        )
                    )
                ]
            )

    class _FakeChat:
        def __init__(self) -> None:
            self.completions = _FakeCompletions()

    class _FakeOpenAI:
        def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.chat = _FakeChat()

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)

    settings = Settings(
        groq_api_key="gsk_test",
        llm_provider=LLMProvider.GROQ,
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

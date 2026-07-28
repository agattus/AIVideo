"""Tests for multi-language script support."""

from __future__ import annotations

from pathlib import Path

from youtube_pipeline.api.schemas import GenerateVideoRequest
from youtube_pipeline.i18n import (
    caption_font_for_language,
    default_voice_for_language,
    language_options,
    normalize_language,
    script_language_name,
)
from youtube_pipeline.models import AspectRatio, PipelineRequest, VisualStyle
from youtube_pipeline.script_engine.prompts import build_system_prompt, build_user_prompt
from youtube_pipeline.video.text_clips import render_caption_rgba


def test_normalize_language_aliases() -> None:
    assert normalize_language("te") == "te"
    assert normalize_language("te-IN") == "te"
    assert normalize_language("TELUGU") == "en"  # unknown → en
    assert normalize_language(None) == "en"


def test_telugu_defaults_and_font() -> None:
    assert default_voice_for_language("te") == "te-IN-MohanNeural"
    assert "Telugu" in script_language_name("te")
    font = caption_font_for_language("te")
    assert font is not None
    assert Path(font).exists()
    assert "Telugu" in font


def test_language_options_include_telugu() -> None:
    ids = {opt["id"] for opt in language_options()}
    assert {"en", "te", "hi", "ta"}.issubset(ids)


def test_generate_request_accepts_language() -> None:
    req = GenerateVideoRequest(idea="Matsya Avatar myth", language="te", voice="te-IN-ShrutiNeural")
    assert req.language == "te"
    assert req.voice == "te-IN-ShrutiNeural"


def test_pipeline_request_defaults_english() -> None:
    req = PipelineRequest(idea="A dark temple at midnight")
    assert req.language == "en"


def test_prompts_require_native_script_language() -> None:
    system = build_system_prompt(8, language="te")
    assert "Telugu" in system
    assert "native" in system.lower() or "writing system" in system.lower()
    assert "visual_prompt" in system and "English" in system

    user = build_user_prompt(
        idea="The Matsya Avatar",
        style=VisualStyle.CINEMATIC,
        aspect_ratio=AspectRatio.LANDSCAPE,
        target_duration_seconds=60,
        max_scenes=8,
        language="te",
    )
    assert "NARRATION LANGUAGE" in user
    assert "తెలుగు" in user or "Telugu" in user


def test_telugu_caption_renders_with_noto_font() -> None:
    font = caption_font_for_language("te")
    frame = render_caption_rgba(
        "ఆ చీకటి గుడి లో… ఒక రహస్యం నిద్రపోతోంది.",
        size=(640, 360),
        font_size=40,
        font_path=font,
    )
    assert frame.shape == (360, 640, 4)
    assert frame[:, :, 3].max() > 0

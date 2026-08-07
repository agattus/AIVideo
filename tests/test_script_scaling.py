from __future__ import annotations

from youtube_pipeline.models import AspectRatio, VisualStyle
from youtube_pipeline.script_engine.prompts import (
    build_system_prompt,
    build_user_prompt,
    compute_min_scenes,
    compute_scene_word_budget,
    compute_target_scenes,
    compute_target_words,
)


def test_target_words_formula() -> None:
    # 16 minutes = 960s => int((960/60)*140) = 2240
    assert compute_target_words(960) == 2240
    assert compute_target_words(60) == 140
    assert compute_target_words(45) == 105


def test_min_scenes_fast_pacing_about_8_seconds() -> None:
    assert compute_min_scenes(45) == 6
    assert compute_min_scenes(60) == 8
    assert compute_min_scenes(960) == 120
    assert compute_min_scenes(15) == 2


def test_target_scenes_never_exceeds_max_scenes_or_global_limit() -> None:
    assert compute_target_scenes(max_scenes=8, duration_seconds=60) == 8
    assert compute_target_scenes(max_scenes=4, duration_seconds=60) == 4
    assert compute_target_scenes(max_scenes=12, duration_seconds=60) == 12
    assert compute_target_scenes(max_scenes=240, duration_seconds=3600) == 240


def test_user_prompt_requires_exact_target_scenes() -> None:
    prompt = build_user_prompt(
        idea="How black holes warp spacetime",
        style=VisualStyle.CINEMATIC,
        aspect_ratio=AspectRatio.LANDSCAPE,
        target_duration_seconds=60,
        max_scenes=8,
        target_scenes=8,
    )
    assert "You MUST generate exactly 8 scenes." in prompt
    assert "maximum 15 to 20 words per scene" in prompt
    assert "Never let a single visual linger for more than 2 short sentences." in prompt
    assert "TARGET_SCENES: 8" in prompt
    assert str(compute_scene_word_budget(8)) in prompt
    assert "Do not summarize" not in prompt
    assert "substantial spoken text" not in prompt.lower()
    assert "Do NOT write long expansive paragraphs" in prompt
    assert "The Cold Open:" in prompt
    assert "NOT sound like Wikipedia" in prompt


def test_system_prompt_embeds_exact_scene_count() -> None:
    system = build_system_prompt(10)
    assert "You MUST generate exactly 10 scenes." in system
    assert "maximum 15 to 20 words per scene" in system
    assert "Never let a single visual linger for more than 2 short sentences." in system
    assert "The Cold Open:" in system
    assert "The Tone:" in system
    assert "The Pacing:" in system
    assert "The Escalation:" in system
    assert "The Climax:" in system
    assert "NOT a Wikipedia article" in system
    assert "ellipses (...)" in system

from __future__ import annotations

from youtube_pipeline.models import AspectRatio, VisualStyle
from youtube_pipeline.script_engine.prompts import (
    build_user_prompt,
    compute_min_scenes,
    compute_target_words,
)


def test_target_words_formula() -> None:
    # 16 minutes = 960s => int((960/60)*140) = 2240
    assert compute_target_words(960) == 2240
    assert compute_target_words(60) == 140
    assert compute_target_words(45) == 105


def test_min_scenes_one_per_15_seconds() -> None:
    assert compute_min_scenes(45) == 3
    assert compute_min_scenes(960) == 64
    assert compute_min_scenes(15) == 1 or compute_min_scenes(15) == 2  # floor at 2
    assert compute_min_scenes(15) == 2


def test_user_prompt_injects_critical_word_count() -> None:
    prompt = build_user_prompt(
        idea="How black holes warp spacetime",
        style=VisualStyle.CINEMATIC,
        aspect_ratio=AspectRatio.LANDSCAPE,
        target_duration_seconds=960,
        max_scenes=8,
    )
    assert "2240 words" in prompt
    assert "Do not summarize" in prompt
    assert "narration" in prompt
    # Auto scene floor for 960s is 64 even if max_scenes arg is 8.
    assert "between 64 and 64 scenes" in prompt or "64" in prompt

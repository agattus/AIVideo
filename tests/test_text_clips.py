from __future__ import annotations

import numpy as np

from youtube_pipeline.video.text_clips import (
    create_caption_clip,
    phrase_timeline,
    render_caption_rgba,
    split_script_into_phrases,
)


def test_split_script_into_phrases_sums_to_duration() -> None:
    text = (
        "Black holes warp spacetime. Light bends around their event horizon, "
        "and nothing escapes once it crosses that invisible boundary."
    )
    phrases = split_script_into_phrases(text, scene_duration=12.0)
    assert len(phrases) >= 2
    assert all(p.strip() for p, _ in phrases)
    assert abs(sum(d for _, d in phrases) - 12.0) < 0.05
    # Punchy chunks — no phrase should dump the entire script.
    assert all(len(p) < len(text) for p, _ in phrases) or len(phrases) == 1


def test_phrase_timeline_is_contiguous() -> None:
    phrases = [("One two", 2.0), ("Three four five", 3.0)]
    timeline = phrase_timeline(phrases)
    assert timeline[0] == ("One two", 0.0, 2.0)
    assert timeline[1][1] == 2.0
    assert timeline[1][2] == 5.0


def test_render_caption_rgba_has_alpha_channel() -> None:
    frame = render_caption_rgba("Cinematic caption", size=(640, 360), font_size=36)
    assert frame.shape == (360, 640, 4)
    assert frame.dtype == np.uint8
    # Some pixels should be non-transparent where text/pill was drawn.
    assert frame[:, :, 3].max() > 0


def test_create_caption_clip_no_imagemagick() -> None:
    clip = create_caption_clip("Pure Pillow text", 1.5, size=(640, 360), font_size=40)
    try:
        assert clip.duration == 1.5
        assert clip.size == (640, 360)
        frame = clip.get_frame(0.1)
        assert frame.shape[0] == 360 and frame.shape[1] == 640
    finally:
        clip.close()

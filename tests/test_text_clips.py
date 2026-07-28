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


def test_render_caption_sits_around_three_quarters() -> None:
    """Burned-in captions should sit above the lower third, not the extreme bottom."""
    height = 360
    frame = render_caption_rgba(
        "Readable caption line",
        size=(640, height),
        font_size=36,
        vertical_ratio=0.68,
    )
    alpha = frame[:, :, 3]
    rows = np.where(alpha.max(axis=1) > 0)[0]
    assert len(rows) > 0
    center_y = float(rows.mean())
    # Center of ink should be around 68% (±12% tolerance for pill height).
    assert 0.55 * height <= center_y <= 0.82 * height
    # Must not be glued to the last ~8% of the frame.
    assert rows.max() < height * 0.95


def test_caption_cues_from_words_are_scene_relative() -> None:
    from youtube_pipeline.video.text_clips import caption_cues_from_words, scene_caption_timeline

    words = [
        {"word": "Once", "start": 5.0, "end": 5.3},
        {"word": "upon", "start": 5.3, "end": 5.6},
        {"word": "a", "start": 5.6, "end": 5.7},
        {"word": "time", "start": 5.7, "end": 6.2},
        {"word": "there", "start": 6.3, "end": 6.6},
        {"word": "lived", "start": 6.6, "end": 7.0},
        {"word": "a", "start": 7.0, "end": 7.1},
        {"word": "king", "start": 7.1, "end": 7.5},
    ]
    cues = caption_cues_from_words(words, scene_start=5.0, scene_end=8.0)
    assert cues
    assert cues[0][1] == 0.0  # relative to scene
    assert all(0.0 <= start < end <= 3.0 + 1e-6 for _, start, end in cues)

    timed = scene_caption_timeline(
        "Once upon a time there lived a king",
        scene_duration=3.0,
        words=words,
        scene_start=5.0,
    )
    assert timed
    assert timed[0][1] < 0.5


def test_create_caption_clip_no_imagemagick() -> None:
    clip = create_caption_clip("Pure Pillow text", 1.5, size=(640, 360), font_size=40)
    try:
        assert clip.duration == 1.5
        assert clip.size == (640, 360)
        frame = clip.get_frame(0.1)
        assert frame.shape[0] == 360 and frame.shape[1] == 640
    finally:
        clip.close()

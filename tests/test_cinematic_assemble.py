"""Tests for cinematic timeline assembly helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from youtube_pipeline.video.composer import VideoComposer


def test_assemble_timeline_applies_crossfade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import Settings

    composer = VideoComposer(
        Settings(
            output_dir=tmp_path / "out",
            assets_cache_dir=tmp_path / "cache",
            scene_crossfade_seconds=0.45,
        )
    )

    clip_a = MagicMock(name="a")
    clip_a.duration = 4.0
    clip_a.with_effects.return_value = clip_a

    clip_b = MagicMock(name="b")
    clip_b.duration = 4.0
    clip_b.with_effects.return_value = clip_b

    captured: dict[str, object] = {}

    def fake_concat(clips, method="compose", padding=0, **kwargs):
        captured["clips"] = clips
        captured["method"] = method
        captured["padding"] = padding
        result = MagicMock(name="timeline")
        result.duration = 7.55
        return result

    monkeypatch.setattr(
        "youtube_pipeline.video.composer.concatenate_videoclips",
        fake_concat,
    )

    timeline = composer._assemble_timeline([clip_a, clip_b])
    assert timeline.duration == 7.55
    assert clip_a.with_effects.called
    assert clip_b.with_effects.called
    assert captured["method"] == "compose"
    assert float(captured["padding"]) < 0  # overlap for dissolve-like cut

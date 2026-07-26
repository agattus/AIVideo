"""Tests for cinematic Ken Burns easing helpers."""

from __future__ import annotations

from youtube_pipeline.video.ken_burns import smoothstep


def test_smoothstep_endpoints() -> None:
    assert smoothstep(0.0) == 0.0
    assert smoothstep(1.0) == 1.0


def test_smoothstep_eases_midpoint() -> None:
    # Hermite smoothstep at 0.5 is exactly 0.5, but slope is gentler near ends.
    assert smoothstep(0.5) == 0.5
    assert smoothstep(0.25) < 0.25
    assert smoothstep(0.75) > 0.75


def test_smoothstep_clamps() -> None:
    assert smoothstep(-1.0) == 0.0
    assert smoothstep(2.0) == 1.0

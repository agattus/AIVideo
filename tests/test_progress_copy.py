"""Plain-language progress copy for the job UI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from config.settings import Settings
from youtube_pipeline.orchestrator import VideoPipelineOrchestrator


def test_emit_stage_uses_plain_language_without_stage_prefix(tmp_path: Path) -> None:
    events: list[tuple[int, str, int]] = []
    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        openai_api_key="test",
        gemini_api_key="test",
    )
    orch = VideoPipelineOrchestrator(
        settings=settings,
        script_engine=MagicMock(),
        audio_engine=MagicMock(),
        asset_service=MagicMock(),
        video_composer=MagicMock(),
        on_progress=lambda stage, label, pct: events.append((stage, label, pct)),
    )
    orch._emit_stage(2, "Recording the narration…")
    assert events
    stage, label, pct = events[-1]
    assert stage == 2
    assert pct == 60
    assert "Stage" not in label
    assert "Edge-TTS" not in label
    assert "Recording the narration" in label

"""Orchestrator uses ingest for provided scripts and never rewrites them."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from youtube_pipeline.models import PipelineRequest, VideoFormat, VisualStyle
from youtube_pipeline.orchestrator import VideoPipelineOrchestrator
from youtube_pipeline.quality.models import ScriptReview


def test_orchestrator_provided_script_skips_generate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    engine = MagicMock()
    engine._call_llm = None
    engine.generate = MagicMock(side_effect=AssertionError("generate must not run"))

    audio = MagicMock()
    timed = MagicMock()
    # Minimal timed script mirror for write_json
    from youtube_pipeline.models import SceneData, VideoScript

    script_like = VideoScript(
        title="Provided",
        full_script="One. Two.",
        style="cinematic",
        scenes=[
            SceneData(scene_id=0, script_text="One.", visual_prompt="v0"),
            SceneData(scene_id=1, script_text="Two.", visual_prompt="v1"),
        ],
    )
    timed.script = script_like
    timed.timing = {"words": [{"word": "One.", "start": 0.0, "end": 0.5}]}
    timed.audio_path = str(tmp_path / "voice.mp3")
    timed.duration_seconds = 2.0
    (tmp_path / "voice.mp3").write_bytes(b"ID3")
    audio.synthesize.return_value = timed

    assets = MagicMock()
    assets.fetch_bgm.return_value = None

    orch = VideoPipelineOrchestrator(
        script_engine=engine,
        audio_engine=audio,
        asset_service=assets,
        script_critique=lambda script, request: ScriptReview(
            status="needs_approval",
            scores={
                "idea_fit": 2,
                "hook": 2,
                "ending": 2,
                "pacing_emotion": 2,
                "format_rules": 2,
            },
            issues=["weak"],
        ),
        script_rewrite=lambda script, request, review: (_ for _ in ()).throw(
            AssertionError("rewrite must not run")
        ),
    )

    result = orch.run(
        PipelineRequest(
            idea="hint",
            format=VideoFormat.NARRATIVE,
            style=VisualStyle.CINEMATIC,
            target_duration_seconds=45,
            max_scenes=6,
            script_source="provided",
            user_script_text="One.\n\nTwo.",
            output_name="byos-run",
        )
    )
    assert result.status == "waiting_for_assets"
    engine.generate.assert_not_called()
    run_dir = Path(result.metadata["run_dir"])
    saved = (run_dir / "script.json").read_text(encoding="utf-8")
    assert "One." in saved
    quality = (run_dir / "quality_review.json").read_text(encoding="utf-8")
    assert "needs_approval" in quality
    assert '"retries": 0' in quality or '"retries":0' in quality.replace(" ", "")

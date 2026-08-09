"""Tests for script regen chaining voiceover + timing review."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tests.test_hitl_workspace import _make_run
from youtube_pipeline.assets.hitl_workspace import (
    quality_workspace_fields,
    regenerate_script_with_quality_gate,
)
from youtube_pipeline.models import VideoScript
from youtube_pipeline.quality.models import ScriptReview, TimingReview


def _timing(*, scene_durations: list[float], words: list[dict] | None = None) -> dict:
    return {
        "scenes": [
            {"scene_id": index, "duration": duration}
            for index, duration in enumerate(scene_durations)
        ],
        "words": words or [],
    }


def test_regen_script_refreshes_voiceover_timing_and_review(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=2)
    stale_audio = run / "audio" / "voiceover.mp3"
    stale_audio.write_bytes(b"stale-audio")
    (run / "timing.json").write_text(
        json.dumps(_timing(scene_durations=[1.0, 1.0])),
        encoding="utf-8",
    )

    new_script = VideoScript.model_validate(json.loads((run / "script.json").read_text()))
    new_script.title = "Regenerated Title"
    script_review = ScriptReview(status="pass", issues=[])
    refreshed_timing = _timing(
        scene_durations=[4.0, 5.0],
        words=[{"word": "hello", "start": 0.0, "end": 8.5}],
    )
    timing_review = TimingReview(status="pass", issues=[])

    def fake_gate(_candidate, _request, *, critique_fn, rewrite_fn):
        del critique_fn, rewrite_fn
        return new_script, script_review

    with patch(
        "youtube_pipeline.quality.script_review.run_script_quality_gate",
        side_effect=fake_gate,
    ), patch(
        "youtube_pipeline.assets.hitl_workspace.regenerate_voiceover",
    ) as regen_vo, patch(
        "youtube_pipeline.quality.timing_review.review_timing",
        return_value=timing_review,
    ) as review_timing_fn:

        def refresh_voiceover(root: Path, voice: str | None = None, *, on_progress=None):
            del voice, on_progress
            (root / "script_timed.json").write_text(
                new_script.model_dump_json(), encoding="utf-8"
            )
            (root / "timing.json").write_text(
                json.dumps(refreshed_timing), encoding="utf-8"
            )
            stale_audio.write_bytes(b"fresh-audio")
            return stale_audio

        regen_vo.side_effect = refresh_voiceover

        result = regenerate_script_with_quality_gate(
            run,
            job_id="regen-test",
            generate_fn=lambda _request: new_script,
        )

    assert result.status == "pass"
    regen_vo.assert_called_once_with(run)
    review_timing_fn.assert_called_once()
    kwargs = review_timing_fn.call_args.kwargs
    assert kwargs["script"].title == "Regenerated Title"
    assert kwargs["timing"] == refreshed_timing
    assert kwargs["duration_seconds"] == 9.0
    assert kwargs["target_duration_seconds"] == 60

    assert stale_audio.read_bytes() == b"fresh-audio"
    persisted = json.loads((run / "quality_review.json").read_text(encoding="utf-8"))
    assert persisted["script_review"]["status"] == "pass"
    assert persisted["timing_review"]["status"] == "pass"
    assert persisted["image_review"]["status"] == "pending"


def test_regen_script_soft_continues_on_timing_needs_approval(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=1)
    (run / "timing.json").write_text(
        json.dumps(_timing(scene_durations=[2.0])),
        encoding="utf-8",
    )

    new_script = VideoScript.model_validate(json.loads((run / "script.json").read_text()))
    script_review = ScriptReview(status="pass")
    timing_review = TimingReview(status="needs_approval", issues=["duration_drift:120s vs target 60s"])

    with patch(
        "youtube_pipeline.quality.script_review.run_script_quality_gate",
        return_value=(new_script, script_review),
    ), patch(
        "youtube_pipeline.assets.hitl_workspace.regenerate_voiceover",
        return_value=run / "audio" / "voiceover.mp3",
    ), patch(
        "youtube_pipeline.quality.timing_review.review_timing",
        return_value=timing_review,
    ):
        result = regenerate_script_with_quality_gate(
            run,
            job_id="regen-soft",
            generate_fn=lambda _request: new_script,
        )

    assert result.status == "pass"
    persisted = json.loads((run / "quality_review.json").read_text(encoding="utf-8"))
    assert persisted["timing_review"]["status"] == "needs_approval"
    assert persisted["timing_review"]["issues"] == ["duration_drift:120s vs target 60s"]


def test_legacy_quality_review_seeded_when_phase1_artifacts_exist(tmp_path: Path) -> None:
    run = _make_run(tmp_path, scenes=2)
    (run / "timing.json").write_text(
        json.dumps(_timing(scene_durations=[3.0, 3.0])),
        encoding="utf-8",
    )
    assert not (run / "quality_review.json").exists()

    fields = quality_workspace_fields(run)

    assert (run / "quality_review.json").exists()
    assert fields["quality_review"]["script_review"]["status"] == "pass"
    assert fields["quality_review"]["timing_review"]["status"] == "pass"
    assert fields["quality_review"]["image_review"]["status"] == "pending"
    assert fields["assemble_allowed"] is False

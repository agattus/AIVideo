from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from config.settings import LLMProvider, Settings
from youtube_pipeline.models import (
    PipelineRequest,
    SceneData,
    VideoFormat,
    VideoScript,
)
from youtube_pipeline.orchestrator import VideoPipelineOrchestrator
from youtube_pipeline.quality.models import ScriptReview, TimingReview


def _narrative_script(*, scene_count: int = 2) -> VideoScript:
    return VideoScript(
        title="Test",
        full_script=" ".join(f"Scene {index} text." for index in range(scene_count)),
        style="cinematic",
        format="narrative",
        scenes=[
            SceneData(
                scene_id=index,
                script_text=f"Scene {index} text.",
                visual_prompt=f"Visual {index}",
            )
            for index in range(scene_count)
        ],
    )


def _dialogue_script(*, scene_count: int = 2, line_count: int = 2) -> VideoScript:
    lines = [
        {"speaker_id": "narrator", "text": f"Line {index}."}
        for index in range(line_count)
    ]
    return VideoScript(
        title="Dialogue",
        full_script=" ".join(line["text"] for line in lines),
        style="cinematic",
        format="dialogue",
        cast=[{"id": "narrator", "name": "Narrator", "gender_hint": "neutral"}],
        voice_map={"narrator": "alloy"},
        lines=lines,
        scenes=[
            SceneData(
                scene_id=index,
                script_text=lines[index]["text"],
                visual_prompt=f"Visual {index}",
            )
            for index in range(scene_count)
        ],
    )


def _timing(
    *,
    scene_durations: list[float],
    words: list[dict[str, float | str]] | None = None,
) -> dict:
    cursor = 0.0
    scenes = []
    for scene_id, duration in enumerate(scene_durations):
        scenes.append(
            {
                "scene_id": scene_id,
                "start": cursor,
                "end": cursor + duration,
                "duration": duration,
            }
        )
        cursor += duration
    payload: dict = {
        "total_duration": cursor,
        "scenes": scenes,
    }
    if words is not None:
        payload["words"] = words
    return payload


def test_review_timing_passes_when_all_checks_ok() -> None:
    from youtube_pipeline.quality.timing_review import review_timing

    review = review_timing(
        script=_narrative_script(),
        timing=_timing(scene_durations=[5.0, 5.0], words=[{"word": "end", "end": 9.0}]),
        duration_seconds=10.0,
        target_duration_seconds=10,
    )

    assert review.status == "pass"
    assert review.issues == []


def test_review_timing_fails_when_duration_drift_exceeds_band() -> None:
    from youtube_pipeline.quality.timing_review import review_timing

    review = review_timing(
        script=_narrative_script(),
        timing=_timing(scene_durations=[5.0, 5.0]),
        duration_seconds=50.0,
        target_duration_seconds=100,
    )

    assert review.status == "needs_approval"
    assert any("duration" in issue for issue in review.issues)


def test_review_timing_skips_duration_band_when_target_missing() -> None:
    from youtube_pipeline.quality.timing_review import review_timing

    review = review_timing(
        script=_narrative_script(),
        timing=_timing(scene_durations=[5.0, 5.0]),
        duration_seconds=5.0,
        target_duration_seconds=None,
    )

    assert review.status == "pass"
    assert review.issues == []


def test_review_timing_fails_on_zero_scene_duration() -> None:
    from youtube_pipeline.quality.timing_review import review_timing

    review = review_timing(
        script=_narrative_script(),
        timing=_timing(scene_durations=[5.0, 0.0]),
        duration_seconds=5.0,
        target_duration_seconds=None,
    )

    assert review.status == "needs_approval"
    assert any("scene" in issue.lower() for issue in review.issues)


def test_review_timing_fails_when_dialogue_scene_line_counts_mismatch() -> None:
    from youtube_pipeline.quality.timing_review import review_timing

    review = review_timing(
        script=_dialogue_script(scene_count=2, line_count=3),
        timing=_timing(scene_durations=[3.0, 3.0]),
        duration_seconds=6.0,
        target_duration_seconds=None,
    )

    assert review.status == "needs_approval"
    assert any("dialogue" in issue.lower() or "line" in issue.lower() for issue in review.issues)


def test_review_timing_fails_when_word_span_too_short() -> None:
    from youtube_pipeline.quality.timing_review import review_timing

    review = review_timing(
        script=_narrative_script(),
        timing=_timing(
            scene_durations=[5.0, 5.0],
            words=[{"word": "hello", "start": 0.0, "end": 4.0}],
        ),
        duration_seconds=10.0,
        target_duration_seconds=None,
    )

    assert review.status == "needs_approval"
    assert any("word" in issue.lower() or "caption" in issue.lower() for issue in review.issues)


def test_orchestrator_persists_timing_review_without_wiping_script_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    script = _dialogue_script(scene_count=1, line_count=1)
    timing = _timing(scene_durations=[2.0], words=[{"word": "line", "start": 0.0, "end": 1.9}])
    script_review = ScriptReview(
        status="needs_approval",
        scores={"hook": 2},
        issues=["low_score:hook"],
        retries=1,
    )
    timing_review = TimingReview(status="pass", issues=[])

    class FakeScriptEngine:
        def generate(self, request: PipelineRequest) -> VideoScript:
            del request
            return script

        def _call_llm(self, *_args, **_kwargs) -> str:
            return "{}"

    class FakeAudioEngine:
        def synthesize(
            self,
            script: VideoScript,
            output_dir: Path,
            *,
            voice: str | None,
        ) -> SimpleNamespace:
            del voice
            output_dir.mkdir(parents=True, exist_ok=True)
            audio_path = output_dir / "voiceover.mp3"
            audio_path.write_bytes(b"audio")
            return SimpleNamespace(
                script=script,
                timing=timing,
                audio_path=str(audio_path),
                duration_seconds=2.0,
            )

    def fake_script_gate(candidate, request, *, critique_fn, rewrite_fn):
        del candidate, request, critique_fn, rewrite_fn
        return script, script_review

    def fake_timing_gate(**kwargs):
        assert kwargs["script"] is script
        assert kwargs["timing"] == timing
        assert kwargs["duration_seconds"] == 2.0
        return timing_review

    monkeypatch.setattr(
        "youtube_pipeline.orchestrator.run_script_quality_gate",
        fake_script_gate,
    )
    monkeypatch.setattr(
        "youtube_pipeline.orchestrator.review_timing",
        fake_timing_gate,
    )

    settings = Settings(
        output_dir=tmp_path,
        assets_cache_dir=tmp_path / "cache",
        gemini_api_key="offline-test-key",
        llm_provider=LLMProvider.GEMINI,
        _env_file=None,
    )
    orchestrator = VideoPipelineOrchestrator(
        settings,
        script_engine=FakeScriptEngine(),
        audio_engine=FakeAudioEngine(),
        asset_service=SimpleNamespace(fetch_bgm=lambda *_args, **_kwargs: None),
        video_composer=SimpleNamespace(),
    )
    request = PipelineRequest(
        idea="Timing review hook",
        format=VideoFormat.DIALOGUE,
        output_name="timing-hook-test",
        target_duration_seconds=None,
    )

    result = orchestrator.run(request)
    run_dir = Path(result.metadata["run_dir"])
    persisted = json.loads((run_dir / "quality_review.json").read_text(encoding="utf-8"))

    assert persisted["script_review"]["status"] == "needs_approval"
    assert persisted["script_review"]["issues"] == ["low_score:hook"]
    assert persisted["timing_review"]["status"] == "pass"
    assert persisted["timing_review"]["issues"] == []

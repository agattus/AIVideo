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
from youtube_pipeline.quality.models import ScriptReview


def _dialogue_script(title: str, text: str) -> VideoScript:
    cast = [{"id": "narrator", "name": "Narrator", "gender_hint": "neutral"}]
    lines = [{"speaker_id": "narrator", "text": text}]
    return VideoScript(
        title=title,
        full_script=text,
        style="cinematic",
        format=VideoFormat.DIALOGUE.value,
        cast=cast,
        voice_map={"narrator": "alloy"},
        lines=lines,
        scenes=[
            SceneData(
                scene_id=0,
                script_text=text,
                visual_prompt="A narrator framed in dramatic light",
            )
        ],
    )


def test_run_persists_rewritten_script_review_before_tts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original = _dialogue_script("Original", "The old opening.")
    rewritten = _dialogue_script("Rewritten", "A stronger opening.")
    generated_requests: list[PipelineRequest] = []
    synthesized_scripts: list[VideoScript] = []

    class FakeScriptEngine:
        def generate(self, request: PipelineRequest) -> VideoScript:
            generated_requests.append(request)
            return original

    class FakeAudioEngine:
        def synthesize(
            self,
            script: VideoScript,
            output_dir: Path,
            *,
            voice: str | None,
        ) -> SimpleNamespace:
            del voice
            synthesized_scripts.append(script)
            output_dir.mkdir(parents=True, exist_ok=True)
            audio_path = output_dir / "voiceover.mp3"
            audio_path.write_bytes(b"audio")
            return SimpleNamespace(
                script=script,
                timing={},
                audio_path=str(audio_path),
                duration_seconds=1.0,
            )

    review = ScriptReview(
        status="needs_approval",
        scores={"hook": 2},
        issues=["low_score:hook"],
        retries=1,
    )

    def fake_gate(script, request, *, critique_fn, rewrite_fn):
        del critique_fn, rewrite_fn
        assert script is original
        assert request is generated_requests[0]
        return rewritten, review

    monkeypatch.setattr(
        "youtube_pipeline.orchestrator.run_script_quality_gate",
        fake_gate,
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
        script_critique=lambda *_args: review,
        script_rewrite=lambda *_args: rewritten,
    )
    request = PipelineRequest(
        idea="Improve this dialogue",
        format=VideoFormat.DIALOGUE,
        output_name="quality-hook-test",
    )

    result = orchestrator.run(request)
    run_dir = Path(result.metadata["run_dir"])

    assert synthesized_scripts == [rewritten]
    assert json.loads((run_dir / "script.json").read_text(encoding="utf-8"))[
        "title"
    ] == "Rewritten"
    assert json.loads((run_dir / "dialogue_lines.json").read_text(encoding="utf-8")) == [
        {"speaker_id": "narrator", "text": "A stronger opening."}
    ]
    persisted_review = json.loads(
        (run_dir / "quality_review.json").read_text(encoding="utf-8")
    )
    assert persisted_review["script_review"]["status"] == "needs_approval"
    assert persisted_review["script_review"]["issues"] == ["low_score:hook"]

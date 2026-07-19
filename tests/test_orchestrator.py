from __future__ import annotations

from pathlib import Path

from youtube_pipeline.models import (
    AudioArtifact,
    MediaAsset,
    PipelineRequest,
    Scene,
    ScriptPackage,
    SubtitleCue,
    VisualStyle,
)
from youtube_pipeline.orchestrator import VideoPipelineOrchestrator


class FakeScriptEngine:
    def generate(self, request: PipelineRequest) -> ScriptPackage:
        scenes = [
            Scene(
                index=0,
                narration="One",
                visual_prompt="cinematic ocean wide shot",
                keywords=["ocean"],
            ),
            Scene(
                index=1,
                narration="Two",
                visual_prompt="cinematic mountain ridge",
                keywords=["mountain"],
            ),
        ]
        return ScriptPackage(
            title="Fake Title",
            idea=request.idea,
            style=request.style,
            full_script="One Two",
            scenes=scenes,
        )


class FakeAudioEngine:
    def synthesize(self, script: ScriptPackage, output_dir: Path, *, voice: str | None = None):
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / "voiceover.mp3"
        audio_path.write_bytes(b"fake-audio")
        srt_path = output_dir / "captions.srt"
        srt_path.write_text("1\n00:00:00,000 --> 00:00:02,000\nOne Two\n", encoding="utf-8")
        return AudioArtifact(
            audio_path=audio_path,
            duration_seconds=4.0,
            subtitle_cues=[
                SubtitleCue(index=1, start=0.0, end=2.0, text="One"),
                SubtitleCue(index=2, start=2.0, end=4.0, text="Two"),
            ],
            srt_path=srt_path,
            vtt_path=None,
        )


class FakeAssetService:
    def acquire_all(self, script: ScriptPackage, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        assets = []
        for scene in script.scenes:
            path = output_dir / f"scene_{scene.index}.jpg"
            path.write_bytes(b"fake-image")
            assets.append(
                MediaAsset(
                    scene_index=scene.index,
                    path=path,
                    source="fake",
                    media_type="image",
                )
            )
        return assets


class FakeVideoComposer:
    def __init__(self) -> None:
        self.called = False

    def compose(self, *, request, timed_scenes, audio, output_path: Path) -> Path:
        self.called = True
        output_path.write_bytes(b"fake-mp4")
        return output_path


def test_orchestrator_happy_path(tmp_path: Path, monkeypatch) -> None:
    from config.settings import Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        openai_api_key="test",
        pexels_api_key="test",
    )
    settings.ensure_directories()

    composer = FakeVideoComposer()
    orch = VideoPipelineOrchestrator(
        settings=settings,
        script_engine=FakeScriptEngine(),  # type: ignore[arg-type]
        audio_engine=FakeAudioEngine(),  # type: ignore[arg-type]
        asset_service=FakeAssetService(),  # type: ignore[arg-type]
        video_composer=composer,  # type: ignore[arg-type]
    )

    result = orch.run(
        PipelineRequest(
            idea="The future of renewable energy",
            style=VisualStyle.CINEMATIC,
            output_name="renewable",
        )
    )

    assert composer.called
    assert result.video_path.exists()
    assert (result.run_dir / "script.json").exists()
    assert (result.run_dir / "timeline.json").exists()
    assert result.script.title == "Fake Title"

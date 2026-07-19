from __future__ import annotations

from pathlib import Path

from youtube_pipeline.audio.tts import TTSResult
from youtube_pipeline.models import (
    MediaAsset,
    PipelineRequest,
    PipelineResult,
    SceneData,
    VideoScript,
    VisualStyle,
    WordTimestamp,
)
from youtube_pipeline.orchestrator import VideoPipelineOrchestrator


class FakeScriptEngine:
    def generate(self, request: PipelineRequest) -> VideoScript:
        scenes = [
            SceneData(
                scene_id=0,
                script_text="One",
                visual_prompt="cinematic ocean wide shot",
                keywords=["ocean"],
            ),
            SceneData(
                scene_id=1,
                script_text="Two",
                visual_prompt="cinematic mountain ridge",
                keywords=["mountain"],
            ),
        ]
        return VideoScript(
            title="Fake Title",
            full_script="One Two",
            style=request.style.value,
            scenes=scenes,
        )


class FakeAudioEngine:
    def synthesize(self, script: VideoScript, output_dir: Path, *, voice: str | None = None):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / "voiceover.mp3"
        audio_path.write_bytes(b"fake-audio")
        timed_scenes = [
            scene.model_copy(update={"duration": 2.0}) for scene in script.scenes
        ]
        timed = script.model_copy(update={"scenes": timed_scenes})
        return TTSResult(
            audio_path=audio_path,
            duration_seconds=4.0,
            script=timed,
            word_timestamps=[
                WordTimestamp(word="One", start=0.0, end=2.0),
                WordTimestamp(word="Two", start=2.0, end=4.0),
            ],
            timing={"total_duration": 4.0, "scenes": []},
        )


class FakeAssetService:
    def acquire_all(self, script: VideoScript, output_dir: Path):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        assets = []
        for scene in script.scenes:
            path = output_dir / f"scene_{scene.scene_id:02d}.jpg"
            path.write_bytes(b"fake-image")
            assets.append(
                MediaAsset(
                    scene_id=scene.scene_id,
                    path=str(path),
                    source="fake",
                    media_type="image",
                )
            )
        return assets

    def fetch_bgm(self, style: str, output_dir: Path):
        # Optional BGM; return None so composition stays voiceover-only in unit tests.
        return None


class FakeVideoComposer:
    def __init__(self) -> None:
        self.called = False

    def compose(self, script, audio_path, assets_dir, output_path: Path) -> PipelineResult:
        self.called = True
        output_path = Path(output_path)
        output_path.write_bytes(b"fake-mp4")
        return PipelineResult(
            video_path=str(output_path),
            status="success",
            metadata={"title": script.title},
        )


def test_orchestrator_happy_path(tmp_path: Path) -> None:
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
    assert result.status == "success"
    assert Path(result.video_path).exists()
    assert (Path(result.metadata["run_dir"]) / "script.json").exists()
    assert result.metadata["title"] == "Fake Title"

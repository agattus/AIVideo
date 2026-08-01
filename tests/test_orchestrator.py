from __future__ import annotations

from pathlib import Path

from youtube_pipeline.audio.tts import TTSResult
from youtube_pipeline.models import (
    PipelineRequest,
    PipelineResult,
    SceneData,
    VideoScript,
    VisualStyle,
    WordTimestamp,
)
from youtube_pipeline.orchestrator import WAITING_MESSAGE, VideoPipelineOrchestrator


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
    def synthesize(
        self,
        script: VideoScript,
        output_dir: Path,
        *,
        voice: str | None = None,
        use_per_scene_text: bool = False,
    ):
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
    def fetch_bgm(self, style: str, output_dir: Path):
        return None


class FakeComposer:
    def __init__(self) -> None:
        self.called = False
        self.width = 0
        self.height = 0
        self.enable_ken_burns = True

    def compose(self, script, audio_path, assets_dir, output_path, **_kwargs):
        self.called = True
        Path(output_path).write_bytes(b"fake-mp4")
        return PipelineResult(
            video_path=str(Path(output_path).resolve()),
            status="success",
            metadata={"title": script.title, "scene_count": len(script.scenes)},
        )


def test_orchestrator_pauses_after_audio_with_prompts(tmp_path: Path, capsys) -> None:
    from config.settings import Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        openai_api_key="test",
        gemini_api_key="test",
    )
    settings.ensure_directories()

    composer = FakeComposer()
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

    assert composer.called is False
    assert result.status == "waiting_for_assets"
    assert result.metadata["waiting_for_assets"] is True
    assert result.metadata["compile_video"] is False
    assert result.metadata["message"] == WAITING_MESSAGE
    run_dir = Path(result.metadata["run_dir"])
    assert (run_dir / "script.json").exists()
    assert (run_dir / "audio" / "voiceover.mp3").exists()
    assert (run_dir / "prompts.json").exists()
    assert (run_dir / "prompts.csv").exists()
    assert (run_dir / "WAITING_FOR_ASSETS.txt").exists()
    assert not (run_dir / "assets" / "scene_00.jpg").exists()
    assert WAITING_MESSAGE in capsys.readouterr().out


def test_orchestrator_resume_assembles_video(tmp_path: Path) -> None:
    from config.settings import Settings
    from PIL import Image
    import zipfile

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        openai_api_key="test",
        gemini_api_key="test",
    )
    composer = FakeComposer()
    orch = VideoPipelineOrchestrator(
        settings=settings,
        script_engine=FakeScriptEngine(),  # type: ignore[arg-type]
        audio_engine=FakeAudioEngine(),  # type: ignore[arg-type]
        asset_service=FakeAssetService(),  # type: ignore[arg-type]
        video_composer=composer,  # type: ignore[arg-type]
    )
    phase1 = orch.run(
        PipelineRequest(
            idea="Resume myth",
            style=VisualStyle.CINEMATIC,
            output_name="resume-myth",
        )
    )
    run_dir = Path(phase1.metadata["run_dir"])

    zip_path = tmp_path / "scenes.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i in range(2):
            img = tmp_path / f"scene_{i:02d}.jpg"
            Image.new("RGB", (64, 64), (20 + i * 40, 80, 160)).save(img, format="JPEG")
            zf.write(img, arcname=img.name)

    result = orch.resume(run_dir, zip_path=zip_path)
    assert composer.called is True
    assert result.status == "success"
    assert result.video_path.endswith(".mp4")
    assert Path(result.video_path).exists()

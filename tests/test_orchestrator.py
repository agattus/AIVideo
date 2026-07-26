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
    def __init__(self) -> None:
        self.quota_hit = False
        self.pending_scene_ids: list[int] = []
        self.quota_message = None

    def acquire_all(self, script: VideoScript, output_dir: Path, *, aspect_ratio="16:9"):
        from PIL import Image

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        assets = []
        for scene in script.scenes:
            path = output_dir / f"scene_{scene.scene_id:02d}.jpg"
            Image.new("RGB", (64, 64), (30, 90, 160)).save(path, format="JPEG")
            assets.append(
                MediaAsset(
                    scene_id=scene.scene_id,
                    path=str(path),
                    source="fake",
                    media_type="image",
                )
            )
        self.pending_scene_ids = []
        return assets

    def fetch_bgm(self, style: str, output_dir: Path):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        bgm = output_dir / "bgm.mp3"
        bgm.write_bytes(b"ID3" + b"\x00" * 2048)
        return bgm


class FakeVideoComposer:
    def __init__(self) -> None:
        self.called = False
        self.last_args: tuple | None = None

    def compose(self, script, audio_path, assets_dir, output_path):
        self.called = True
        self.last_args = (script, audio_path, assets_dir, output_path)
        Path(output_path).write_bytes(b"fake-mp4")
        return PipelineResult(
            video_path=str(Path(output_path).resolve()),
            status="success",
            metadata={"title": script.title, "style": script.style},
        )


def test_orchestrator_compiles_cinematic_video_with_bgm(tmp_path: Path) -> None:
    from config.settings import Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        openai_api_key="test",
        gemini_api_key="test",
    )
    settings.ensure_directories()

    composer = FakeVideoComposer()
    assets = FakeAssetService()
    orch = VideoPipelineOrchestrator(
        settings=settings,
        script_engine=FakeScriptEngine(),  # type: ignore[arg-type]
        audio_engine=FakeAudioEngine(),  # type: ignore[arg-type]
        asset_service=assets,  # type: ignore[arg-type]
        video_composer=composer,  # type: ignore[arg-type]
    )

    result = orch.run(
        PipelineRequest(
            idea="The future of renewable energy",
            style=VisualStyle.CINEMATIC,
            output_name="renewable",
        )
    )

    assert composer.called is True
    assert result.status == "success"
    assert result.metadata["compile_video"] is True
    assert result.video_path.endswith(".mp4")
    assert Path(result.video_path).exists()
    run_dir = Path(result.metadata["run_dir"])
    assert (run_dir / "script.json").exists()
    assert (run_dir / "audio" / "voiceover.mp3").exists()
    assert (run_dir / "assets" / "scene_00.jpg").exists()
    assert (run_dir / "assets" / "bgm.mp3").exists()
    assert result.metadata.get("bgm_path")

"""Core pipeline orchestration: idea + style -> finished YouTube video."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings, get_settings
from youtube_pipeline.assets.service import AssetService
from youtube_pipeline.audio.tts import AudioEngine
from youtube_pipeline.exceptions import PipelineError
from youtube_pipeline.models import PipelineRequest, PipelineResult
from youtube_pipeline.script_engine.generator import ScriptEngine
from youtube_pipeline.utils.files import ensure_dir, slugify, write_json
from youtube_pipeline.utils.logging import get_logger, setup_logging
from youtube_pipeline.video.composer import VideoComposer
from youtube_pipeline.video.timing import align_scenes_to_audio

logger = get_logger(__name__)


class VideoPipelineOrchestrator:
    """Coordinates script, audio, assets, and video composition stages.

    Architecture (data flow)::

        PipelineRequest(idea, style)
                |
                v
        ScriptEngine      -> ScriptPackage (scenes + visual prompts)
                |
                v
        AudioEngine       -> voiceover + SRT/VTT + word timings
                |
                v
        AssetService      -> per-scene MediaAsset (AI or stock)
                |
                v
        timing.align...   -> TimedScene list locked to audio duration
                |
                v
        VideoComposer     -> Ken Burns + captions + mux -> .mp4
                |
                v
        PipelineResult
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        script_engine: ScriptEngine | None = None,
        audio_engine: AudioEngine | None = None,
        asset_service: AssetService | None = None,
        video_composer: VideoComposer | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        setup_logging(self.settings.log_level)
        self.script_engine = script_engine or ScriptEngine(self.settings)
        self.audio_engine = audio_engine or AudioEngine(self.settings)
        self.asset_service = asset_service or AssetService(self.settings)
        self.video_composer = video_composer or VideoComposer(self.settings)

    def run(self, request: PipelineRequest) -> PipelineResult:
        """Execute the full pipeline end-to-end."""
        run_dir = self._create_run_dir(request)
        logger.info(
            "Pipeline start | idea=%r | style=%s | run_dir=%s",
            request.idea,
            request.style.value,
            run_dir,
        )
        write_json(run_dir / "request.json", request.model_dump(mode="json"))

        try:
            # 1) Script & visual prompts
            script = self.script_engine.generate(request)
            write_json(run_dir / "script.json", script.model_dump(mode="json"))

            # 2) Voiceover + subtitles
            audio = self.audio_engine.synthesize(
                script,
                run_dir / "audio",
                voice=request.voice,
            )

            # 3) Visual assets
            assets = self.asset_service.acquire_all(script, run_dir / "assets")
            write_json(
                run_dir / "assets.json",
                [a.model_dump(mode="json") for a in assets],
            )

            # 4) Timeline alignment
            timed_scenes = align_scenes_to_audio(script, audio, assets)
            write_json(
                run_dir / "timeline.json",
                [t.model_dump(mode="json") for t in timed_scenes],
            )

            # 5) Compose final video
            video_name = f"{slugify(request.output_name or script.title)}.mp4"
            video_path = run_dir / video_name
            self.video_composer.compose(
                request=request,
                timed_scenes=timed_scenes,
                audio=audio,
                output_path=video_path,
            )

            result = PipelineResult(
                request=request,
                script=script,
                audio=audio,
                timed_scenes=timed_scenes,
                video_path=video_path,
                srt_path=audio.srt_path,
                vtt_path=audio.vtt_path,
                run_dir=run_dir,
            )
            write_json(run_dir / "result.json", result.model_dump(mode="json"))
            logger.info("Pipeline complete | video=%s", video_path)
            return result

        except PipelineError:
            logger.exception("Pipeline failed with domain error")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Pipeline failed with unexpected error")
            raise PipelineError(f"Unexpected pipeline failure: {exc}") from exc

    def _create_run_dir(self, request: PipelineRequest) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = slugify(request.output_name or request.idea)
        run_dir = self.settings.output_dir / f"{stamp}_{name}"
        return ensure_dir(run_dir)

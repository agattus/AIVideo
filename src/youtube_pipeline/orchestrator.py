"""Core pipeline orchestration: idea + style -> finished YouTube video."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings, get_settings
from youtube_pipeline.assets.provider import AssetService
from youtube_pipeline.audio.tts import AudioEngine
from youtube_pipeline.exceptions import PipelineError
from youtube_pipeline.models import AspectRatio, PipelineRequest, PipelineResult
from youtube_pipeline.script_engine.generator import ScriptEngine
from youtube_pipeline.utils.files import ensure_dir, slugify, write_json
from youtube_pipeline.utils.logging import get_logger, log_stage, setup_logging
from youtube_pipeline.video.composer import VideoComposer, default_output_name

logger = get_logger(__name__)


class VideoPipelineOrchestrator:
    """Coordinates script, audio, assets, and video composition stages.

    Architecture (data flow)::

        PipelineRequest(idea, style)
                |
                v
        ScriptEngine      -> VideoScript (scenes + visual prompts)
                |
                v
        AudioEngine       -> voiceover.mp3 + SceneData.duration timings
                |
                v
        AssetService      -> per-scene media in assets/
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
        """Execute the full pipeline end-to-end with verbose stage logging."""
        run_dir = self._create_run_dir(request)
        logger.info(
            "Pipeline start | idea=%r | style=%s | run_dir=%s",
            request.idea,
            request.style.value,
            run_dir,
        )
        write_json(run_dir / "request.json", request.model_dump(mode="json"))

        try:
            # ---- Stage 1/5: Script -------------------------------------------------
            log_stage(
                logger,
                1,
                "Generating Script via Groq (llama-3.3-70b-versatile) JSON output...",
            )
            script = self.script_engine.generate(request)
            write_json(run_dir / "script.json", script.model_dump(mode="json"))
            logger.info(
                "Script ready | title=%r | scenes=%d",
                script.title,
                len(script.scenes),
            )

            # ---- Stage 2/5: Audio + intervals --------------------------------------
            log_stage(
                logger,
                2,
                "Synthesizing Audio and calculating scene intervals...",
            )
            tts_result = self.audio_engine.synthesize(
                script,
                run_dir / "audio",
                voice=request.voice,
            )
            timed_script = tts_result.script
            write_json(run_dir / "script_timed.json", timed_script.model_dump(mode="json"))
            write_json(run_dir / "timing.json", tts_result.timing)
            logger.info(
                "Audio ready | duration=%.2fs | scene_durations=%s",
                tts_result.duration_seconds,
                [round(s.duration, 2) for s in timed_script.scenes],
            )

            # ---- Stage 3/5: Assets -------------------------------------------------
            log_stage(
                logger,
                3,
                "Querying Pexels (Fallback: DALL-E 3) for assets...",
            )
            assets_dir = run_dir / "assets"
            assets = self.asset_service.acquire_all(timed_script, assets_dir)
            write_json(
                run_dir / "assets.json",
                [a.model_dump(mode="json") for a in assets],
            )
            logger.info(
                "Assets acquired | count=%d | sources=%s",
                len(assets),
                sorted({a.source for a in assets}),
            )

            # ---- Stage 4/5: Localize / stage files ---------------------------------
            log_stage(
                logger,
                4,
                "Localizing files into temporary directories...",
            )
            composer = self._configure_composer(request)
            video_name = (
                f"{slugify(request.output_name)}.mp4"
                if request.output_name
                else default_output_name(timed_script)
            )
            video_path = run_dir / video_name
            logger.info(
                "Run workspace ready | audio=%s | assets=%s | out=%s",
                tts_result.audio_path,
                assets_dir,
                video_path,
            )

            # ---- Stage 5/5: Compose ------------------------------------------------
            log_stage(
                logger,
                5,
                "Initiating MoviePy multi-pass compilation...",
            )
            result = composer.compose(
                timed_script,
                tts_result.audio_path,
                assets_dir,
                video_path,
            )
            result = result.model_copy(
                update={
                    "metadata": {
                        **result.metadata,
                        "idea": request.idea,
                        "run_dir": str(run_dir),
                        "audio_duration": tts_result.duration_seconds,
                        "asset_sources": sorted({a.source for a in assets}),
                    }
                }
            )
            write_json(run_dir / "result.json", result.model_dump(mode="json"))
            logger.info("Pipeline complete | status=%s | video=%s", result.status, result.video_path)
            return result

        except PipelineError:
            logger.exception("Pipeline failed with domain error")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Pipeline failed with unexpected error")
            raise PipelineError(f"Unexpected pipeline failure: {exc}") from exc

    def _configure_composer(self, request: PipelineRequest) -> VideoComposer:
        """Apply request flags/dimensions when using a real VideoComposer."""
        composer = self.video_composer
        if type(composer) is not VideoComposer:
            return composer

        width, height = self.settings.video_width, self.settings.video_height
        if request.aspect_ratio == AspectRatio.VERTICAL:
            width, height = 1080, 1920
        elif request.aspect_ratio == AspectRatio.SQUARE:
            width, height = 1080, 1080

        composer.width = width
        composer.height = height
        composer.enable_ken_burns = request.enable_ken_burns
        composer.burn_captions = request.burn_captions
        return composer

    def _create_run_dir(self, request: PipelineRequest) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = slugify(request.output_name or request.idea)
        run_dir = self.settings.output_dir / f"{stamp}_{name}"
        return ensure_dir(run_dir)

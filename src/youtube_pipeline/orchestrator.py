"""Core pipeline orchestration: idea + style -> finished cinematic YouTube video."""

from __future__ import annotations

from collections.abc import Callable
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

# Stage number (1-5) -> progress percent reported to mobile clients / Redis.
STAGE_PROGRESS: dict[int, int] = {
    1: 20,
    2: 40,
    3: 60,
    4: 80,
    5: 90,
}
TOTAL_STAGES = 5

# Optional callback: (stage_number, stage_message, progress_percent) -> None
ProgressCallback = Callable[[int, str, int], None]


class VideoPipelineOrchestrator:
    """Coordinates script, audio, AI visuals, BGM, and cinematic MoviePy assembly.

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
        AssetService      -> per-scene AI stills + optional BGM
                |
                v
        VideoComposer     -> Ken Burns + crossfades + captions + BGM sync -> .mp4
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
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        setup_logging(self.settings.log_level)
        self.script_engine = script_engine or ScriptEngine(self.settings)
        self.audio_engine = audio_engine or AudioEngine(self.settings)
        self.asset_service = asset_service or AssetService(self.settings)
        self.video_composer = video_composer or VideoComposer(self.settings)
        self.on_progress = on_progress

    def _emit_stage(self, stage: int, message: str) -> None:
        """Log a stage transition and notify optional progress listeners (Redis/API)."""
        log_stage(logger, stage, message, total=TOTAL_STAGES)
        if self.on_progress is None:
            return
        progress = STAGE_PROGRESS.get(stage, min(100, stage * 20))
        stage_label = f"Stage {stage}/{TOTAL_STAGES}: {message}"
        try:
            self.on_progress(stage, stage_label, progress)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Progress callback failed | stage=%d | %s", stage, exc)

    def run(self, request: PipelineRequest) -> PipelineResult:
        """Execute the full cinematic pipeline end-to-end with verbose stage logging."""
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
            model_label = self.settings.llm_model or "gemini-1.5-flash"
            self._emit_stage(
                1,
                f"Generating script via {self.settings.llm_provider.value} ({model_label})...",
            )
            script = self.script_engine.generate(request)
            script_path = run_dir / "script.json"
            write_json(script_path, script.model_dump(mode="json"))
            logger.info(
                "Script ready | title=%r | scenes=%d",
                script.title,
                len(script.scenes),
            )

            # ---- Stage 2/5: Audio + intervals --------------------------------------
            self._emit_stage(
                2,
                "Synthesizing narration audio and scene intervals...",
            )
            tts_result = self.audio_engine.synthesize(
                script,
                run_dir / "audio",
                voice=request.voice,
            )
            timed_script = tts_result.script
            write_json(run_dir / "script_timed.json", timed_script.model_dump(mode="json"))
            write_json(run_dir / "timing.json", tts_result.timing)
            audio_path = Path(tts_result.audio_path)
            logger.info(
                "Audio ready | duration=%.2fs | scene_durations=%s | path=%s",
                tts_result.duration_seconds,
                [round(s.duration, 2) for s in timed_script.scenes],
                audio_path,
            )

            # ---- Stage 3/5: AI visuals + BGM ---------------------------------------
            provider_label = {
                "imagen": "Gemini high-quality AI images",
                "pollinations": "Pollinations.ai generative images (free)",
                "openai_image": "OpenAI DALL-E 3 only",
            }.get(self.settings.asset_provider.value, self.settings.asset_provider.value)
            self._emit_stage(
                3,
                f"Generating {provider_label} + cinematic BGM bed...",
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

            bgm_path = None
            try:
                bgm_path = self.asset_service.fetch_bgm(
                    timed_script.style or request.style.value,
                    assets_dir,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("BGM fetch raised unexpectedly; skipping | %s", exc)
            if bgm_path:
                logger.info("BGM ready | path=%s", bgm_path)
            else:
                logger.info("BGM skipped — composition will use voiceover only")

            # ---- Stage 4/5: Localize / stage files ---------------------------------
            self._emit_stage(
                4,
                "Staging timed audio, AI visuals, and BGM for assembly...",
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
                audio_path,
                assets_dir,
                video_path,
            )

            # ---- Stage 5/5: Compose ------------------------------------------------
            self._emit_stage(
                5,
                "Cinematic MoviePy assemble: Ken Burns, crossfades, captions, BGM sync...",
            )
            result = composer.compose(
                timed_script,
                audio_path,
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
                        "bgm_path": str(bgm_path) if bgm_path else None,
                        "script_path": str(script_path.resolve()),
                        "audio_path": str(audio_path.resolve()),
                        "assets_dir": str(assets_dir.resolve()),
                        "compile_video": True,
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

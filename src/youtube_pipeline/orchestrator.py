"""Core pipeline orchestration: idea + style -> script/audio/image assets.

Video compilation (MoviePy/FFmpeg) is intentionally disabled — this pipeline
is an asset generator for manual assembly in an external editor.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings, get_settings
from youtube_pipeline.assets.provider import AssetService
from youtube_pipeline.audio.tts import AudioEngine
from youtube_pipeline.exceptions import PipelineError
from youtube_pipeline.models import PipelineRequest, PipelineResult
from youtube_pipeline.script_engine.generator import ScriptEngine
from youtube_pipeline.utils.files import ensure_dir, slugify, write_json
from youtube_pipeline.utils.logging import get_logger, log_stage, setup_logging

logger = get_logger(__name__)

# Stage number (1-3) -> progress percent for UI / Redis clients.
STAGE_PROGRESS: dict[int, int] = {
    1: 33,
    2: 66,
    3: 100,
}
TOTAL_STAGES = 3

# Optional callback: (stage_number, stage_message, progress_percent) -> None
ProgressCallback = Callable[[int, str, int], None]

ASSETS_READY_MESSAGE = "Assets successfully generated! Ready for manual assembly."


class VideoPipelineOrchestrator:
    """Coordinates script, audio, and visual asset stages only.

    Architecture (data flow)::

        PipelineRequest(idea, style)
                |
                v
        ScriptEngine      -> VideoScript (narration + visual prompts)
                |
                v
        AudioEngine       -> voiceover.mp3 + SceneData.duration timings
                |
                v
        AssetService      -> per-scene scene_XX.jpg in assets/
                |
                v
        PipelineResult (assets only — no MoviePy render)
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        script_engine: ScriptEngine | None = None,
        audio_engine: AudioEngine | None = None,
        asset_service: AssetService | None = None,
        video_composer: object | None = None,  # retained for DI compatibility; unused
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        setup_logging(self.settings.log_level)
        self.script_engine = script_engine or ScriptEngine(self.settings)
        self.audio_engine = audio_engine or AudioEngine(self.settings)
        self.asset_service = asset_service or AssetService(self.settings)
        self.video_composer = video_composer  # intentionally unused
        self.on_progress = on_progress

    def _emit_stage(self, stage: int, message: str) -> None:
        """Log a stage transition and notify optional progress listeners."""
        log_stage(logger, stage, message, total=TOTAL_STAGES)
        if self.on_progress is None:
            return
        progress = STAGE_PROGRESS.get(stage, min(100, int(stage * 100 / TOTAL_STAGES)))
        stage_label = f"Stage {stage}/{TOTAL_STAGES}: {message}"
        try:
            self.on_progress(stage, stage_label, progress)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Progress callback failed | stage=%d | %s", stage, exc)

    def run(self, request: PipelineRequest) -> PipelineResult:
        """Generate script JSON, TTS audio, and scene images — then stop."""
        run_dir = self._create_run_dir(request)
        logger.info(
            "Asset pipeline start | idea=%r | style=%s | run_dir=%s",
            request.idea,
            request.style.value,
            run_dir,
        )
        write_json(run_dir / "request.json", request.model_dump(mode="json"))

        try:
            # ---- Stage 1/3: Script (Gemini) ----------------------------------------
            model_label = self.settings.llm_model or "gemini-1.5-flash"
            self._emit_stage(
                1,
                f"Generating documentary script via {self.settings.llm_provider.value} ({model_label})...",
            )
            script = self.script_engine.generate(request)
            script_path = run_dir / "script.json"
            write_json(script_path, script.model_dump(mode="json"))
            logger.info(
                "Script ready | title=%r | scenes=%d",
                script.title,
                len(script.scenes),
            )

            # ---- Stage 2/3: Audio --------------------------------------------------
            self._emit_stage(
                2,
                "Synthesizing Edge-TTS / TTS narration audio...",
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

            # ---- Stage 3/3: Visual assets ------------------------------------------
            provider_label = {
                "pollinations": "Pollinations.ai generative images (free)",
                "openai_image": "OpenAI DALL-E 3 only",
            }.get(self.settings.asset_provider.value, self.settings.asset_provider.value)
            self._emit_stage(
                3,
                f"Downloading {provider_label} as scene_XX.jpg...",
            )
            assets_dir = run_dir / "assets"
            assets = self.asset_service.acquire_all(timed_script, assets_dir)
            write_json(
                run_dir / "assets.json",
                [a.model_dump(mode="json") for a in assets],
            )
            logger.info(
                "Assets acquired | count=%d | sources=%s | dir=%s",
                len(assets),
                sorted({a.source for a in assets}),
                assets_dir,
            )

            # Optional BGM for editors who want a bed track (never fails the pipeline).
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

            # Write a human-readable handoff note for manual editors.
            manifest = {
                "message": ASSETS_READY_MESSAGE,
                "title": script.title,
                "idea": request.idea,
                "style": timed_script.style,
                "run_dir": str(run_dir.resolve()),
                "script_path": str(script_path.resolve()),
                "audio_path": str(audio_path.resolve()),
                "assets_dir": str(assets_dir.resolve()),
                "scene_count": len(timed_script.scenes),
                "asset_sources": sorted({a.source for a in assets}),
                "bgm_path": str(bgm_path) if bgm_path else None,
                "compile_video": False,
            }
            write_json(run_dir / "result.json", manifest)
            (run_dir / "READY_FOR_MANUAL_ASSEMBLY.txt").write_text(
                ASSETS_READY_MESSAGE + "\n",
                encoding="utf-8",
            )

            logger.info(ASSETS_READY_MESSAGE)
            print(ASSETS_READY_MESSAGE)

            # video_path points at the run folder (no MP4 is produced).
            return PipelineResult(
                video_path=str(run_dir.resolve()),
                status="success",
                metadata={
                    "title": script.title,
                    "idea": request.idea,
                    "style": timed_script.style,
                    "run_dir": str(run_dir.resolve()),
                    "script_path": str(script_path.resolve()),
                    "audio_path": str(audio_path.resolve()),
                    "assets_dir": str(assets_dir.resolve()),
                    "audio_duration": tts_result.duration_seconds,
                    "scene_count": len(timed_script.scenes),
                    "asset_sources": sorted({a.source for a in assets}),
                    "bgm_path": str(bgm_path) if bgm_path else None,
                    "compile_video": False,
                    "message": ASSETS_READY_MESSAGE,
                },
            )

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

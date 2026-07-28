"""Human-in-the-loop orchestration: script + audio → pause → resume assemble."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings, get_settings
from youtube_pipeline.assets.prompts_export import export_visual_prompts
from youtube_pipeline.assets.provider import AssetService
from youtube_pipeline.audio.tts import AudioEngine
from youtube_pipeline.exceptions import PipelineError
from youtube_pipeline.models import AspectRatio, PipelineRequest, PipelineResult, VideoScript
from youtube_pipeline.script_engine.generator import ScriptEngine
from youtube_pipeline.utils.files import ensure_dir, read_json, slugify, write_json
from youtube_pipeline.utils.logging import get_logger, log_stage, setup_logging
from youtube_pipeline.video.ffmpeg_composer import FFmpegComposer, default_output_name

logger = get_logger(__name__)

# Phase 1 stages (script + audio + prompts) before human upload.
STAGE_PROGRESS: dict[int, int] = {
    1: 30,
    2: 60,
    3: 75,  # prompts exported / waiting
}
TOTAL_STAGES = 3

# Resume assembly stages reported by tasks (not emitted via orchestrator.run).
RESUME_STAGE_PROGRESS: dict[int, int] = {
    1: 80,
    2: 95,
}

ProgressCallback = Callable[[int, str, int], None]

WAITING_MESSAGE = (
    "Script and audio ready. Generate images from prompts.json / prompts.csv, "
    "zip them, and upload to resume assembly."
)


class VideoPipelineOrchestrator:
    """Pause-and-resume YouTube pipeline.

    Phase 1 (``run``)::

        ScriptEngine → AudioEngine → prompts.json/csv → WAITING_FOR_ASSETS

    Phase 2 (``resume``)::

        uploaded scene images → FFmpegComposer (Ken Burns zoompan) → MP4
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        script_engine: ScriptEngine | None = None,
        audio_engine: AudioEngine | None = None,
        asset_service: AssetService | None = None,
        video_composer: FFmpegComposer | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        setup_logging(self.settings.log_level)
        self.script_engine = script_engine or ScriptEngine(self.settings)
        self.audio_engine = audio_engine or AudioEngine(self.settings)
        self.asset_service = asset_service or AssetService(self.settings)
        self.video_composer = video_composer or FFmpegComposer(self.settings)
        self.on_progress = on_progress

    def _emit_stage(self, stage: int, message: str, *, total: int = TOTAL_STAGES) -> None:
        log_stage(logger, stage, message, total=total)
        if self.on_progress is None:
            return
        progress = STAGE_PROGRESS.get(stage, min(100, int(stage * 100 / total)))
        stage_label = f"Stage {stage}/{total}: {message}"
        try:
            self.on_progress(stage, stage_label, progress)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Progress callback failed | stage=%d | %s", stage, exc)

    def run(self, request: PipelineRequest) -> PipelineResult:
        """Phase 1: generate script + TTS, export prompts, then pause for uploads."""
        run_dir = self._create_run_dir(request)
        logger.info(
            "HITL Phase 1 start | idea=%r | style=%s | run_dir=%s",
            request.idea,
            request.style.value,
            run_dir,
        )
        write_json(run_dir / "request.json", request.model_dump(mode="json"))

        try:
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

            self._emit_stage(2, "Synthesizing Edge-TTS / TTS narration audio...")
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
                "Audio ready | duration=%.2fs | path=%s",
                tts_result.duration_seconds,
                audio_path,
            )

            # Optional BGM bed for later mux (never blocks Phase 1).
            assets_dir = ensure_dir(run_dir / "assets")
            bgm_path = None
            try:
                bgm_path = self.asset_service.fetch_bgm(
                    timed_script.style or request.style.value,
                    assets_dir,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("BGM fetch skipped | %s", exc)

            self._emit_stage(
                3,
                "Exporting visual prompts — waiting for human image upload...",
            )
            prompts = export_visual_prompts(
                timed_script,
                run_dir,
                aspect_ratio=request.aspect_ratio.value,
            )
            from youtube_pipeline.assets.hitl_workspace import write_prompt_pack

            prompt_pack = write_prompt_pack(run_dir)
            message = WAITING_MESSAGE
            (run_dir / "WAITING_FOR_ASSETS.txt").write_text(message + "\n", encoding="utf-8")

            result = PipelineResult(
                video_path=str(run_dir.resolve()),
                status="waiting_for_assets",
                metadata={
                    "title": script.title,
                    "idea": request.idea,
                    "style": timed_script.style,
                    "aspect_ratio": request.aspect_ratio.value,
                    "run_dir": str(run_dir.resolve()),
                    "script_path": str(script_path.resolve()),
                    "audio_path": str(audio_path.resolve()),
                    "assets_dir": str(assets_dir.resolve()),
                    "prompts_json": str((run_dir / "prompts.json").resolve()),
                    "prompts_csv": str((run_dir / "prompts.csv").resolve()),
                    "prompts_all_txt": prompt_pack.get("prompts_all_txt"),
                    "audio_duration": tts_result.duration_seconds,
                    "scene_count": len(timed_script.scenes),
                    "bgm_path": str(bgm_path) if bgm_path else None,
                    "compile_video": False,
                    "waiting_for_assets": True,
                    "message": message,
                    "prompts": prompts,
                },
            )
            write_json(run_dir / "result.json", result.model_dump(mode="json"))
            logger.info(
                "Phase 1 complete — waiting_for_assets | scenes=%d | prompts=%s",
                len(timed_script.scenes),
                run_dir / "prompts.json",
            )
            print(message)
            return result

        except PipelineError:
            logger.exception("Phase 1 failed with domain error")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Phase 1 failed unexpectedly")
            raise PipelineError(f"Unexpected pipeline failure: {exc}") from exc

    def resume(
        self,
        run_dir: Path | str,
        *,
        zip_path: Path | str | None = None,
    ) -> PipelineResult:
        """Phase 2: ingest uploaded images and assemble the final MP4."""
        root = Path(run_dir)
        if not root.exists():
            raise PipelineError(f"Run directory not found: {root}")

        request = PipelineRequest.model_validate(read_json(root / "request.json"))
        timed_script = VideoScript.model_validate(read_json(root / "script_timed.json"))
        audio_path = root / "audio" / "voiceover.mp3"
        if not audio_path.exists():
            raise PipelineError(f"Voiceover missing: {audio_path}")

        assets_dir = ensure_dir(root / "assets")
        if zip_path is not None:
            from youtube_pipeline.assets.zip_ingest import ingest_assets_zip

            ingest_assets_zip(
                zip_path,
                assets_dir,
                expected_scenes=len(timed_script.scenes),
            )
        else:
            from youtube_pipeline.assets.zip_ingest import validate_scene_images

            validate_scene_images(assets_dir, expected_scenes=len(timed_script.scenes))

        composer = self._configure_composer(request)
        video_name = (
            f"{slugify(request.output_name)}.mp4"
            if request.output_name
            else default_output_name(timed_script)
        )
        video_path = root / video_name
        logger.info(
            "HITL Phase 2 assemble | run_dir=%s | scenes=%d | out=%s",
            root,
            len(timed_script.scenes),
            video_path,
        )
        result = composer.compose(
            timed_script,
            audio_path,
            assets_dir,
            video_path,
            timing=read_json(root / "timing.json") if (root / "timing.json").exists() else None,
        )
        result = result.model_copy(
            update={
                "metadata": {
                    **result.metadata,
                    "idea": request.idea,
                    "run_dir": str(root.resolve()),
                    "script_path": str((root / "script.json").resolve()),
                    "audio_path": str(audio_path.resolve()),
                    "assets_dir": str(assets_dir.resolve()),
                    "aspect_ratio": request.aspect_ratio.value,
                    "compile_video": True,
                    "waiting_for_assets": False,
                }
            }
        )
        write_json(root / "result.json", result.model_dump(mode="json"))
        waiting_note = root / "WAITING_FOR_ASSETS.txt"
        if waiting_note.exists():
            waiting_note.unlink(missing_ok=True)
        return result

    def _configure_composer(self, request: PipelineRequest) -> FFmpegComposer:
        composer = self.video_composer
        if type(composer) is not FFmpegComposer:
            return composer  # type: ignore[return-value]

        width, height = self.settings.video_width, self.settings.video_height
        if request.aspect_ratio == AspectRatio.VERTICAL:
            width, height = 1080, 1920
        elif request.aspect_ratio == AspectRatio.SQUARE:
            width, height = 1080, 1080
        else:
            # Landscape 16:9 — keep settings defaults, but normalize common HD size.
            width, height = width or 1920, height or 1080
            if width < height:
                width, height = 1920, 1080

        composer.width = int(width)
        composer.height = int(height)
        composer.enable_ken_burns = request.enable_ken_burns
        composer.burn_captions = bool(request.burn_captions)
        composer.aspect_ratio = request.aspect_ratio.value
        logger.info(
            "Composer configured | aspect=%s | %dx%d | captions=%s | ken_burns=%s",
            request.aspect_ratio.value,
            composer.width,
            composer.height,
            composer.burn_captions,
            composer.enable_ken_burns,
        )
        return composer

    def _create_run_dir(self, request: PipelineRequest) -> Path:
        # Prefer a stable job_id folder when provided (API human-in-the-loop).
        if request.output_name:
            slug = slugify(request.output_name)
            # UUID-like / job ids → stable path for resume uploads.
            if len(slug) >= 8:
                return ensure_dir(self.settings.output_dir / slug)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = slugify(request.output_name or request.idea)
        return ensure_dir(self.settings.output_dir / f"{stamp}_{name}")

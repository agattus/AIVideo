"""Core pipeline orchestration: idea + style -> finished cinematic YouTube video."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from config.settings import Settings, get_settings
from youtube_pipeline.assets.aspect import dimensions_for_aspect, label_for_aspect
from youtube_pipeline.assets.prompt_pack import missing_scene_ids, write_visual_prompt_pack
from youtube_pipeline.assets.provider import AssetService
from youtube_pipeline.audio.tts import AudioEngine
from youtube_pipeline.exceptions import AssetAcquisitionError, PipelineError
from youtube_pipeline.models import AspectRatio, PipelineRequest, PipelineResult, VideoScript
from youtube_pipeline.script_engine.generator import ScriptEngine
from youtube_pipeline.utils.files import ensure_dir, read_json, slugify, write_json
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
            assets = self.asset_service.acquire_all(
                timed_script,
                assets_dir,
                aspect_ratio=request.aspect_ratio,
            )
            write_json(
                run_dir / "assets.json",
                [a.model_dump(mode="json") for a in assets],
            )
            logger.info(
                "Assets acquired | count=%d | sources=%s | aspect=%s",
                len(assets),
                sorted({a.source for a in assets}),
                request.aspect_ratio.value,
            )

            pending = list(getattr(self.asset_service, "pending_scene_ids", []) or [])
            pending.extend(missing_scene_ids(timed_script, assets_dir))
            pending = sorted(set(pending))
            reason = None
            if getattr(self.asset_service, "quota_hit", False):
                reason = (
                    self.asset_service.quota_message
                    or "Daily/rate limit hit while generating AI visuals."
                )
            elif pending:
                reason = "Some scene visuals are missing or blank and need re-upload."

            prompt_pack = write_visual_prompt_pack(
                run_dir,
                timed_script,
                aspect_ratio=request.aspect_ratio.value,
                style=timed_script.style or request.style.value,
                pending_scene_ids=pending,
                reason=reason,
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

            if pending:
                return self._awaiting_assets_result(
                    request=request,
                    run_dir=run_dir,
                    timed_script=timed_script,
                    script_path=script_path,
                    audio_path=audio_path,
                    assets_dir=assets_dir,
                    assets=assets,
                    bgm_path=bgm_path,
                    pending=pending,
                    prompt_pack=prompt_pack,
                    audio_duration=tts_result.duration_seconds,
                )

            return self._compose_final(
                request=request,
                run_dir=run_dir,
                timed_script=timed_script,
                script_path=script_path,
                audio_path=audio_path,
                assets_dir=assets_dir,
                assets=assets,
                bgm_path=bgm_path,
                audio_duration=tts_result.duration_seconds,
            )

        except PipelineError:
            logger.exception("Pipeline failed with domain error")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Pipeline failed with unexpected error")
            raise PipelineError(f"Unexpected pipeline failure: {exc}") from exc

    def continue_from_run(self, run_dir: Path | str) -> PipelineResult:
        """Resume composition after manually re-uploading ``assets/scene_XX.jpg`` files."""
        root = Path(run_dir)
        if not root.exists():
            raise PipelineError(f"Run directory not found: {root}")

        request_path = root / "request.json"
        timed_path = root / "script_timed.json"
        if not request_path.exists() or not timed_path.exists():
            raise PipelineError(
                f"Run directory incomplete (need request.json + script_timed.json): {root}"
            )

        request = PipelineRequest.model_validate(read_json(request_path))
        timed_script = VideoScript.model_validate(read_json(timed_path))
        assets_dir = root / "assets"
        audio_path = Path(
            (read_json(root / "result.json").get("metadata") or {}).get("audio_path")
            if (root / "result.json").exists()
            else ""
        )
        if not audio_path.exists():
            audio_path = root / "audio" / "voiceover.mp3"
        script_path = root / "script.json"
        if not audio_path.exists():
            raise PipelineError(f"Voiceover missing: {audio_path}")

        pending = missing_scene_ids(timed_script, assets_dir)
        prompt_pack = write_visual_prompt_pack(
            root,
            timed_script,
            aspect_ratio=request.aspect_ratio.value,
            style=timed_script.style or request.style.value,
            pending_scene_ids=pending,
            reason="Still waiting for re-uploaded scene images." if pending else None,
        )
        if pending:
            names = ", ".join(f"scene_{sid:02d}.jpg" for sid in pending)
            raise AssetAcquisitionError(
                f"Still missing visuals for scenes [{names}]. "
                f"Generate at {request.aspect_ratio.value} "
                f"({label_for_aspect(request.aspect_ratio)}), save into {assets_dir}, "
                f"then re-run continue. See {root / 'VISUAL_PROMPTS.md'}"
            )

        assets_meta = []
        if (root / "assets.json").exists():
            try:
                assets_meta = read_json(root / "assets.json")
            except Exception:  # noqa: BLE001
                assets_meta = []
        bgm_path = assets_dir / "bgm.mp3"
        bgm = bgm_path if bgm_path.exists() else None

        logger.info(
            "Continuing run after re-upload | run_dir=%s | aspect=%s | scenes=%d",
            root,
            request.aspect_ratio.value,
            len(timed_script.scenes),
        )
        return self._compose_final(
            request=request,
            run_dir=root,
            timed_script=timed_script,
            script_path=script_path,
            audio_path=audio_path,
            assets_dir=assets_dir,
            assets=assets_meta,
            bgm_path=bgm,
            audio_duration=float(sum(s.duration for s in timed_script.scenes)),
            prompt_pack=prompt_pack,
        )

    def _awaiting_assets_result(
        self,
        *,
        request: PipelineRequest,
        run_dir: Path,
        timed_script: VideoScript,
        script_path: Path,
        audio_path: Path,
        assets_dir: Path,
        assets: list,
        bgm_path: Path | None,
        pending: list[int],
        prompt_pack: dict,
        audio_duration: float,
    ) -> PipelineResult:
        """Pause before MoviePy when visuals still need manual generation/re-upload."""
        self._emit_stage(
            4,
            "Daily limit / missing visuals — prompt pack ready for re-upload...",
        )
        message = (
            f"Paused for manual visuals ({len(pending)} scene(s)). "
            f"Aspect ratio: {request.aspect_ratio.value} "
            f"({label_for_aspect(request.aspect_ratio)}). "
            f"Open {run_dir / 'VISUAL_PROMPTS.md'}, generate scene_XX.jpg, "
            f"then run: python cli.py continue \"{run_dir}\""
        )
        logger.warning(message)
        print(message)
        result = PipelineResult(
            video_path=str(run_dir.resolve()),
            status="awaiting_assets",
            metadata={
                "title": timed_script.title,
                "idea": request.idea,
                "style": timed_script.style,
                "aspect_ratio": request.aspect_ratio.value,
                "aspect_label": label_for_aspect(request.aspect_ratio),
                "run_dir": str(run_dir.resolve()),
                "script_path": str(script_path.resolve()),
                "audio_path": str(audio_path.resolve()),
                "assets_dir": str(assets_dir.resolve()),
                "audio_duration": audio_duration,
                "scene_count": len(timed_script.scenes),
                "asset_sources": sorted(
                    {
                        str(getattr(a, "source", None) or (a.get("source") if isinstance(a, dict) else "") or "")
                        for a in assets
                        if a
                    }
                    - {""}
                ),
                "bgm_path": str(bgm_path) if bgm_path else None,
                "compile_video": False,
                "awaiting_assets": True,
                "pending_scene_ids": pending,
                "quota_hit": bool(getattr(self.asset_service, "quota_hit", False)),
                "visual_prompts_json": str((run_dir / "visual_prompts.json").resolve()),
                "visual_prompts_md": str((run_dir / "VISUAL_PROMPTS.md").resolve()),
                "continue_command": f'python cli.py continue "{run_dir}"',
                "message": message,
                "prompt_pack_pending": prompt_pack.get("pending_scene_ids"),
            },
        )
        write_json(run_dir / "result.json", result.model_dump(mode="json"))
        (run_dir / "AWAITING_ASSETS.txt").write_text(message + "\n", encoding="utf-8")
        return result

    def _compose_final(
        self,
        *,
        request: PipelineRequest,
        run_dir: Path,
        timed_script: VideoScript,
        script_path: Path,
        audio_path: Path,
        assets_dir: Path,
        assets: list,
        bgm_path: Path | None,
        audio_duration: float,
        prompt_pack: dict | None = None,
    ) -> PipelineResult:
        # ---- Stage 4/5: Localize / stage files ---------------------------------
        self._emit_stage(
            4,
            f"Staging timed audio + AI visuals ({request.aspect_ratio.value}) for assembly...",
        )
        composer = self._configure_composer(request)
        video_name = (
            f"{slugify(request.output_name)}.mp4"
            if request.output_name
            else default_output_name(timed_script)
        )
        video_path = run_dir / video_name
        logger.info(
            "Run workspace ready | audio=%s | assets=%s | aspect=%s | out=%s",
            audio_path,
            assets_dir,
            request.aspect_ratio.value,
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
        sources: list[str] = []
        for item in assets:
            if hasattr(item, "source"):
                sources.append(str(item.source))
            elif isinstance(item, dict) and item.get("source"):
                sources.append(str(item["source"]))
        result = result.model_copy(
            update={
                "metadata": {
                    **result.metadata,
                    "idea": request.idea,
                    "run_dir": str(run_dir),
                    "audio_duration": audio_duration,
                    "asset_sources": sorted(set(sources)),
                    "bgm_path": str(bgm_path) if bgm_path else None,
                    "script_path": str(Path(script_path).resolve()),
                    "audio_path": str(Path(audio_path).resolve()),
                    "assets_dir": str(Path(assets_dir).resolve()),
                    "aspect_ratio": request.aspect_ratio.value,
                    "aspect_label": label_for_aspect(request.aspect_ratio),
                    "compile_video": True,
                    "awaiting_assets": False,
                    "visual_prompts_md": str((run_dir / "VISUAL_PROMPTS.md").resolve())
                    if (run_dir / "VISUAL_PROMPTS.md").exists()
                    else None,
                    "prompt_pack_pending": (prompt_pack or {}).get("pending_scene_ids"),
                }
            }
        )
        write_json(run_dir / "result.json", result.model_dump(mode="json"))
        awaiting_note = run_dir / "AWAITING_ASSETS.txt"
        if awaiting_note.exists():
            awaiting_note.unlink(missing_ok=True)
        logger.info("Pipeline complete | status=%s | video=%s", result.status, result.video_path)
        return result

    def _configure_composer(self, request: PipelineRequest) -> VideoComposer:
        """Apply request flags/dimensions when using a real VideoComposer."""
        composer = self.video_composer
        if type(composer) is not VideoComposer:
            return composer

        width, height = dimensions_for_aspect(request.aspect_ratio)
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

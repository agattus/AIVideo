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
from youtube_pipeline.models import (
    AspectRatio,
    PipelineRequest,
    PipelineResult,
    VideoFormat,
    VideoScript,
)
from youtube_pipeline.quality.models import QualityReview, ScriptReview
from youtube_pipeline.quality.script_review import (
    CritiqueFn,
    RewriteFn,
    critique_script,
    rewrite_script_once,
    run_script_quality_gate,
)
from youtube_pipeline.quality.store import save_quality_review
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

# Resume assembly stages (compose callback climbs from ~80 → 94).
RESUME_STAGE_PROGRESS: dict[int, int] = {
    1: 80,
    2: 81,
}

ProgressCallback = Callable[[int, str, int], None]

WAITING_MESSAGE = (
    "Your script and voiceover are ready. "
    "Copy each visual prompt, create the images, upload them here, then assemble your film."
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
        script_critique: CritiqueFn | None = None,
        script_rewrite: RewriteFn | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        setup_logging(self.settings.log_level)
        self.script_engine = script_engine or ScriptEngine(self.settings)
        self.audio_engine = audio_engine or AudioEngine(self.settings)
        self.asset_service = asset_service or AssetService(self.settings)
        self.video_composer = video_composer or FFmpegComposer(self.settings)
        self.on_progress = on_progress
        self.script_critique = script_critique
        self.script_rewrite = script_rewrite

    def _emit_stage(self, stage: int, message: str, *, total: int = TOTAL_STAGES) -> None:
        # Keep technical detail in logs; send plain language to the UI.
        log_stage(logger, stage, message, total=total)
        if self.on_progress is None:
            return
        if total == 2:
            progress = RESUME_STAGE_PROGRESS.get(stage, min(100, int(stage * 100 / total)))
        else:
            progress = STAGE_PROGRESS.get(stage, min(100, int(stage * 100 / total)))
        try:
            self.on_progress(stage, message, progress)
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
            self._emit_stage(1, "Writing your story…")
            script = self.script_engine.generate(request)
            script_path = run_dir / "script.json"
            write_json(script_path, script.model_dump(mode="json"))
            if request.format == VideoFormat.DIALOGUE:
                write_json(run_dir / "cast.json", script.cast)
                write_json(run_dir / "voice_map.json", script.voice_map)
                write_json(run_dir / "dialogue_lines.json", script.lines)
            if request.format == VideoFormat.QUIZVERSE:
                from youtube_pipeline.quiz.drafts import (
                    build_community_post_draft,
                    extract_quiz_questions,
                )

                questions = extract_quiz_questions(script)
                write_json(run_dir / "quiz_questions.json", questions)
                draft = build_community_post_draft(script.title, questions)
                (run_dir / "community_post_draft.txt").write_text(
                    draft,
                    encoding="utf-8",
                )

            llm_call = getattr(self.script_engine, "_call_llm", None)
            if self.script_critique is None and llm_call is None:
                script_review = ScriptReview(
                    status="needs_approval",
                    issues=["quality_critique_unavailable"],
                )
            else:
                critique_fn = self.script_critique or (
                    lambda candidate, gate_request: critique_script(
                        candidate,
                        gate_request,
                        llm_call=llm_call,
                    )
                )
                rewrite_fn = self.script_rewrite or (
                    lambda candidate, gate_request, review: rewrite_script_once(
                        candidate,
                        gate_request,
                        review,
                        generate_fn=self.script_engine.generate,
                    )
                )
                script, script_review = run_script_quality_gate(
                    script,
                    request,
                    critique_fn=critique_fn,
                    rewrite_fn=rewrite_fn,
                )
            write_json(script_path, script.model_dump(mode="json"))
            if request.format == VideoFormat.DIALOGUE:
                write_json(run_dir / "cast.json", script.cast)
                write_json(run_dir / "voice_map.json", script.voice_map)
                write_json(run_dir / "dialogue_lines.json", script.lines)
            save_quality_review(
                run_dir,
                QualityReview(script_review=script_review),
            )
            if script_review.status == "needs_approval":
                logger.warning(
                    "Script quality review needs approval; continuing Phase 1 | issues=%s",
                    script_review.issues,
                )

            logger.info(
                "Script ready | title=%r | scenes=%d | provider=%s | model=%s",
                script.title,
                len(script.scenes),
                self.settings.llm_provider.value,
                self.settings.llm_model or "gemini-1.5-flash",
            )

            self._emit_stage(2, "Recording the narration…")
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

            self._emit_stage(3, "Preparing scene prompts for your images…")
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
        timed_script = self._ensure_scene_sfx(root, timed_script)
        audio_path = root / "audio" / "voiceover.mp3"
        if not audio_path.exists():
            raise PipelineError(f"Voiceover missing: {audio_path}")

        assets_dir = ensure_dir(root / "assets")
        scene_count = len(timed_script.scenes)
        if zip_path is not None:
            from youtube_pipeline.assets.zip_ingest import ingest_assets_zip

            self._emit_stage(1, "Checking your scene images…", total=2)
            ingest_assets_zip(
                zip_path,
                assets_dir,
                expected_scenes=scene_count,
            )
        else:
            from youtube_pipeline.assets.zip_ingest import validate_scene_images

            self._emit_stage(1, "Checking your scene images…", total=2)
            validate_scene_images(assets_dir, expected_scenes=scene_count)

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
            scene_count,
            video_path,
        )

        def _compose_progress(done: int, total: int, message: str) -> None:
            # Map scene render 80% → 94%, then leave headroom for publish.
            if total <= 0:
                pct = 88
            else:
                pct = 80 + int(14 * min(done, total) / total)
            if self.on_progress is not None:
                try:
                    self.on_progress(2, message, min(94, pct))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Resume progress callback failed | %s", exc)

        self._emit_stage(2, f"Rendering scene 1 of {scene_count}…", total=2)
        result = composer.compose(
            timed_script,
            audio_path,
            assets_dir,
            video_path,
            timing=read_json(root / "timing.json") if (root / "timing.json").exists() else None,
            language=getattr(request, "language", None) or "en",
            on_progress=_compose_progress,
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

    def _ensure_scene_sfx(self, root: Path, timed_script: VideoScript) -> VideoScript:
        """Backfill missing ambience/SFX tags (older jobs) and persist to script files."""
        from youtube_pipeline.audio.sfx_tags import apply_sfx_fallback

        updated_scenes = [apply_sfx_fallback(scene) for scene in timed_script.scenes]
        changed = any(
            a.ambience != b.ambience or a.sfx != b.sfx
            for a, b in zip(timed_script.scenes, updated_scenes, strict=True)
        )
        if not changed:
            return timed_script

        filled = sum(
            1 for scene in updated_scenes if scene.ambience != "none" or scene.sfx
        )
        logger.info(
            "Backfilled scene SFX tags | run_dir=%s | tagged=%d/%d",
            root,
            filled,
            len(updated_scenes),
        )
        updated = timed_script.model_copy(update={"scenes": updated_scenes})
        write_json(root / "script_timed.json", updated.model_dump(mode="json"))

        script_path = root / "script.json"
        if script_path.exists():
            try:
                base = VideoScript.model_validate(read_json(script_path))
                by_id = {scene.scene_id: scene for scene in updated_scenes}
                base_scenes = []
                for scene in base.scenes:
                    tagged = by_id.get(scene.scene_id)
                    if tagged is None:
                        base_scenes.append(scene)
                    else:
                        base_scenes.append(
                            scene.model_copy(
                                update={"ambience": tagged.ambience, "sfx": tagged.sfx}
                            )
                        )
                write_json(
                    script_path,
                    base.model_copy(update={"scenes": base_scenes}).model_dump(mode="json"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not persist SFX tags to script.json | %s", exc)
        return updated

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

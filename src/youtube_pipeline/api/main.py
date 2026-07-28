"""FastAPI application — web studio UI + human-in-the-loop async job API."""

from __future__ import annotations

import os
import sys
import threading
import uuid
from pathlib import Path

# Bootstrap repo root + src before any config / pipeline imports.
_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP_SRC = _BOOTSTRAP_ROOT / "src"
for _path in (_BOOTSTRAP_ROOT, _BOOTSTRAP_SRC, Path.cwd(), Path.cwd() / "src"):
    _text = str(_path)
    if _path.is_dir() and _text not in sys.path:
        sys.path.insert(0, _text)

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from youtube_pipeline.api.job_store import (
    get_job,
    init_job,
    list_jobs,
    redis_available,
    to_job_summary,
    update_job,
)
from youtube_pipeline.api.schemas import (
    AssembleAccepted,
    BgmUpdateAccepted,
    GenerateVideoAccepted,
    GenerateVideoRequest,
    JobListResponse,
    JobStatus,
    JobStatusResponse,
    ReopenAccepted,
    SceneSlot,
    SceneUploadAccepted,
    UploadAssetsAccepted,
    VoiceListResponse,
    VoiceOption,
    VoicePreviewRequest,
    VoicePreviewResponse,
    VoiceoverUpdateAccepted,
    WorkspaceResponse,
)
from youtube_pipeline.api.tasks import (
    STATIC_DIR as TASKS_STATIC_DIR,
    execute_resume_pipeline,
    execute_video_pipeline,
    resume_video_pipeline,
    run_video_pipeline,
)
from youtube_pipeline.assets.hitl_workspace import (
    publish_workspace_static,
    refetch_bgm,
    regenerate_voiceover,
    save_bgm_file,
    save_scene_image,
    save_voiceover_file,
    workspace_status,
)
from youtube_pipeline.assets.zip_ingest import ingest_assets_zip
from youtube_pipeline.utils.logging import get_logger, setup_logging
from youtube_pipeline.utils.paths import ensure_project_paths

ensure_project_paths()

logger = get_logger(__name__)
setup_logging(os.getenv("LOG_LEVEL", "INFO"))

ROOT_CANDIDATES = [
    Path(os.getenv("WEB_DIR", "")),
    Path.cwd() / "web",
    Path(__file__).resolve().parents[3] / "web",
    Path("/app/web"),
]


def _find_web_dir() -> Path:
    for candidate in ROOT_CANDIDATES:
        if candidate and (candidate / "index.html").exists():
            return candidate
    return Path.cwd() / "web"


WEB_DIR = _find_web_dir()
UI_ASSETS_DIR = WEB_DIR / "assets"


def _resolve_static_dir() -> Path:
    preferred = Path(os.getenv("STATIC_DIR", "./static"))
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path.cwd() / "static"
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning("STATIC_DIR=%s not writable; using %s", preferred, fallback)
        return fallback


STATIC_DIR = _resolve_static_dir()
# Keep task publisher and API mounts on the same static root when possible.
if TASKS_STATIC_DIR.resolve() != STATIC_DIR.resolve():
    logger.warning(
        "STATIC_DIR mismatch api=%s tasks=%s — using api STATIC_DIR",
        STATIC_DIR,
        TASKS_STATIC_DIR,
    )

app = FastAPI(
    title="AIVideo Pipeline API",
    description=(
        "Human-in-the-loop YouTube video generation. "
        "POST /api/v1/generate → waiting_for_assets → "
        "copy prompts / upload scenes / swap BGM → "
        "POST /api/v1/jobs/{job_id}/assemble → completed MP4."
    ),
    version="2.1.0",
)

_cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
allow_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if UI_ASSETS_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(UI_ASSETS_DIR)), name="ui")


def _run_job_in_thread(job_id: str, request_data: dict) -> None:
    try:
        ensure_project_paths()
        execute_video_pipeline(job_id, request_data)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background pipeline thread crashed | job_id=%s | %s", job_id, exc)


def _run_resume_in_thread(job_id: str, zip_path: str | None) -> None:
    try:
        ensure_project_paths()
        execute_resume_pipeline(job_id, zip_path=zip_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background resume thread crashed | job_id=%s | %s", job_id, exc)


def _dispatch_job(job_id: str, request_data: dict) -> str:
    use_celery = os.getenv("FORCE_INLINE_WORKER", "").lower() not in {"1", "true", "yes"}
    if use_celery and redis_available():
        try:
            run_video_pipeline.delay(job_id, request_data)
            logger.info("Dispatched Phase 1 job to Celery | job_id=%s", job_id)
            return "celery"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Celery dispatch failed (%s); falling back to thread", exc)

    thread = threading.Thread(
        target=_run_job_in_thread,
        args=(job_id, request_data),
        name=f"pipeline-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    logger.info("Dispatched Phase 1 job to in-process thread | job_id=%s", job_id)
    return "thread"


def _dispatch_resume(job_id: str, zip_path: Path | None = None) -> str:
    use_celery = os.getenv("FORCE_INLINE_WORKER", "").lower() not in {"1", "true", "yes"}
    zip_arg = str(zip_path) if zip_path is not None else None
    if use_celery and redis_available():
        try:
            resume_video_pipeline.delay(job_id, zip_arg)
            logger.info("Dispatched resume job to Celery | job_id=%s", job_id)
            return "celery"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Celery resume dispatch failed (%s); falling back to thread", exc)

    thread = threading.Thread(
        target=_run_resume_in_thread,
        args=(job_id, zip_arg),
        name=f"resume-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    logger.info("Dispatched resume job to in-process thread | job_id=%s", job_id)
    return "thread"


def _require_job_run_dir(job_id: str, *, mutate: bool = True):
    """Return job + run_dir.

    ``mutate=False`` allows viewing the studio for any job that already has a run_dir
    (waiting / completed / failed). ``mutate=True`` restricts uploads/BGM/assemble
    to editable jobs (including completed — re-edit & reassemble).
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown job_id: {job_id}",
        )
    if mutate:
        allowed = {
            JobStatus.WAITING_FOR_ASSETS,
            JobStatus.FAILED,
            JobStatus.COMPLETED,
        }
        if job.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Job is {job.status.value}; uploads/BGM/assemble require "
                    "waiting_for_assets, failed, or completed"
                ),
            )
    if not job.run_dir:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job has no run_dir — Phase 1 has not finished yet",
        )
    run_dir = Path(job.run_dir)
    if not run_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run directory missing on disk: {run_dir}",
        )
    return job, run_dir


def _workspace_response(job_id: str) -> WorkspaceResponse:
    job, run_dir = _require_job_run_dir(job_id, mutate=False)
    publish_workspace_static(job_id, run_dir, STATIC_DIR)
    data = workspace_status(run_dir, job_id=job_id)
    can_edit = job.status in {
        JobStatus.WAITING_FOR_ASSETS,
        JobStatus.FAILED,
        JobStatus.COMPLETED,
    }
    return WorkspaceResponse(
        job_id=job_id,
        status=job.status,
        can_edit=can_edit,
        run_dir=data.get("run_dir"),
        idea=str(data.get("idea") or ""),
        title=str(data.get("title") or ""),
        style=str(data.get("style") or ""),
        aspect_ratio=str(data.get("aspect_ratio") or "16:9"),
        scene_count=int(data.get("scene_count") or 0),
        scenes_ready=int(data.get("scenes_ready") or 0),
        all_scenes_ready=bool(data.get("all_scenes_ready")),
        audio_ready=bool(data.get("audio_ready")),
        script_ready=bool(data.get("script_ready")),
        video_ready=bool(data.get("video_ready")),
        bgm_ready=bool(data.get("bgm_ready")),
        audio_url=data.get("audio_url"),
        script_url=data.get("script_url"),
        video_url=data.get("video_url"),
        subtitles_url=data.get("subtitles_url"),
        bgm_url=data.get("bgm_url"),
        prompts_url=data.get("prompts_url"),
        prompts_csv_url=data.get("prompts_csv_url"),
        prompts_txt_url=data.get("prompts_txt_url"),
        current_voice=str(data.get("current_voice") or "en-US-ChristopherNeural"),
        voice_options=[VoiceOption.model_validate(v) for v in data.get("voice_options") or []],
        clipboard_text=str(data.get("clipboard_text") or ""),
        scenes=[SceneSlot.model_validate(s) for s in data.get("scenes") or []],
    )


@app.get("/", include_in_schema=False)
def studio_home() -> FileResponse:
    index = WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Web UI not found at {index}. Ensure the web/ folder is present.",
        )
    return FileResponse(index)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, object]:
    from youtube_pipeline.api.job_store import _candidate_output_roots, list_jobs

    roots = [str(p) for p in _candidate_output_roots()]
    try:
        discovered = len(list_jobs(limit=200, require_run_dir=True))
    except Exception:  # noqa: BLE001
        discovered = -1
    return {
        "status": "ok",
        "redis": redis_available(),
        "ui": (WEB_DIR / "index.html").exists(),
        "mode": "human-in-the-loop",
        "output_dirs": roots,
        "previous_films": discovered,
    }


@app.get(
    "/api/v1/voices",
    response_model=VoiceListResponse,
    tags=["voices"],
)
def list_voices(
    locale: str = Query(default="en", description="Locale prefix filter (en, en-US, all)"),
    refresh: bool = Query(default=False, description="Bypass cached edge-tts catalog"),
) -> VoiceListResponse:
    """List Edge-TTS voices (from ``edge_tts.list_voices``)."""
    from config.settings import get_settings
    from youtube_pipeline.audio.edge_voices import list_edge_voices, safe_list_edge_voices

    prefix = (locale or "en").strip() or "en"
    try:
        if refresh:
            voices = list_edge_voices(locale_prefix=prefix, force_refresh=True)
            if not voices:
                voices = safe_list_edge_voices(locale_prefix=prefix)
        else:
            voices = safe_list_edge_voices(locale_prefix=prefix)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not list edge-tts voices: {exc}",
        ) from exc

    default_voice = "en-US-ChristopherNeural"
    try:
        default_voice = get_settings().edge_tts_voice or default_voice
    except Exception:  # noqa: BLE001
        pass

    options = [VoiceOption.model_validate(v) for v in voices]
    return VoiceListResponse(
        voices=options,
        count=len(options),
        locale_prefix=prefix,
        default_voice=default_voice,
    )


@app.post(
    "/api/v1/voices/preview",
    response_model=VoicePreviewResponse,
    tags=["voices"],
)
def preview_voice(payload: VoicePreviewRequest) -> VoicePreviewResponse:
    """Synthesize a short Edge-TTS sample for the selected speaker."""
    from youtube_pipeline.audio.edge_voices import preview_voice_mp3

    try:
        path, url = preview_voice_mp3(
            payload.voice,
            static_dir=STATIC_DIR,
            text=payload.text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Voice preview failed: {exc}",
        ) from exc
    bust = int(path.stat().st_mtime)
    return VoicePreviewResponse(
        voice=payload.voice,
        preview_url=f"{url}?t={bust}",
        message=f"Preview ready for {payload.voice}",
    )


@app.get(
    "/api/v1/jobs",
    response_model=JobListResponse,
    tags=["jobs"],
)
def list_previous_jobs(limit: int = 40) -> JobListResponse:
    """List previously generated jobs from the output directory (and Redis index)."""
    jobs = list_jobs(limit=limit, require_run_dir=True)
    summaries = []
    for job in jobs:
        if job.run_dir and Path(job.run_dir).is_dir():
            try:
                publish_workspace_static(job.job_id, job.run_dir, STATIC_DIR)
                # Ensure Open/Edit can resolve the job after a process restart.
                update_job(
                    job.job_id,
                    status=job.status,
                    current_stage=job.current_stage or "Recovered from disk",
                    progress_percent=job.progress_percent,
                    run_dir=str(Path(job.run_dir).resolve()),
                    scene_count=job.scene_count,
                    title=job.title,
                    idea=job.idea,
                    download_urls=job.download_urls,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Could not publish library job | job_id=%s", job.job_id)
        summaries.append(to_job_summary(job, static_dir=STATIC_DIR))
    return JobListResponse(jobs=summaries, count=len(summaries))


@app.post(
    "/api/v1/jobs/{job_id}/reopen",
    response_model=ReopenAccepted,
    tags=["jobs"],
)
def reopen_job(job_id: str) -> ReopenAccepted:
    """Reopen a completed/failed job for editing voiceover, BGM, images, and reassemble."""
    job, run_dir = _require_job_run_dir(job_id, mutate=False)
    publish_workspace_static(job_id, run_dir, STATIC_DIR)
    ws = workspace_status(run_dir, job_id=job_id)
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        current_stage="Reopened for editing — update assets then assemble",
        progress_percent=75,
        run_dir=str(run_dir.resolve()),
        scene_count=int(ws.get("scene_count") or job.scene_count or 0),
        title=str(ws.get("title") or job.title or ""),
        idea=str(ws.get("idea") or job.idea or ""),
        error=None,
    )
    return ReopenAccepted(
        job_id=job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        message="Job reopened — edit voiceover, BGM, or images, then assemble",
    )


@app.post(
    "/api/v1/generate",
    response_model=GenerateVideoAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
def generate_video(payload: GenerateVideoRequest) -> GenerateVideoAccepted:
    """Start Phase 1 (script + audio + prompts) and return immediately."""
    job_id = str(uuid.uuid4())
    init_job(job_id)

    request_data = payload.model_dump()
    mode = _dispatch_job(job_id, request_data)
    logger.info(
        "Enqueue generate | job_id=%s | mode=%s | style=%s | aspect=%s | duration=%s | idea=%r",
        job_id,
        mode,
        payload.style,
        payload.aspect_ratio,
        payload.duration,
        payload.idea[:80],
    )
    return GenerateVideoAccepted(job_id=job_id, status=JobStatus.QUEUED)


@app.get(
    "/api/v1/jobs/{job_id}/workspace",
    response_model=WorkspaceResponse,
    tags=["jobs"],
)
def get_workspace(job_id: str) -> WorkspaceResponse:
    """Checklist of prompts, scene slots, and BGM for a paused HITL job."""
    return _workspace_response(job_id)


@app.get(
    "/api/v1/jobs/{job_id}/prompts.txt",
    response_class=PlainTextResponse,
    tags=["jobs"],
)
def get_prompts_clipboard(job_id: str) -> PlainTextResponse:
    """Clipboard-friendly prompts pack (all scenes)."""
    ws = _workspace_response(job_id)
    return PlainTextResponse(ws.clipboard_text or "", media_type="text/plain; charset=utf-8")


@app.post(
    "/api/v1/jobs/{job_id}/scenes/{scene_id}",
    response_model=SceneUploadAccepted,
    tags=["jobs"],
)
async def upload_scene_image(
    job_id: str,
    scene_id: int,
    file: UploadFile = File(..., description="Single scene image (.jpg/.png/.webp)"),
) -> SceneUploadAccepted:
    """Save one image into ``assets/scene_XX.jpg`` for the given scene slot."""
    job, run_dir = _require_job_run_dir(job_id)
    content = await file.read()
    try:
        dest = save_scene_image(
            run_dir,
            scene_id,
            content,
            source_name=file.filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    publish_workspace_static(job_id, run_dir, STATIC_DIR)
    ws = workspace_status(run_dir, job_id=job_id)
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        current_stage=(
            f"Scene images {ws['scenes_ready']}/{ws['scene_count']} ready"
            + (" — you can assemble" if ws["all_scenes_ready"] else "")
        ),
        progress_percent=75,
        scene_count=int(ws.get("scene_count") or job.scene_count or 0),
        error=None,
    )
    return SceneUploadAccepted(
        job_id=job_id,
        scene_id=scene_id,
        filename=dest.name,
        ready=True,
        scenes_ready=int(ws["scenes_ready"]),
        scene_count=int(ws["scene_count"]),
        all_scenes_ready=bool(ws["all_scenes_ready"]),
        message=f"Saved {dest.name}",
    )


@app.post(
    "/api/v1/jobs/{job_id}/upload-assets",
    response_model=UploadAssetsAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
async def upload_assets(
    job_id: str,
    file: UploadFile = File(..., description="ZIP of scene_XX.jpg images"),
    assemble: bool = Query(
        default=True,
        description="If true, start FFmpeg assembly after ingesting the ZIP",
    ),
) -> UploadAssetsAccepted:
    """Accept a ZIP of scene images, place them in ``assets/``, optionally assemble."""
    job, run_dir = _require_job_run_dir(job_id)

    filename = (file.filename or "assets.zip").lower()
    if not filename.endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload must be a .zip file of scene images",
        )

    upload_dir = run_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    zip_path = upload_dir / "assets.zip"

    content = await file.read()
    if len(content) < 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded ZIP is empty",
        )
    zip_path.write_bytes(content)

    expected = int(job.scene_count or 0)
    if expected <= 0:
        from youtube_pipeline.assets.hitl_workspace import load_prompts

        expected = int(load_prompts(run_dir).get("scene_count") or 0)

    try:
        ingest_assets_zip(zip_path, run_dir / "assets", expected_scenes=expected)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not place ZIP images: {exc}",
        ) from exc

    publish_workspace_static(job_id, run_dir, STATIC_DIR)
    ws = workspace_status(run_dir, job_id=job_id)
    logger.info(
        "Assets ZIP ingested | job_id=%s | ready=%s/%s | assemble=%s",
        job_id,
        ws["scenes_ready"],
        ws["scene_count"],
        assemble,
    )

    if assemble:
        if not ws["all_scenes_ready"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Only {ws['scenes_ready']}/{ws['scene_count']} scenes ready after "
                    "ZIP ingest — fix images or call assemble later"
                ),
            )
        mode = _dispatch_resume(job_id, zip_path=None)
        logger.info("Resume dispatched | job_id=%s | mode=%s", job_id, mode)
        return UploadAssetsAccepted(
            job_id=job_id,
            status=JobStatus.PROCESSING,
            message="Assets placed — resume assembly started",
            scenes_ready=int(ws["scenes_ready"]),
            scene_count=int(ws["scene_count"]),
            all_scenes_ready=True,
        )

    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        current_stage=(
            f"Scene images {ws['scenes_ready']}/{ws['scene_count']} ready"
            + (" — review BGM then assemble" if ws["all_scenes_ready"] else "")
        ),
        progress_percent=75,
        scene_count=int(ws["scene_count"]),
        error=None,
    )
    return UploadAssetsAccepted(
        job_id=job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        message="Assets placed in job assets/ — assemble when ready",
        scenes_ready=int(ws["scenes_ready"]),
        scene_count=int(ws["scene_count"]),
        all_scenes_ready=bool(ws["all_scenes_ready"]),
    )


@app.post(
    "/api/v1/jobs/{job_id}/voiceover",
    response_model=VoiceoverUpdateAccepted,
    tags=["jobs"],
)
async def update_voiceover(
    job_id: str,
    file: UploadFile | None = File(
        default=None,
        description="Optional custom narration (.mp3/.wav). Omit to regenerate with a new speaker.",
    ),
    voice: str | None = Form(
        default=None,
        description="Edge-TTS voice id when regenerating (ignored if file uploaded)",
    ),
) -> VoiceoverUpdateAccepted:
    """Replace narration — upload your own track or regenerate TTS with a new speaker."""
    _job, run_dir = _require_job_run_dir(job_id)

    try:
        if file is not None and file.filename:
            content = await file.read()
            save_voiceover_file(run_dir, content, source_name=file.filename)
            message = "Custom voiceover uploaded to audio/voiceover.mp3 (scenes re-timed)"
        else:
            if not voice:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Provide a voice id or upload an audio file",
                )
            regenerate_voiceover(run_dir, voice=voice)
            message = f"Regenerated voiceover with speaker={voice}"
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Voiceover update failed: {exc}",
        ) from exc

    publish_workspace_static(job_id, run_dir, STATIC_DIR)
    ws = workspace_status(run_dir, job_id=job_id)
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        current_stage="Voiceover updated — preview it, then assemble when ready",
        progress_percent=75,
        error=None,
    )
    return VoiceoverUpdateAccepted(
        job_id=job_id,
        audio_ready=bool(ws["audio_ready"]),
        audio_url=ws.get("audio_url"),
        current_voice=str(ws.get("current_voice") or voice or "custom_upload"),
        message=message,
    )


@app.post(
    "/api/v1/jobs/{job_id}/bgm",
    response_model=BgmUpdateAccepted,
    tags=["jobs"],
)
async def update_bgm(
    job_id: str,
    file: UploadFile | None = File(
        default=None,
        description="Optional custom BGM (.mp3/.wav). Omit to auto-refetch.",
    ),
    style: str | None = Form(
        default=None,
        description="Style used when auto-refetching BGM (ignored if file uploaded)",
    ),
) -> BgmUpdateAccepted:
    """Replace background music — upload a track or refetch a new bed by style."""
    _job, run_dir = _require_job_run_dir(job_id)

    if file is not None and file.filename:
        content = await file.read()
        try:
            save_bgm_file(run_dir, content, source_name=file.filename)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        message = "Custom BGM uploaded to assets/bgm.mp3"
    else:
        path = refetch_bgm(run_dir, style=style)
        if path is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not refetch BGM — try uploading an .mp3 instead",
            )
        message = f"Fetched new BGM for style={style or 'job default'}"

    publish_workspace_static(job_id, run_dir, STATIC_DIR)
    ws = workspace_status(run_dir, job_id=job_id)
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        current_stage="BGM updated — assemble when scene images are ready",
        progress_percent=75,
        error=None,
    )
    return BgmUpdateAccepted(
        job_id=job_id,
        bgm_ready=bool(ws["bgm_ready"]),
        bgm_url=ws.get("bgm_url"),
        message=message,
    )


@app.post(
    "/api/v1/jobs/{job_id}/assemble",
    response_model=AssembleAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
def assemble_video(job_id: str) -> AssembleAccepted:
    """Assemble the final MP4 from images already placed in ``assets/``."""
    _job, run_dir = _require_job_run_dir(job_id)
    ws = workspace_status(run_dir, job_id=job_id)
    if not ws["all_scenes_ready"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Need all scene images before assemble "
                f"({ws['scenes_ready']}/{ws['scene_count']} ready)"
            ),
        )
    mode = _dispatch_resume(job_id, zip_path=None)
    logger.info("Assemble dispatched | job_id=%s | mode=%s", job_id, mode)
    return AssembleAccepted(
        job_id=job_id,
        status=JobStatus.PROCESSING,
        message="Assembly started from placed scene images + BGM",
    )


@app.get(
    "/api/v1/status/{job_id}",
    response_model=JobStatusResponse,
    tags=["jobs"],
)
def get_job_status(job_id: str) -> JobStatusResponse:
    state = get_job(job_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown job_id: {job_id}",
        )
    return state

"""Human-in-the-loop workspace helpers: prompts pack, scene placement, BGM."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from config.settings import AssetProvider, get_settings
from youtube_pipeline.assets.factory import build_asset_provider
from youtube_pipeline.assets.zip_ingest import (
    find_scene_image,
    normalize_loose_scene_images,
)
from youtube_pipeline.utils.files import ensure_dir, read_json, write_json
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}


def _job_language(run_dir: Path) -> str:
    from youtube_pipeline.i18n import normalize_language

    req = run_dir / "request.json"
    if req.exists():
        try:
            return normalize_language(str(read_json(req).get("language") or "en"))
        except Exception:  # noqa: BLE001
            pass
    return "en"


def _voice_options(run_dir: Path | None = None) -> list[dict[str, str]]:
    from youtube_pipeline.audio.edge_voices import safe_list_edge_voices
    from youtube_pipeline.i18n import locale_prefix_for_language

    lang = _job_language(run_dir) if run_dir is not None else "en"
    return safe_list_edge_voices(locale_prefix=locale_prefix_for_language(lang))


# Kept for imports/tests that expect a static curated list.
EDGE_TTS_VOICE_OPTIONS: list[dict[str, str]] = [
    {"id": "en-US-ChristopherNeural", "label": "Christopher (US male)"},
    {"id": "en-US-GuyNeural", "label": "Guy (US male)"},
    {"id": "en-US-DavisNeural", "label": "Davis (US male)"},
    {"id": "en-US-JennyNeural", "label": "Jenny (US female)"},
    {"id": "en-US-AriaNeural", "label": "Aria (US female)"},
    {"id": "en-US-SaraNeural", "label": "Sara (US female)"},
    {"id": "en-GB-RyanNeural", "label": "Ryan (UK male)"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia (UK female)"},
    {"id": "en-AU-WilliamNeural", "label": "William (AU male)"},
    {"id": "en-AU-NatashaNeural", "label": "Natasha (AU female)"},
    {"id": "en-IN-PrabhatNeural", "label": "Prabhat (IN male)"},
    {"id": "en-IN-NeerjaNeural", "label": "Neerja (IN female)"},
]


def current_voice(run_dir: Path | str) -> str:
    """Return the last selected TTS voice for this job (or language default)."""
    root = Path(run_dir)
    meta = root / "voiceover_meta.json"
    if meta.exists():
        try:
            data = read_json(meta)
            voice = str(data.get("voice") or "").strip()
            if voice:
                return voice
        except Exception:  # noqa: BLE001
            pass
    req = root / "request.json"
    if req.exists():
        try:
            payload = read_json(req)
            voice = str(payload.get("voice") or "").strip()
            if voice:
                return voice
            from youtube_pipeline.i18n import default_voice_for_language

            return default_voice_for_language(str(payload.get("language") or "en"))
        except Exception:  # noqa: BLE001
            pass
    try:
        from config.settings import get_settings

        return get_settings().edge_tts_voice or "en-US-ChristopherNeural"
    except Exception:  # noqa: BLE001
        return "en-US-ChristopherNeural"


def _write_voice_meta(run_dir: Path, *, voice: str, source: str) -> None:
    write_json(
        run_dir / "voiceover_meta.json",
        {"voice": voice, "source": source},
    )
    req_path = run_dir / "request.json"
    if req_path.exists():
        try:
            req = read_json(req_path)
            req["voice"] = voice
            write_json(req_path, req)
        except Exception:  # noqa: BLE001
            pass


def remember_voice(run_dir: Path | str, voice: str, *, source: str = "tts") -> None:
    """Persist the selected Edge-TTS voice for a job run."""
    _write_voice_meta(Path(run_dir), voice=voice, source=source)

def _load_script_for_voiceover(run_dir: Path) -> "VideoScript":
    from youtube_pipeline.models import VideoScript

    for name in ("script_timed.json", "script.json"):
        path = run_dir / name
        if path.exists():
            return VideoScript.model_validate(read_json(path))
    raise FileNotFoundError(f"No script.json in {run_dir}")


def _retime_script_from_voiceover(run_dir: Path) -> float:
    """Redistribute scene durations to match the current voiceover.mp3 length."""
    from config.settings import Settings, TTSProvider
    from youtube_pipeline.audio.tts import AudioEngine

    script = _load_script_for_voiceover(run_dir)
    audio_path = run_dir / "audio" / "voiceover.mp3"
    # Timing-only path — use edge-tts settings so no cloud API key is required.
    engine = AudioEngine(Settings(tts_provider=TTSProvider.EDGE_TTS))
    duration = engine._probe_duration_seconds(audio_path)
    if duration <= 0:
        duration = engine.estimate_duration_wpm(
            " ".join(s.script_text for s in script.scenes)
        )
    timed = engine.populate_scene_durations(script, total_duration=duration)
    narration = " ".join(s.script_text for s in timed.scenes) or timed.full_script
    words = engine._estimate_word_timestamps(narration, duration)
    timing = engine._build_timing_dictionary(timed, words, duration)
    write_json(run_dir / "script_timed.json", timed.model_dump(mode="json"))
    write_json(run_dir / "timing.json", timing)
    return float(duration)


def save_voiceover_file(
    run_dir: Path | str,
    data: bytes,
    *,
    source_name: str | None = None,
) -> Path:
    """Save a custom narration track to ``audio/voiceover.mp3`` and retime scenes."""
    if len(data) < 1024:
        raise ValueError("Voiceover file is empty or too small")
    root = Path(run_dir)
    audio_dir = ensure_dir(root / "audio")
    dest = audio_dir / "voiceover.mp3"
    suffix = Path(source_name or "voiceover.mp3").suffix.lower()
    if suffix and suffix not in _AUDIO_EXTS and suffix != ".mp3":
        raise ValueError(f"Unsupported voiceover type {suffix}; use .mp3 / .wav / .m4a")
    dest.write_bytes(data)
    duration = _retime_script_from_voiceover(root)
    _write_voice_meta(root, voice="custom_upload", source="upload")
    logger.info(
        "Voiceover replaced via upload | path=%s | bytes=%d | duration=%.2fs",
        dest,
        len(data),
        duration,
    )
    return dest


def regenerate_voiceover(
    run_dir: Path | str,
    voice: str | None = None,
    *,
    on_progress=None,
) -> Path:
    """Re-run TTS for the job script with a new speaker voice."""
    from youtube_pipeline.audio.tts import AudioEngine

    root = Path(run_dir)
    script = _load_script_for_voiceover(root)
    selected = (voice or current_voice(root) or "en-US-ChristopherNeural").strip()
    if selected == "custom_upload":
        from youtube_pipeline.i18n import default_voice_for_language

        selected = default_voice_for_language(_job_language(root))

    engine = AudioEngine()
    result = engine.synthesize(
        script,
        root / "audio",
        voice=selected,
        use_per_scene_text=True,
        on_progress=on_progress,
    )
    write_json(root / "script_timed.json", result.script.model_dump(mode="json"))
    write_json(root / "timing.json", result.timing)
    _write_voice_meta(root, voice=selected, source="tts")
    logger.info(
        "Voiceover regenerated | voice=%s | duration=%.2fs | path=%s",
        selected,
        result.duration_seconds,
        result.audio_path,
    )
    return Path(result.audio_path)


def load_prompts(run_dir: Path | str) -> dict[str, Any]:
    root = Path(run_dir)
    prompts_path = root / "prompts.json"
    if prompts_path.exists():
        return json.loads(prompts_path.read_text(encoding="utf-8"))
    # Fall back to script_timed.json / script.json if prompts export is missing.
    for name in ("script_timed.json", "script.json"):
        script_path = root / name
        if not script_path.exists():
            continue
        script = read_json(script_path)
        scenes = []
        for scene in script.get("scenes", []):
            sid = int(scene["scene_id"])
            scenes.append(
                {
                    "scene_number": sid + 1,
                    "scene_id": sid,
                    "filename": f"scene_{sid:02d}.jpg",
                    "visual_prompt": scene.get("visual_prompt", ""),
                    "script_text": scene.get("script_text", ""),
                    "duration_seconds": float(scene.get("duration") or 0.0),
                    "aspect_ratio": script.get("aspect_ratio") or "16:9",
                }
            )
        return {
            "title": script.get("title", ""),
            "style": script.get("style", ""),
            "aspect_ratio": script.get("aspect_ratio") or "16:9",
            "scene_count": len(scenes),
            "scenes": scenes,
        }
    return {
        "title": "",
        "style": "",
        "aspect_ratio": "16:9",
        "scene_count": 0,
        "scenes": [],
    }


def write_prompt_pack(run_dir: Path | str) -> dict[str, Any]:
    """Write clipboard-friendly prompt files under ``prompts/`` and ``prompts_all.txt``."""
    root = Path(run_dir)
    payload = load_prompts(root)
    pack_dir = ensure_dir(root / "prompts")
    lines: list[str] = [
        f"Title: {payload.get('title', '')}",
        f"Style: {payload.get('style', '')}",
        f"Aspect ratio: {payload.get('aspect_ratio', '16:9')}",
        f"Scenes: {payload.get('scene_count', 0)}",
        "",
        "Copy each prompt into Meta AI / Gemini. Save images as the filename shown.",
        "",
    ]
    for scene in payload.get("scenes", []):
        sid = int(scene["scene_id"])
        filename = scene.get("filename") or f"scene_{sid:02d}.jpg"
        prompt = (scene.get("visual_prompt") or "").strip()
        block = (
            f"=== Scene {scene.get('scene_number', sid + 1)} → save as {filename} ===\n"
            f"{prompt}\n"
        )
        lines.append(block)
        (pack_dir / f"scene_{sid:02d}.txt").write_text(
            f"Save as: {filename}\n"
            f"Aspect ratio: {scene.get('aspect_ratio') or payload.get('aspect_ratio') or '16:9'}\n\n"
            f"{prompt}\n",
            encoding="utf-8",
        )

    all_txt = root / "prompts_all.txt"
    all_txt.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "prompts_dir": str(pack_dir.resolve()),
        "prompts_all_txt": str(all_txt.resolve()),
        "scene_count": int(payload.get("scene_count") or 0),
    }


def clipboard_text(run_dir: Path | str) -> str:
    """Return a single clipboard-ready string of all visual prompts."""
    root = Path(run_dir)
    pack = write_prompt_pack(root)
    return Path(pack["prompts_all_txt"]).read_text(encoding="utf-8")


def scene_image_path(run_dir: Path | str, scene_id: int) -> Path:
    return Path(run_dir) / "assets" / f"scene_{int(scene_id):02d}.jpg"


def _load_scene_sidecar(run_dir: Path, filename: str) -> dict[str, str]:
    path = run_dir / "assets" / filename
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
        if isinstance(payload, dict):
            return {str(key): str(value) for key, value in payload.items()}
    except Exception:  # noqa: BLE001
        logger.warning("Unable to read scene sidecar | path=%s", path)
    return {}


def _load_scene_errors(run_dir: Path) -> dict[str, str]:
    return _load_scene_sidecar(run_dir, "scene_errors.json")


def _load_scene_sources(run_dir: Path) -> dict[str, str]:
    return _load_scene_sidecar(run_dir, "scene_sources.json")


def _save_scene_errors(run_dir: Path, errors: dict[str, str]) -> None:
    write_json(ensure_dir(run_dir / "assets") / "scene_errors.json", errors)


def _clear_scene_error(run_dir: Path, scene_id: int) -> None:
    errors = _load_scene_errors(run_dir)
    if errors.pop(str(int(scene_id)), None) is not None:
        _save_scene_errors(run_dir, errors)


def _normalize_scene_source(source: str | None) -> str | None:
    if not source:
        return None
    return "gemini" if source in {"gemini_image", "imagen"} else source


def _remember_scene_source(run_dir: Path, scene_id: int, source: str | None) -> None:
    sources = _load_scene_sources(run_dir)
    key = str(int(scene_id))
    normalized = _normalize_scene_source(source)
    if normalized is None:
        sources.pop(key, None)
    else:
        sources[key] = normalized
    write_json(ensure_dir(run_dir / "assets") / "scene_sources.json", sources)


def save_scene_image(
    run_dir: Path | str,
    scene_id: int,
    data: bytes,
    *,
    source_name: str | None = None,
) -> Path:
    """Normalize and save an uploaded image to ``assets/scene_XX.jpg``."""
    root = Path(run_dir)
    expected = _expected_scene_count(root)
    sid = int(scene_id)
    if sid < 0 or (expected and sid >= expected):
        raise ValueError(f"scene_id {sid} out of range (0..{(expected or 1) - 1})")
    if len(data) < 256:
        raise ValueError("Uploaded image is empty or too small")

    assets = ensure_dir(root / "assets")
    dest = assets / f"scene_{sid:02d}.jpg"
    tmp = assets / f"_upload_{sid:02d}{Path(source_name or 'upload.jpg').suffix or '.jpg'}"
    tmp.write_bytes(data)
    try:
        with Image.open(tmp) as img:
            img.convert("RGB").save(dest, format="JPEG", quality=92)
    except Exception:
        # Raw copy fallback for already-valid JPEGs Pillow cannot re-encode.
        shutil.copy2(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)

    if dest.stat().st_size < 256:
        raise ValueError(f"Failed to write scene image: {dest}")
    _remember_scene_source(root, sid, "upload")
    _clear_scene_error(root, sid)
    logger.info("Scene image saved | scene=%d | path=%s | bytes=%d", sid, dest, dest.stat().st_size)
    return dest


def auto_fill_scene_images(
    run_dir: Path | str,
    *,
    force: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Fill missing scene images via the configured asset provider."""
    from youtube_pipeline.models import SceneData

    root = Path(run_dir)
    settings = get_settings()
    if settings.asset_provider == AssetProvider.MANUAL:
        return {
            "filled": 0,
            "skipped": 0,
            "failed": [],
            "provider": "manual",
            "skipped_manual": True,
        }

    provider = build_asset_provider(settings)
    scenes = load_prompts(root).get("scenes") or []
    total = len(scenes)
    filled = 0
    skipped = 0
    failed: list[dict[str, Any]] = []
    errors = _load_scene_errors(root)
    tmp_dir = ensure_dir(root / "assets" / "_gen")

    for index, scene in enumerate(scenes):
        sid = int(scene["scene_id"])
        dest = scene_image_path(root, sid)
        if dest.exists() and dest.stat().st_size > 256 and not force:
            skipped += 1
            continue
        if on_progress is not None:
            on_progress(index + 1, total, f"Generating scene {index + 1}/{total}")
        try:
            scene_data = SceneData(
                scene_id=sid,
                script_text=str(scene.get("script_text") or f"Scene {sid}"),
                visual_prompt=str(scene.get("visual_prompt") or ""),
            )
            asset = provider.fetch_for_scene(scene_data, tmp_dir)
            save_scene_image(
                root,
                sid,
                Path(asset.path).read_bytes(),
                source_name=Path(asset.path).name,
            )
            _remember_scene_source(root, sid, provider.name)
            errors.pop(str(sid), None)
            filled += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scene image auto-fill failed | scene=%s | %s", sid, exc)
            message = str(exc)
            if len(message) > 320:
                message = message[:317] + "..."
            failed.append({"scene_id": sid, "error": message})
            errors[str(sid)] = message
            # Daily/minute quota will fail every remaining scene — stop early.
            lowered = message.lower()
            if "quota" in lowered or "429" in lowered:
                remaining = [
                    int(item["scene_id"])
                    for item in scenes[index + 1 :]
                    if force
                    or not (
                        scene_image_path(root, int(item["scene_id"])).exists()
                        and scene_image_path(root, int(item["scene_id"])).stat().st_size > 256
                    )
                ]
                for rest_id in remaining:
                    note = message
                    failed.append({"scene_id": rest_id, "error": note})
                    errors[str(rest_id)] = note
                logger.warning(
                    "Aborting auto-fill after quota error | filled=%d | remaining=%d",
                    filled,
                    len(remaining),
                )
                break

    _save_scene_errors(root, errors)
    return {
        "filled": filled,
        "skipped": skipped,
        "failed": failed,
        "provider": provider.name,
    }


def generate_one_scene_image(run_dir: Path | str, scene_id: int) -> dict[str, Any]:
    """Force-generate one scene image via the configured asset provider."""
    from youtube_pipeline.models import SceneData

    root = Path(run_dir)
    settings = get_settings()
    if settings.asset_provider == AssetProvider.MANUAL:
        return {
            "filled": 0,
            "skipped": 0,
            "failed": [],
            "provider": "manual",
            "skipped_manual": True,
        }

    sid = int(scene_id)
    scenes = load_prompts(root).get("scenes") or []
    scene = next((item for item in scenes if int(item["scene_id"]) == sid), None)
    if scene is None:
        valid_ids = [int(item["scene_id"]) for item in scenes]
        if valid_ids:
            valid = f"{min(valid_ids)}..{max(valid_ids)}"
        else:
            valid = "none"
        raise ValueError(f"scene_id {sid} not found (valid scene ids: {valid})")

    provider = build_asset_provider(settings)
    errors = _load_scene_errors(root)
    try:
        scene_data = SceneData(
            scene_id=sid,
            script_text=str(scene.get("script_text") or f"Scene {sid}"),
            visual_prompt=str(scene.get("visual_prompt") or ""),
        )
        asset = provider.fetch_for_scene(
            scene_data,
            ensure_dir(root / "assets" / "_gen"),
        )
        save_scene_image(
            root,
            sid,
            Path(asset.path).read_bytes(),
            source_name=Path(asset.path).name,
        )
        _remember_scene_source(root, sid, provider.name)
        errors.pop(str(sid), None)
        failed: list[dict[str, Any]] = []
        filled = 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scene image generation failed | scene=%s | %s", sid, exc)
        message = str(exc)
        failed = [{"scene_id": sid, "error": message}]
        errors[str(sid)] = message
        filled = 0

    _save_scene_errors(root, errors)
    return {
        "filled": filled,
        "skipped": 0,
        "failed": failed,
        "provider": provider.name,
    }


def save_bgm_file(run_dir: Path | str, data: bytes, *, source_name: str | None = None) -> Path:
    """Save a custom BGM track to ``assets/bgm.mp3`` (composer looks for this name)."""
    if len(data) < 1024:
        raise ValueError("BGM file is empty or too small")
    assets = ensure_dir(Path(run_dir) / "assets")
    dest = assets / "bgm.mp3"
    suffix = Path(source_name or "bgm.mp3").suffix.lower()
    if suffix and suffix not in _AUDIO_EXTS and suffix != ".mp3":
        raise ValueError(f"Unsupported BGM type {suffix}; use .mp3 / .wav / .m4a")
    dest.write_bytes(data)
    logger.info("BGM replaced via upload | path=%s | bytes=%d", dest, len(data))
    return dest


def set_scene_ambience(run_dir: Path | str, scene_id: int, ambience: str) -> str:
    """Normalize and write ambience into script.json scenes; return stored value."""
    from youtube_pipeline.audio.sfx_tags import normalize_ambience

    root = Path(run_dir)
    sid = int(scene_id)
    stored = normalize_ambience(ambience)
    paths = [root / "script.json"]
    timed_path = root / "script_timed.json"
    if timed_path.exists():
        paths.append(timed_path)

    payloads: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    for path in paths:
        if not path.exists():
            raise ValueError(f"Script file missing: {path.name}")
        payload = read_json(path)
        scene = next(
            (item for item in payload.get("scenes", []) if int(item.get("scene_id", -1)) == sid),
            None,
        )
        if scene is None:
            raise ValueError(f"scene_id {sid} not found in {path.name}")
        payloads.append((path, payload, scene))

    for path, payload, scene in payloads:
        scene["ambience"] = stored
        write_json(path, payload)
    return stored


def refetch_bgm(run_dir: Path | str, style: str | None = None) -> Path | None:
    """Download a fresh BGM bed for ``style`` into ``assets/bgm.mp3``."""
    from youtube_pipeline.assets.provider import AssetService

    root = Path(run_dir)
    if style is None:
        req_path = root / "request.json"
        style = "cinematic"
        if req_path.exists():
            req = read_json(req_path)
            style = str(req.get("style") or style)
    assets = ensure_dir(root / "assets")
    # Remove previous track so fetch always writes a new file.
    old = assets / "bgm.mp3"
    if old.exists():
        old.unlink(missing_ok=True)
    path = AssetService().fetch_bgm(style or "cinematic", assets)
    return path


def _load_quiz_workspace(root: Path) -> dict[str, Any]:
    video_format = "narrative"
    quiz_mode: str | None = None
    request_path = root / "request.json"
    if request_path.exists():
        try:
            request = read_json(request_path)
            video_format = str(request.get("format") or video_format)
            quiz_mode = request.get("quiz_mode")
        except Exception:  # noqa: BLE001
            pass

    script = None
    for name in ("script.json", "script_timed.json"):
        path = root / name
        if not path.exists():
            continue
        try:
            from youtube_pipeline.models import VideoScript

            script = VideoScript.model_validate(read_json(path))
            video_format = script.format or video_format
            quiz_mode = script.quiz_mode or quiz_mode
            break
        except Exception:  # noqa: BLE001
            continue

    questions: list[dict[str, Any]] = []
    questions_path = root / "quiz_questions.json"
    if questions_path.exists():
        try:
            raw = read_json(questions_path)
            if isinstance(raw, list):
                questions = [item for item in raw if isinstance(item, dict)]
        except Exception:  # noqa: BLE001
            pass
    if not questions and script is not None:
        from youtube_pipeline.quiz.drafts import extract_quiz_questions

        questions = extract_quiz_questions(script)

    draft_path = root / "community_post_draft.txt"
    community_post_draft = ""
    if draft_path.exists():
        try:
            community_post_draft = draft_path.read_text(encoding="utf-8")
        except OSError:
            pass

    return {
        "format": video_format,
        "quiz_mode": quiz_mode,
        "quiz_answer_key": questions,
        "community_post_draft": community_post_draft,
    }


def workspace_status(run_dir: Path | str, *, job_id: str | None = None) -> dict[str, Any]:
    """Checklist of prompts, scene slots, and BGM for the HITL UI/API."""
    root = Path(run_dir)
    write_prompt_pack(root)
    payload = load_prompts(root)
    expected = int(payload.get("scene_count") or _expected_scene_count(root) or 0)
    assets = ensure_dir(root / "assets")
    # Accept Flow / browser downloads like scene_00.jpg_1730… → scene_00.jpg
    if expected > 0:
        normalize_loose_scene_images(assets, expected_scenes=expected)
    else:
        normalize_loose_scene_images(assets)
    scene_errors = _load_scene_errors(root)
    scene_sources = _load_scene_sources(root)
    scene_audio: dict[int, dict[str, Any]] = {}
    for script_name in ("script.json", "script_timed.json"):
        script_path = root / script_name
        if not script_path.exists():
            continue
        script = read_json(script_path)
        scene_audio = {
            int(item["scene_id"]): {
                "ambience": item.get("ambience", "none"),
                "sfx": item.get("sfx") or [],
            }
            for item in script.get("scenes", [])
        }
        break

    idea = ""
    req_path = root / "request.json"
    if req_path.exists():
        try:
            idea = str(read_json(req_path).get("idea") or "")
        except Exception:  # noqa: BLE001
            idea = ""

    scenes_out: list[dict[str, Any]] = []
    present = 0
    for scene in payload.get("scenes", []):
        sid = int(scene["scene_id"])
        path = find_scene_image(assets, sid)
        ready = path is not None
        if ready:
            present += 1
        scenes_out.append(
            {
                "scene_number": scene.get("scene_number", sid + 1),
                "scene_id": sid,
                "filename": f"scene_{sid:02d}.jpg",
                "visual_prompt": scene.get("visual_prompt", ""),
                "script_text": scene.get("script_text", ""),
                "duration_seconds": float(scene.get("duration_seconds") or 0),
                "ambience": scene_audio.get(sid, {}).get("ambience", "none"),
                "sfx": scene_audio.get(sid, {}).get("sfx", []),
                "ready": ready,
                "source": _normalize_scene_source(scene_sources.get(str(sid))),
                "error": scene_errors.get(str(sid)),
                "preview_url": (
                    f"/static/{job_id}/assets/scene_{sid:02d}.jpg"
                    if job_id and ready
                    else None
                ),
            }
        )

    bgm = assets / "bgm.mp3"
    bgm_ready = bgm.exists() and bgm.stat().st_size > 1024
    audio_path = root / "audio" / "voiceover.mp3"
    audio_ready = audio_path.exists() and audio_path.stat().st_size > 256
    script_path = root / "script.json"
    if not script_path.exists():
        script_path = root / "script_timed.json"
    script_ready = script_path.exists()
    video_candidates = sorted(root.glob("*.mp4"))
    video_ready = bool(video_candidates)
    srt_ready = any(root.glob("*.srt"))

    # Prefer aspect ratio from the original request when present.
    aspect_ratio = str(payload.get("aspect_ratio") or "16:9")
    if req_path.exists():
        try:
            req_aspect = str(read_json(req_path).get("aspect_ratio") or "").strip()
            if req_aspect:
                aspect_ratio = req_aspect
        except Exception:  # noqa: BLE001
            pass

    static_prefix = f"/static/{job_id}" if job_id else None
    quiz_workspace = _load_quiz_workspace(root)
    return {
        "run_dir": str(root.resolve()),
        "idea": idea,
        "title": payload.get("title", ""),
        "style": payload.get("style", ""),
        "aspect_ratio": aspect_ratio,
        "language": _job_language(root),
        **quiz_workspace,
        "scene_count": expected,
        "scenes_ready": present,
        "all_scenes_ready": present == expected and expected > 0,
        "audio_ready": audio_ready,
        "script_ready": script_ready,
        "video_ready": video_ready,
        "bgm_ready": bgm_ready,
        "audio_url": f"{static_prefix}/audio.mp3" if static_prefix and audio_ready else None,
        # Cache-bust key for the studio <audio> element after regen.
        "audio_version": (
            str(int(audio_path.stat().st_mtime_ns)) if audio_ready else None
        ),
        "script_url": f"{static_prefix}/script.json" if static_prefix and script_ready else None,
        "video_url": f"{static_prefix}/video.mp4" if static_prefix and video_ready else None,
        "subtitles_url": f"{static_prefix}/video.srt" if static_prefix and srt_ready else None,
        "bgm_url": f"{static_prefix}/bgm.mp3" if static_prefix and bgm_ready else None,
        "prompts_url": f"{static_prefix}/prompts.json" if static_prefix else None,
        "prompts_csv_url": f"{static_prefix}/prompts.csv" if static_prefix else None,
        "prompts_txt_url": f"{static_prefix}/prompts_all.txt" if static_prefix else None,
        "current_voice": current_voice(root),
        "voice_options": _voice_options(root),
        "clipboard_text": clipboard_text(root),
        "scenes": scenes_out,
    }


def publish_workspace_static(job_id: str, run_dir: Path | str, static_dir: Path | str) -> None:
    """Mirror script, audio, prompts, assets, and BGM into ``static/{job_id}/`` for the UI."""
    root = Path(run_dir)
    dest = ensure_dir(Path(static_dir) / job_id)
    write_prompt_pack(root)

    audio = root / "audio" / "voiceover.mp3"
    if audio.exists():
        shutil.copy2(audio, dest / "audio.mp3")

    for script_name in ("script.json", "script_timed.json"):
        script = root / script_name
        if script.exists():
            shutil.copy2(script, dest / "script.json")
            break

    for video in sorted(root.glob("*.mp4")):
        try:
            shutil.copy2(video, dest / "video.mp4")
            srt = video.with_suffix(".srt")
            if srt.exists():
                shutil.copy2(srt, dest / "video.srt")
        except OSError as exc:
            # Windows file lock while the browser/player has the MP4 open.
            logger.warning("Skipping static video publish (%s): %s", video.name, exc)
        break
    if not (dest / "video.srt").exists():
        for srt in sorted(root.glob("*.srt")):
            shutil.copy2(srt, dest / "video.srt")
            break

    for name in ("prompts.json", "prompts.csv", "prompts_all.txt", "PROMPTS_README.txt"):
        src = root / name
        if src.exists():
            shutil.copy2(src, dest / name)

    prompts_src = root / "prompts"
    if prompts_src.is_dir():
        prompts_dest = ensure_dir(dest / "prompts")
        for path in prompts_src.glob("scene_*.txt"):
            shutil.copy2(path, prompts_dest / path.name)

    assets_src = root / "assets"
    assets_dest = ensure_dir(dest / "assets")
    if assets_src.is_dir():
        expected = _expected_scene_count(root)
        normalize_loose_scene_images(
            assets_src, expected_scenes=expected if expected > 0 else None
        )
        for path in sorted(assets_src.glob("scene_*.jpg")):
            if path.stat().st_size > 256:
                shutil.copy2(
                    path,
                    assets_dest / f"scene_{_scene_id_from_name(path.name):02d}.jpg",
                )
        for path in sorted(assets_src.glob("scene_*.png")):
            sid = _scene_id_from_name(path.name)
            dest_jpg = assets_dest / f"scene_{sid:02d}.jpg"
            if dest_jpg.exists():
                continue
            try:
                with Image.open(path) as img:
                    img.convert("RGB").save(dest_jpg, format="JPEG", quality=90)
            except Exception:  # noqa: BLE001
                shutil.copy2(path, assets_dest / path.name)
        bgm = assets_src / "bgm.mp3"
        if bgm.exists() and bgm.stat().st_size > 1024:
            shutil.copy2(bgm, dest / "bgm.mp3")


def _scene_id_from_name(name: str) -> int:
    import re

    match = re.search(r"scene[_-]?0*(\d+)", name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)", name)
    return int(match.group(1)) if match else 0


def _expected_scene_count(run_dir: Path) -> int:
    prompts = run_dir / "prompts.json"
    if prompts.exists():
        data = json.loads(prompts.read_text(encoding="utf-8"))
        return int(data.get("scene_count") or len(data.get("scenes") or []))
    for name in ("script_timed.json", "script.json"):
        path = run_dir / name
        if path.exists():
            data = read_json(path)
            return len(data.get("scenes") or [])
    return 0

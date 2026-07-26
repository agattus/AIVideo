"""Human-in-the-loop workspace helpers: prompts pack, scene placement, BGM."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from youtube_pipeline.utils.files import ensure_dir, read_json
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}


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
    logger.info("Scene image saved | scene=%d | path=%s | bytes=%d", sid, dest, dest.stat().st_size)
    return dest


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


def workspace_status(run_dir: Path | str, *, job_id: str | None = None) -> dict[str, Any]:
    """Checklist of prompts, scene slots, and BGM for the HITL UI/API."""
    root = Path(run_dir)
    write_prompt_pack(root)
    payload = load_prompts(root)
    expected = int(payload.get("scene_count") or _expected_scene_count(root) or 0)
    assets = ensure_dir(root / "assets")
    scenes_out: list[dict[str, Any]] = []
    present = 0
    for scene in payload.get("scenes", []):
        sid = int(scene["scene_id"])
        path = assets / f"scene_{sid:02d}.jpg"
        alt = assets / f"scene_{sid:02d}.png"
        ready = (path.exists() and path.stat().st_size > 256) or (
            alt.exists() and alt.stat().st_size > 256
        )
        if ready:
            present += 1
        scenes_out.append(
            {
                "scene_number": scene.get("scene_number", sid + 1),
                "scene_id": sid,
                "filename": f"scene_{sid:02d}.jpg",
                "visual_prompt": scene.get("visual_prompt", ""),
                "script_text": scene.get("script_text", ""),
                "duration_seconds": scene.get("duration_seconds", 0),
                "ready": ready,
                "preview_url": (
                    f"/static/{job_id}/assets/scene_{sid:02d}.jpg"
                    if job_id and ready
                    else None
                ),
            }
        )

    bgm = assets / "bgm.mp3"
    bgm_ready = bgm.exists() and bgm.stat().st_size > 1024
    return {
        "run_dir": str(root.resolve()),
        "title": payload.get("title", ""),
        "style": payload.get("style", ""),
        "aspect_ratio": payload.get("aspect_ratio", "16:9"),
        "scene_count": expected,
        "scenes_ready": present,
        "all_scenes_ready": present == expected and expected > 0,
        "bgm_ready": bgm_ready,
        "bgm_url": f"/static/{job_id}/bgm.mp3" if job_id and bgm_ready else None,
        "prompts_url": f"/static/{job_id}/prompts.json" if job_id else None,
        "prompts_csv_url": f"/static/{job_id}/prompts.csv" if job_id else None,
        "prompts_txt_url": f"/static/{job_id}/prompts_all.txt" if job_id else None,
        "clipboard_text": clipboard_text(root),
        "scenes": scenes_out,
    }


def publish_workspace_static(job_id: str, run_dir: Path | str, static_dir: Path | str) -> None:
    """Mirror prompts pack + current assets/BGM into ``static/{job_id}/`` for the UI."""
    root = Path(run_dir)
    dest = ensure_dir(Path(static_dir) / job_id)
    write_prompt_pack(root)

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
        for path in assets_src.glob("scene_*.*"):
            if path.suffix.lower() in _IMAGE_EXTS:
                shutil.copy2(path, assets_dest / path.name)
        bgm = assets_src / "bgm.mp3"
        if bgm.exists() and bgm.stat().st_size > 1024:
            shutil.copy2(bgm, dest / "bgm.mp3")


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

"""Edge-TTS voice catalog and short sample previews."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

from youtube_pipeline.utils.files import ensure_dir
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_PREVIEW_TEXT = (
    "Welcome to your film. This is a short sample of how this narrator sounds."
)
_VOICE_CACHE: dict[str, Any] = {"fetched_at": 0.0, "voices": []}
_VOICE_CACHE_TTL_SECONDS = 6 * 60 * 60
_SAFE_VOICE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _run_async(factory):
    """Run an async factory from sync code (safe under FastAPI's event loop)."""
    from youtube_pipeline.utils.async_run import run_coro_sync

    return run_coro_sync(factory)


def _friendly_label(entry: dict[str, Any]) -> str:
    short = str(entry.get("ShortName") or "").strip()
    locale = str(entry.get("Locale") or "").strip()
    gender = str(entry.get("Gender") or "").strip()
    friendly = str(entry.get("FriendlyName") or "").strip()
    # "Microsoft Jenny Online (Natural) - English (United States)" → Jenny
    name = short
    if "-" in short:
        name = short.split("-")[-1].replace("Neural", "").replace("Multilingual", "")
    bits = [name or short or "Voice"]
    if locale:
        bits.append(locale)
    if gender:
        bits.append(gender.lower())
    label = " · ".join(bits)
    if friendly and name.lower() not in friendly.lower():
        return f"{label} — {friendly}"
    return label


def list_edge_voices(
    *,
    locale_prefix: str | None = "en",
    force_refresh: bool = False,
) -> list[dict[str, str]]:
    """Return Edge-TTS voices as ``{id, label, locale, gender}``.

    Defaults to English locales (``en``). Pass ``locale_prefix=None`` or ``"all"``
    for the full catalog.
    """
    now = time.time()
    cached = _VOICE_CACHE.get("voices") or []
    if (
        not force_refresh
        and cached
        and (now - float(_VOICE_CACHE.get("fetched_at") or 0)) < _VOICE_CACHE_TTL_SECONDS
    ):
        voices = cached
    else:
        import edge_tts

        async def _fetch() -> list[dict[str, Any]]:
            return await edge_tts.list_voices()

        raw = _run_async(_fetch)
        voices = []
        for entry in raw or []:
            short = str(entry.get("ShortName") or "").strip()
            if not short:
                continue
            voices.append(
                {
                    "id": short,
                    "label": _friendly_label(entry),
                    "locale": str(entry.get("Locale") or ""),
                    "gender": str(entry.get("Gender") or ""),
                }
            )
        voices.sort(key=lambda v: (v.get("locale") or "", v.get("gender") or "", v["id"]))
        _VOICE_CACHE["voices"] = voices
        _VOICE_CACHE["fetched_at"] = now
        logger.info("edge-tts list_voices cached | count=%d", len(voices))

    prefix = (locale_prefix or "").strip().lower()
    if not prefix or prefix in {"all", "*"}:
        return list(voices)
    return [
        v
        for v in voices
        if (v.get("locale") or "").lower().startswith(prefix)
        or (v.get("id") or "").lower().startswith(prefix)
    ]


def curated_fallback_voices() -> list[dict[str, str]]:
    """Offline fallback when list_voices cannot reach Microsoft."""
    return [
        {
            "id": "en-US-ChristopherNeural",
            "label": "Christopher · en-US · male",
            "locale": "en-US",
            "gender": "Male",
        },
        {
            "id": "en-US-GuyNeural",
            "label": "Guy · en-US · male",
            "locale": "en-US",
            "gender": "Male",
        },
        {
            "id": "en-US-DavisNeural",
            "label": "Davis · en-US · male",
            "locale": "en-US",
            "gender": "Male",
        },
        {
            "id": "en-US-JennyNeural",
            "label": "Jenny · en-US · female",
            "locale": "en-US",
            "gender": "Female",
        },
        {
            "id": "en-US-AriaNeural",
            "label": "Aria · en-US · female",
            "locale": "en-US",
            "gender": "Female",
        },
        {
            "id": "en-US-SaraNeural",
            "label": "Sara · en-US · female",
            "locale": "en-US",
            "gender": "Female",
        },
        {
            "id": "en-GB-RyanNeural",
            "label": "Ryan · en-GB · male",
            "locale": "en-GB",
            "gender": "Male",
        },
        {
            "id": "en-GB-SoniaNeural",
            "label": "Sonia · en-GB · female",
            "locale": "en-GB",
            "gender": "Female",
        },
        {
            "id": "en-AU-WilliamNeural",
            "label": "William · en-AU · male",
            "locale": "en-AU",
            "gender": "Male",
        },
        {
            "id": "en-AU-NatashaNeural",
            "label": "Natasha · en-AU · female",
            "locale": "en-AU",
            "gender": "Female",
        },
        {
            "id": "en-IN-PrabhatNeural",
            "label": "Prabhat · en-IN · male",
            "locale": "en-IN",
            "gender": "Male",
        },
        {
            "id": "en-IN-NeerjaNeural",
            "label": "Neerja · en-IN · female",
            "locale": "en-IN",
            "gender": "Female",
        },
    ]


def safe_list_edge_voices(*, locale_prefix: str | None = "en") -> list[dict[str, str]]:
    try:
        voices = list_edge_voices(locale_prefix=locale_prefix)
        if voices:
            return voices
    except Exception as exc:  # noqa: BLE001
        logger.warning("edge-tts list_voices failed (%s); using curated fallback", exc)
    prefix = (locale_prefix or "en").strip().lower()
    fallback = curated_fallback_voices()
    if not prefix or prefix in {"all", "*"}:
        return fallback
    return [
        v
        for v in fallback
        if (v.get("locale") or "").lower().startswith(prefix)
        or (v.get("id") or "").lower().startswith(prefix)
    ]


def preview_voice_mp3(
    voice: str,
    *,
    static_dir: Path | str,
    text: str | None = None,
) -> tuple[Path, str]:
    """Synthesize a short sample; return ``(path, /static/... url)``."""
    import edge_tts

    selected = (voice or "").strip()
    if not selected or not _SAFE_VOICE_RE.match(selected):
        raise ValueError(f"Invalid voice id: {voice!r}")

    sample = (text or DEFAULT_PREVIEW_TEXT).strip() or DEFAULT_PREVIEW_TEXT
    digest = hashlib.sha1(f"{selected}|{sample}".encode("utf-8")).hexdigest()[:12]
    dest_dir = ensure_dir(Path(static_dir) / "voice_previews")
    filename = f"{selected}_{digest}.mp3"
    dest = dest_dir / filename
    url = f"/static/voice_previews/{filename}"

    if dest.exists() and dest.stat().st_size > 64:
        return dest, url

    async def _run() -> None:
        communicate = edge_tts.Communicate(sample, selected)
        await communicate.save(str(dest))

    _run_async(_run)
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"edge-tts preview produced empty audio for {selected}")
    logger.info("edge-tts preview ready | voice=%s | path=%s", selected, dest)
    return dest, url

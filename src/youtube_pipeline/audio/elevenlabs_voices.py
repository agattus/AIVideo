"""ElevenLabs voice catalog and short sample previews."""

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
_VOICE_CACHE: dict[str, Any] = {"fetched_at": 0.0, "voices": [], "api_key_fp": ""}
_VOICE_CACHE_TTL_SECONDS = 30 * 60
# ElevenLabs voice ids are typically 20+ alphanumeric chars; allow hyphens/underscores.
_SAFE_VOICE_RE = re.compile(r"^[A-Za-z0-9_-]{10,128}$")


def _api_key() -> str:
    from config.settings import get_settings

    key = (get_settings().elevenlabs_api_key or "").strip()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is required to list ElevenLabs voices")
    return key


def _friendly_label(entry: Any) -> str:
    name = str(getattr(entry, "name", None) or "").strip() or "Voice"
    labels = getattr(entry, "labels", None) or {}
    if not isinstance(labels, dict):
        labels = {}
    gender = str(labels.get("gender") or "").strip()
    accent = str(labels.get("accent") or labels.get("language") or "").strip()
    age = str(labels.get("age") or "").strip()
    bits = [name]
    if accent:
        bits.append(accent)
    if gender:
        bits.append(gender.lower())
    if age:
        bits.append(age.lower())
    return " · ".join(bits)


def _normalize_gender(raw: str) -> str:
    value = (raw or "").strip().casefold()
    if value in {"male", "m", "masculine"}:
        return "Male"
    if value in {"female", "f", "feminine"}:
        return "Female"
    return (raw or "").strip().title()


# Free API keys can usually synthesize owned/cloned voices, not Voice Library premades.
_API_FRIENDLY_CATEGORIES = frozenset({"cloned", "generated", "professional", "high_quality"})


def _voice_category(entry: Any) -> str:
    return str(getattr(entry, "category", None) or "").strip().casefold()


def list_elevenlabs_voices(
    *,
    force_refresh: bool = False,
    api_usable_only: bool = False,
) -> list[dict[str, str]]:
    """Return ElevenLabs voices as ``{id, label, locale, gender, category}``."""
    from elevenlabs import ElevenLabs

    api_key = _api_key()
    key_fp = hashlib.sha1(api_key.encode("utf-8")).hexdigest()[:12]
    now = time.time()
    cached = _VOICE_CACHE.get("voices") or []
    if (
        not force_refresh
        and cached
        and _VOICE_CACHE.get("api_key_fp") == key_fp
        and (now - float(_VOICE_CACHE.get("fetched_at") or 0)) < _VOICE_CACHE_TTL_SECONDS
    ):
        voices = list(cached)
    else:
        client = ElevenLabs(api_key=api_key)
        response = client.voices.get_all()
        raw_voices = getattr(response, "voices", None) or response or []
        voices = []
        for entry in raw_voices:
            voice_id = str(
                getattr(entry, "voice_id", None) or getattr(entry, "id", None) or ""
            ).strip()
            if not voice_id:
                continue
            labels = getattr(entry, "labels", None) or {}
            if not isinstance(labels, dict):
                labels = {}
            category = _voice_category(entry)
            gender = _normalize_gender(str(labels.get("gender") or ""))
            locale = str(
                labels.get("language") or labels.get("accent") or labels.get("locale") or ""
            ).strip()
            label = _friendly_label(entry)
            if category == "premade":
                label = f"{label} (library — paid API)"
            voices.append(
                {
                    "id": voice_id,
                    "label": label,
                    "locale": locale,
                    "gender": gender,
                    "category": category,
                }
            )
        # Prefer owned/cloned voices first for casting defaults.
        voices.sort(
            key=lambda v: (
                0 if (v.get("category") or "") in _API_FRIENDLY_CATEGORIES else 1,
                v.get("label") or "",
                v["id"],
            )
        )
        _VOICE_CACHE["voices"] = voices
        _VOICE_CACHE["fetched_at"] = now
        _VOICE_CACHE["api_key_fp"] = key_fp
        logger.info("elevenlabs list_voices cached | count=%d", len(voices))

    if api_usable_only:
        usable = [
            v
            for v in voices
            if (v.get("category") or "") in _API_FRIENDLY_CATEGORIES
        ]
        return usable
    return list(voices)


def safe_list_elevenlabs_voices(*, api_usable_only: bool = False) -> list[dict[str, str]]:
    """List voices; return empty list on failure (caller may fall back)."""
    try:
        voices = list_elevenlabs_voices(api_usable_only=api_usable_only)
        return voices if voices else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("elevenlabs list_voices failed (%s)", exc)
        return []


def default_elevenlabs_voice_id() -> str | None:
    """Return configured default, else first API-friendly catalog voice."""
    from config.settings import get_settings

    configured = (get_settings().elevenlabs_voice_id or "").strip()
    if configured:
        return configured
    usable = safe_list_elevenlabs_voices(api_usable_only=True)
    if usable:
        return usable[0]["id"]
    voices = safe_list_elevenlabs_voices()
    if voices:
        return voices[0]["id"]
    return None


def is_elevenlabs_paid_plan_error(exc: BaseException) -> bool:
    """True when ElevenLabs rejects library voices on a free API plan."""
    text = f"{type(exc).__name__} {exc}".casefold()
    markers = (
        "paid_plan_required",
        "payment_required",
        "free users cannot use library voices",
        "status_code: 402",
        "status_code=402",
    )
    return any(marker in text for marker in markers)


ELEVENLABS_PAID_PLAN_MESSAGE = (
    "ElevenLabs free plans cannot use Voice Library voices via the API. "
    "Upgrade your ElevenLabs plan, add your own cloned voices, "
    "or set TTS_PROVIDER=edge-tts for free multi-voice dialogue."
)


def preview_voice_mp3(
    voice: str,
    *,
    static_dir: Path | str,
    text: str | None = None,
) -> tuple[Path, str]:
    """Synthesize a short ElevenLabs sample; return ``(path, /static/... url)``."""
    from elevenlabs import ElevenLabs

    selected = (voice or "").strip()
    if not selected or not _SAFE_VOICE_RE.match(selected):
        raise ValueError(f"Invalid ElevenLabs voice id: {voice!r}")

    sample = (text or DEFAULT_PREVIEW_TEXT).strip() or DEFAULT_PREVIEW_TEXT
    digest = hashlib.sha1(f"el|{selected}|{sample}".encode("utf-8")).hexdigest()[:12]
    dest_dir = ensure_dir(Path(static_dir) / "voice_previews")
    filename = f"el_{selected}_{digest}.mp3"
    dest = dest_dir / filename
    url = f"/static/voice_previews/{filename}"

    if dest.exists() and dest.stat().st_size > 64:
        return dest, url

    client = ElevenLabs(api_key=_api_key())
    audio_iter = client.text_to_speech.convert(
        voice_id=selected,
        text=sample,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    with dest.open("wb") as fh:
        for chunk in audio_iter:
            if chunk:
                fh.write(chunk)
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"ElevenLabs preview produced empty audio for {selected}")
    logger.info("elevenlabs preview ready | voice=%s | path=%s", selected, dest)
    return dest, url

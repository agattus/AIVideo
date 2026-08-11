"""Assign deterministic voices to dialogue cast members (Edge or ElevenLabs)."""

from __future__ import annotations

from typing import Any

from config.settings import TTSProvider, get_settings
from youtube_pipeline.audio.edge_voices import safe_list_edge_voices
from youtube_pipeline.i18n import (
    default_voice_for_language,
    locale_prefix_for_language,
)


def _cast_ids(cast: list[dict[str, Any]]) -> list[str]:
    if len(cast) not in {3, 4}:
        raise ValueError("Dialogue cast must contain 3 or 4 members")

    cast_ids = [str(member.get("id") or "").strip() for member in cast]
    if any(not cast_id for cast_id in cast_ids):
        raise ValueError("Every cast member must have a non-empty id")
    if len(set(cast_ids)) != len(cast_ids):
        raise ValueError("Dialogue cast ids must be unique")
    return cast_ids


def _gender_hint(member: dict[str, Any]) -> str:
    hint = str(member.get("gender_hint") or "").strip().casefold()
    return hint if hint in {"male", "female"} else ""


def _pick_distinct(
    cast: list[dict[str, Any]],
    cast_ids: list[str],
    voices: list[dict[str, str]],
    *,
    default_voice: str,
) -> dict[str, str]:
    used: set[str] = set()
    assignments: dict[str, str] = {}

    for cast_id, member in zip(cast_ids, cast, strict=True):
        hint = _gender_hint(member)
        matching_unused = [
            voice
            for voice in voices
            if voice["id"] not in used
            and (not hint or str(voice.get("gender") or "").casefold() == hint)
        ]
        any_unused = [voice for voice in voices if voice["id"] not in used]
        matching = [
            voice
            for voice in voices
            if not hint or str(voice.get("gender") or "").casefold() == hint
        ]
        candidates = matching_unused or any_unused or matching or voices
        selected = candidates[0]["id"] if candidates else default_voice
        assignments[cast_id] = selected
        used.add(selected)

    return assignments


def _assign_edge_voices(
    cast: list[dict[str, Any]],
    *,
    language: str = "en",
) -> dict[str, str]:
    cast_ids = _cast_ids(cast)
    locale_prefix = locale_prefix_for_language(language).casefold()
    voices = safe_list_edge_voices(locale_prefix=locale_prefix)
    default_voice = default_voice_for_language(language)
    return _pick_distinct(cast, cast_ids, voices, default_voice=default_voice)


def _assign_elevenlabs_voices(cast: list[dict[str, Any]]) -> dict[str, str]:
    from youtube_pipeline.audio.elevenlabs_voices import (
        default_elevenlabs_voice_id,
        safe_list_elevenlabs_voices,
    )

    cast_ids = _cast_ids(cast)
    # Prefer owned/cloned voices — free API keys cannot synthesize library premades.
    voices = safe_list_elevenlabs_voices(api_usable_only=True) or safe_list_elevenlabs_voices()
    if not voices:
        raise ValueError(
            "No ElevenLabs voices available. Check ELEVENLABS_API_KEY and account voices."
        )
    default_voice = default_elevenlabs_voice_id() or voices[0]["id"]
    return _pick_distinct(cast, cast_ids, voices, default_voice=default_voice)


def assign_voices(
    cast: list[dict[str, Any]],
    *,
    language: str = "en",
    provider: TTSProvider | str | None = None,
) -> dict[str, str]:
    """Map cast ids to distinct provider voice ids."""
    selected = provider
    if selected is None:
        try:
            selected = get_settings().tts_provider
        except Exception:  # noqa: BLE001
            selected = TTSProvider.EDGE_TTS
    if isinstance(selected, str):
        selected = selected.strip().lower()

    if selected in {TTSProvider.ELEVENLABS, "elevenlabs"}:
        return _assign_elevenlabs_voices(cast)
    return _assign_edge_voices(cast, language=language)

"""Assign deterministic, offline Edge-TTS voices to dialogue cast members."""

from __future__ import annotations

from typing import Any

from youtube_pipeline.audio.edge_voices import curated_fallback_voices
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


def assign_voices(
    cast: list[dict[str, Any]],
    *,
    language: str = "en",
) -> dict[str, str]:
    """Map cast ids to deterministic Edge voice ids without network access."""
    cast_ids = _cast_ids(cast)
    locale_prefix = locale_prefix_for_language(language).casefold()
    voices = [
        voice
        for voice in curated_fallback_voices()
        if str(voice.get("locale") or "").casefold().startswith(locale_prefix)
    ]
    default_voice = default_voice_for_language(language)
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

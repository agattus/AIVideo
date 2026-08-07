"""Prompt builders for structured multi-speaker dialogue generation."""

from __future__ import annotations

import json

from youtube_pipeline.i18n import normalize_language, script_language_name
from youtube_pipeline.script_engine.schema import DIALOGUE_SCRIPT_SCHEMA


def _language_name(language: str) -> str:
    return script_language_name(normalize_language(language))


def build_dialogue_system_prompt(language: str) -> str:
    """Build the format-specific system instruction for dialogue scripts."""
    language_name = _language_name(language)
    return (
        "You create dramatic multi-speaker video dialogue as strict JSON. "
        f"Create 3 or 4 cast members, 8 to 16 dialogue lines, and 4 to 6 "
        f"visual beats. Write title, cast names, and every line text in "
        f"{language_name}, using its native script rather than transliteration. "
        "Keep cast ids and speaker_id values as short stable ASCII identifiers. "
        "Every speaker_id must match a cast id. Visual beats must cover every "
        "dialogue line exactly once using inclusive, contiguous line_start and "
        "line_end indexes. Write every visual_prompt in English and describe "
        "characters consistently. Return only JSON matching this schema: "
        f"{json.dumps(DIALOGUE_SCRIPT_SCHEMA, separators=(',', ':'))}"
    )


def build_dialogue_user_prompt(idea: str, language: str) -> str:
    """Build the user prompt for one dialogue request."""
    language_name = _language_name(language)
    return (
        f"Create a dialogue-driven video about: {idea}\n"
        f"Use 3 or 4 cast members, 8 to 16 lines, and 4 to 6 visual beats. "
        f"Write natural, language-correct dialogue in {language_name} native script. "
        "Write visual_prompt fields in English. Cover all line indexes exactly once "
        "across the visual beats. Return a single JSON object with title, cast, "
        "lines, and visual_beats."
    )

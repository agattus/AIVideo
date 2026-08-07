"""Prompt builders for structured multi-speaker dialogue generation."""

from __future__ import annotations

import json

from youtube_pipeline.i18n import normalize_language, script_language_name
from youtube_pipeline.script_engine.schema import DIALOGUE_SCRIPT_SCHEMA


def _language_name(language: str) -> str:
    return script_language_name(normalize_language(language))


def resolve_dialogue_line_budget(
    *,
    duration_seconds: int | None,
    max_scenes: int,
) -> int:
    """Choose an exact dialogue line count within the supported 8–16 line grammar."""
    duration = max(15, min(3600, int(duration_seconds or 75)))
    duration_budget = round(duration / 6)
    scene_ceiling = max(8, min(16, int(max_scenes)))
    return max(8, min(scene_ceiling, duration_budget))


def build_dialogue_system_prompt(language: str, *, line_count: int) -> str:
    """Build the format-specific system instruction for dialogue scripts."""
    language_name = _language_name(language)
    return (
        "You create dramatic multi-speaker video dialogue as strict JSON. "
        f"Create 3 or 4 cast members and exactly {line_count} dialogue lines "
        f"(within the supported 8 to 16 line range). Write title, "
        f"cast names, and every line text in "
        f"{language_name}, using its native script rather than transliteration. "
        "Keep cast ids and speaker_id values as short stable ASCII identifiers. "
        "Every speaker_id must match a cast id. Create one visual per dialogue line. "
        "Either add a unique cinematic visual_prompt to every object in lines and "
        "omit visual_beats, or return visual_beats with exactly one beat per line, "
        "where line_start == line_end. When visual_beats are present, they must "
        "cover every dialogue line exactly once using inclusive, contiguous indexes. "
        "Multi-line visual beats are discouraged; the pipeline will split them. "
        "Write every visual_prompt in English and describe characters consistently. "
        "Return only JSON matching this schema: "
        f"{json.dumps(DIALOGUE_SCRIPT_SCHEMA, separators=(',', ':'))}"
    )


def build_dialogue_user_prompt(
    idea: str,
    language: str,
    *,
    line_count: int,
) -> str:
    """Build the user prompt for one dialogue request."""
    language_name = _language_name(language)
    return (
        f"Create a dialogue-driven video about: {idea}\n"
        f"Use 3 or 4 cast members and exactly {line_count} dialogue lines "
        f"(within the supported 8 to 16 line range). Create one visual per dialogue "
        "line. Either put a unique cinematic visual_prompt on every line and omit "
        "visual_beats, or provide exactly one visual beat per line, where "
        "line_start == line_end. Multi-line visual beats are discouraged; the "
        "pipeline will split them. "
        f"Write natural, language-correct dialogue in {language_name} native script. "
        "Write visual_prompt fields in English. If visual_beats are present, cover "
        "all line indexes exactly once. Return a single JSON object with title, "
        "cast, lines, and optional visual_beats."
    )

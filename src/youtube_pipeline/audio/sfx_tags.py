"""Normalize scene sound tags and infer missing tags from scene text."""

from __future__ import annotations

import re
from typing import Any

from youtube_pipeline.models import AMBIENCE_TAGS, ONESHOT_TAGS, SceneData, SfxCue

_AMBIENCE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rain", ("rain", "storm", "drizzle", "downpour")),
    ("forest", ("forest", "jungle", "woods")),
    ("city", ("city", "street", "traffic", "alley", "skyline", "rooftop", "roof")),
    ("ocean", ("ocean", "sea", "beach", "waves", "harbor")),
    ("fire", ("fire", "campfire", "flames")),
    ("night", ("night", "midnight", "moonlit", "moonlight", "nocturnal")),
    ("wind", ("wind", "gale", "breeze", "gust")),
    ("room", ("indoor", "office", "hallway", "apartment", "interior")),
)
_ONESHOT_KEYWORDS: tuple[tuple[str, tuple[str, ...], float], ...] = (
    ("thunder", ("thunder", "lightning"), 0.45),
    ("footsteps", ("footstep", "footsteps", "walking"), 0.35),
    ("door", ("door", "doorway"), 0.5),
    ("birds", ("bird", "birds", "birdsong"), 0.4),
    ("crowd_cheer", ("crowd", "cheer", "cheering"), 0.6),
    ("whoosh", ("whoosh", "swoosh"), 0.5),
)


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords)


def normalize_ambience(raw: str | None) -> str:
    """Normalize unsupported or absent ambience tags to ``none``."""

    normalized = raw.strip().lower() if isinstance(raw, str) else "none"
    return normalized if normalized in AMBIENCE_TAGS else "none"


def normalize_sfx(cues: list[Any] | None) -> list[SfxCue]:
    """Drop unsupported cues, clamp positions, and retain at most two."""

    if not isinstance(cues, list):
        return []
    normalized: list[SfxCue] = []
    for raw in cues:
        try:
            cue = raw if isinstance(raw, SfxCue) else SfxCue.model_validate(raw)
        except (TypeError, ValueError):
            continue
        if cue.tag not in ONESHOT_TAGS:
            continue
        normalized.append(cue)
        if len(normalized) == 2:
            break
    return normalized


def infer_sfx_from_text(
    script_text: str,
    visual_prompt: str = "",
) -> tuple[str, list[SfxCue]]:
    """Infer supported ambience and one-shots using deterministic keywords."""

    combined = f"{script_text or ''} {visual_prompt or ''}".lower()
    ambience = "none"
    for tag, keywords in _AMBIENCE_KEYWORDS:
        if _contains_keyword(combined, keywords):
            ambience = tag
            break

    cues = [
        SfxCue(tag=tag, at=position)
        for tag, keywords, position in _ONESHOT_KEYWORDS
        if _contains_keyword(combined, keywords)
    ]
    return ambience, cues[:2]


def apply_sfx_fallback(scene: SceneData) -> SceneData:
    """Fill tags only when a scene has neither ambience nor one-shot cues."""

    if normalize_ambience(scene.ambience) != "none" or scene.sfx:
        return scene
    ambience, cues = infer_sfx_from_text(scene.script_text, scene.visual_prompt)
    return scene.model_copy(update={"ambience": ambience, "sfx": cues})

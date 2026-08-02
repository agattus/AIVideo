"""Resolve files from the bundled offline ambience and one-shot pack."""

from __future__ import annotations

from pathlib import Path

from youtube_pipeline.models import AMBIENCE_TAGS, ONESHOT_TAGS


def _default_pack_root() -> Path:
    return Path(__file__).resolve().parents[3] / "assets" / "sfx"


def _resolve(tag: str, category: str, allowed: frozenset[str], root: Path | None) -> Path | None:
    normalized = tag.strip().lower() if isinstance(tag, str) else ""
    if normalized not in allowed:
        return None
    candidate = (root or _default_pack_root()) / category / f"{normalized}.mp3"
    return candidate if candidate.is_file() else None


def resolve_ambience_path(tag: str, root: Path | None = None) -> Path | None:
    """Return an ambience file when its tag and bundled file both exist."""

    if tag.strip().lower() == "none":
        return None
    return _resolve(tag, "ambiences", AMBIENCE_TAGS, root)


def resolve_oneshot_path(tag: str, root: Path | None = None) -> Path | None:
    """Return a one-shot file when its tag and bundled file both exist."""

    return _resolve(tag, "oneshots", ONESHOT_TAGS, root)

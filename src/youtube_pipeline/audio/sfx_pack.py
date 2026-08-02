"""Resolve files from the bundled offline ambience and one-shot pack."""

from __future__ import annotations

import os
from pathlib import Path

from youtube_pipeline.models import AMBIENCE_TAGS, ONESHOT_TAGS
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


def _default_pack_root() -> Path:
    env = (os.getenv("SFX_PACK_DIR") or "").strip()
    if env:
        return Path(env)
    # src/youtube_pipeline/audio/sfx_pack.py → repo root /assets/sfx
    return Path(__file__).resolve().parents[3] / "assets" / "sfx"


def _resolve(tag: str, category: str, allowed: frozenset[str], root: Path | None) -> Path | None:
    normalized = tag.strip().lower() if isinstance(tag, str) else ""
    if normalized not in allowed:
        return None
    pack = root or _default_pack_root()
    candidate = pack / category / f"{normalized}.mp3"
    if candidate.is_file():
        return candidate
    logger.debug("SFX pack miss | tag=%s | path=%s", normalized, candidate)
    return None


def resolve_ambience_path(tag: str, root: Path | None = None) -> Path | None:
    """Return an ambience file when its tag and bundled file both exist."""

    if tag.strip().lower() == "none":
        return None
    return _resolve(tag, "ambiences", AMBIENCE_TAGS, root)


def resolve_oneshot_path(tag: str, root: Path | None = None) -> Path | None:
    """Return a one-shot file when its tag and bundled file both exist."""

    return _resolve(tag, "oneshots", ONESHOT_TAGS, root)

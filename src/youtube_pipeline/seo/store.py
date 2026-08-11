"""Persist YouTube SEO packs on disk."""

from __future__ import annotations

from pathlib import Path

from youtube_pipeline.seo.models import YoutubePack
from youtube_pipeline.utils.files import read_json, write_json

_PACK_FILENAME = "youtube_metadata.json"


def pack_path(run_dir: Path | str) -> Path:
    return Path(run_dir) / _PACK_FILENAME


def save_youtube_pack(run_dir: Path | str, pack: YoutubePack) -> Path:
    return write_json(pack_path(run_dir), pack.model_dump(mode="json"))


def load_youtube_pack(run_dir: Path | str) -> YoutubePack | None:
    path = pack_path(run_dir)
    if not path.exists():
        return None
    try:
        return YoutubePack.model_validate(read_json(path))
    except Exception:  # noqa: BLE001
        return None

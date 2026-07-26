"""Filesystem helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify(text: str, *, max_length: int = 60) -> str:
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    if not slug:
        slug = "video"
    return slug[:max_length].rstrip("-")


def write_json(path: Path, data: Any) -> Path:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))

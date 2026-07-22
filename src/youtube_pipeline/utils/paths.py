"""Ensure repo root and ``src/`` are on ``sys.path`` for local Windows/uvicorn runs.

The package imports ``config.settings`` from the repo root and ``youtube_pipeline``
from ``src/``. Editable installs cover this, but ``uvicorn src.youtube_pipeline...``
on Windows often leaves ``config`` unimportable inside background threads.
"""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_project_paths() -> list[str]:
    """Insert repo root and ``src`` at the front of ``sys.path`` if missing."""
    # .../src/youtube_pipeline/utils/paths.py -> parents[3] == repo root
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    src_dir = repo_root / "src"

    added: list[str] = []
    for path in (repo_root, src_dir):
        text = str(path)
        if path.is_dir() and text not in sys.path:
            sys.path.insert(0, text)
            added.append(text)

    # Also honor the current working directory when the app is started from the repo.
    cwd = Path.cwd()
    for path in (cwd, cwd / "src"):
        text = str(path)
        if path.is_dir() and text not in sys.path:
            sys.path.insert(0, text)
            added.append(text)

    return added

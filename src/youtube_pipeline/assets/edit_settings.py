"""Persist Studio Edit panel options beside a job run directory."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from youtube_pipeline.utils.files import read_json, write_json

DEFAULT_EDIT_SETTINGS: dict[str, Any] = {
    "burn_captions": True,
    "caption_size": "m",
    "caption_position": "bottom",
}
_ALLOWED_SIZES = {"s", "m", "l"}
_ALLOWED_POSITIONS = {"bottom", "lower_third"}


def _normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(DEFAULT_EDIT_SETTINGS)
    if not isinstance(raw, dict):
        return data
    if "burn_captions" in raw:
        data["burn_captions"] = bool(raw["burn_captions"])
    size = str(raw.get("caption_size") or data["caption_size"]).lower()
    if size not in _ALLOWED_SIZES:
        raise ValueError(f"caption_size must be one of {sorted(_ALLOWED_SIZES)}")
    data["caption_size"] = size
    pos = str(raw.get("caption_position") or data["caption_position"]).lower()
    if pos not in _ALLOWED_POSITIONS:
        raise ValueError(f"caption_position must be one of {sorted(_ALLOWED_POSITIONS)}")
    data["caption_position"] = pos
    return data


def load_edit_settings(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "edit_settings.json"
    if not path.exists():
        return dict(DEFAULT_EDIT_SETTINGS)
    try:
        return _normalize(read_json(path))
    except Exception:
        return dict(DEFAULT_EDIT_SETTINGS)


def save_edit_settings(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    current = load_edit_settings(run_dir)
    merged = {**current, **(payload or {})}
    normalized = _normalize(merged)
    write_json(Path(run_dir) / "edit_settings.json", normalized)
    return normalized

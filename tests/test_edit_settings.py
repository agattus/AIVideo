from pathlib import Path

from youtube_pipeline.assets.edit_settings import load_edit_settings, save_edit_settings


def test_load_defaults_when_missing(tmp_path: Path) -> None:
    data = load_edit_settings(tmp_path)
    assert data["burn_captions"] is True
    assert data["caption_size"] == "m"
    assert data["caption_position"] == "bottom"


def test_save_roundtrip(tmp_path: Path) -> None:
    saved = save_edit_settings(
        tmp_path,
        {"burn_captions": False, "caption_size": "l", "caption_position": "lower_third"},
    )
    assert saved["burn_captions"] is False
    assert load_edit_settings(tmp_path)["caption_size"] == "l"


def test_rejects_invalid_size(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError):
        save_edit_settings(tmp_path, {"caption_size": "xl"})

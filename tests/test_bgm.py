"""Tests for BGM acquisition and voiceover/BGM mixing."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from youtube_pipeline.assets.provider import STYLE_BGM_QUERIES, AssetService
from youtube_pipeline.video.composer import VideoComposer


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        content: bytes = b"",
    ):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _service(tmp_path: Path) -> AssetService:
    from config.settings import Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        pexels_api_key="pexels-test",
        openai_api_key="openai-test",
    )
    return AssetService(settings)


def test_style_bgm_queries_cover_cinematic_and_suspense() -> None:
    assert "cinematic" in STYLE_BGM_QUERIES
    assert "suspense" in STYLE_BGM_QUERIES
    assert STYLE_BGM_QUERIES["cinematic"]


def test_fetch_bgm_from_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path)
    assets_dir = tmp_path / "assets"
    mp3_bytes = b"ID3" + b"\x00" * 4096

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None, headers=None):
            url_s = str(url)
            if "advancedsearch.php" in url_s:
                return _FakeResponse(
                    200,
                    {
                        "response": {
                            "docs": [{"identifier": "demo-track", "title": "Demo"}]
                        }
                    },
                )
            if "/metadata/" in url_s:
                return _FakeResponse(
                    200,
                    {
                        "files": [
                            {"name": "track.mp3", "size": "4000000"},
                            {"name": "track_spectrogram.png", "size": "1000"},
                        ]
                    },
                )
            if url_s.endswith(".mp3") or "/download/" in url_s:
                return _FakeResponse(200, content=mp3_bytes)
            return _FakeResponse(404, {})

    monkeypatch.setattr("youtube_pipeline.assets.provider.httpx.Client", _Client)

    path = service.fetch_bgm("cinematic", assets_dir)
    assert path is not None
    assert path.name == "bgm.mp3"
    assert path.exists()
    assert path.stat().st_size > 1024


def test_fetch_bgm_static_fallback_when_archive_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    assets_dir = tmp_path / "assets"
    mp3_bytes = b"ID3" + b"\x00" * 4096

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None, headers=None):
            url_s = str(url)
            if "advancedsearch.php" in url_s:
                return _FakeResponse(200, {"response": {"docs": []}})
            if "soundhelix.com" in url_s or url_s.endswith(".mp3"):
                return _FakeResponse(200, content=mp3_bytes)
            return _FakeResponse(404, {})

    monkeypatch.setattr("youtube_pipeline.assets.provider.httpx.Client", _Client)

    path = service.fetch_bgm("suspense", assets_dir)
    assert path is not None
    assert path.name == "bgm.mp3"
    assert path.read_bytes() == mp3_bytes


def test_fetch_bgm_graceful_skip_when_all_sources_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    assets_dir = tmp_path / "assets"

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None, headers=None):
            raise RuntimeError("network down")

    monkeypatch.setattr("youtube_pipeline.assets.provider.httpx.Client", _Client)

    path = service.fetch_bgm("cinematic", assets_dir)
    assert path is None
    assert not (assets_dir / "bgm.mp3").exists()


def test_mix_voiceover_skips_missing_bgm(tmp_path: Path) -> None:
    from config.settings import Settings

    composer = VideoComposer(
        Settings(
            output_dir=tmp_path / "out",
            assets_cache_dir=tmp_path / "cache",
            openai_api_key="test",
        )
    )
    voiceover = MagicMock()
    voiceover.duration = 12.0

    mixed, bgm, used = composer._mix_voiceover_with_bgm(
        voiceover=voiceover,
        bgm_path=tmp_path / "missing-bgm.mp3",
        duration=12.0,
    )
    assert mixed is voiceover
    assert bgm is None
    assert used is False


def test_mix_voiceover_loops_and_ducks_bgm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import Settings

    composer = VideoComposer(
        Settings(
            output_dir=tmp_path / "out",
            assets_cache_dir=tmp_path / "cache",
            openai_api_key="test",
        )
    )
    bgm_path = tmp_path / "bgm.mp3"
    bgm_path.write_bytes(b"ID3" + b"\x00" * 2048)

    voiceover = MagicMock(name="voiceover")
    voiceover.duration = 30.0

    bgm_raw = MagicMock(name="bgm_raw")
    bgm_raw.duration = 5.0
    bgm_looped = MagicMock(name="bgm_looped")
    bgm_looped.duration = 30.0
    bgm_raw.with_effects.return_value = bgm_looped

    mixed_clip = MagicMock(name="mixed")
    mixed_clip.with_duration.return_value = mixed_clip

    monkeypatch.setattr(
        "youtube_pipeline.video.composer.AudioFileClip",
        lambda path: bgm_raw,
    )
    monkeypatch.setattr(
        "youtube_pipeline.video.composer.CompositeAudioClip",
        lambda clips: mixed_clip,
    )

    mixed, bgm, used = composer._mix_voiceover_with_bgm(
        voiceover=voiceover,
        bgm_path=bgm_path,
        duration=30.0,
    )

    assert used is True
    assert bgm is bgm_raw
    assert mixed is mixed_clip
    bgm_raw.with_effects.assert_called_once()
    effects = bgm_raw.with_effects.call_args[0][0]
    assert len(effects) == 2
    # afx.AudioLoop + afx.MultiplyVolume(0.08)
    assert effects[0].__class__.__name__ == "AudioLoop"
    assert effects[1].__class__.__name__ == "MultiplyVolume"
    assert float(getattr(effects[1], "factor", getattr(effects[1], "volume", 0.08))) == pytest.approx(
        0.08
    )


def test_mix_voiceover_survives_bgm_load_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import Settings

    composer = VideoComposer(
        Settings(
            output_dir=tmp_path / "out",
            assets_cache_dir=tmp_path / "cache",
            openai_api_key="test",
        )
    )
    bgm_path = tmp_path / "bgm.mp3"
    bgm_path.write_bytes(b"ID3" + b"\x00" * 2048)
    voiceover = MagicMock()
    voiceover.duration = 10.0

    def _boom(_path: str):
        raise RuntimeError("bad mp3")

    monkeypatch.setattr("youtube_pipeline.video.composer.AudioFileClip", _boom)

    mixed, bgm, used = composer._mix_voiceover_with_bgm(
        voiceover=voiceover,
        bgm_path=bgm_path,
        duration=10.0,
    )
    assert mixed is voiceover
    assert bgm is None
    assert used is False

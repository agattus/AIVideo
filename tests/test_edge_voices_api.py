"""Tests for Edge-TTS voice list + preview API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from youtube_pipeline.audio.edge_voices import (
    curated_fallback_voices,
    list_edge_voices,
    preview_voice_mp3,
    safe_list_edge_voices,
)
from youtube_pipeline.api.schemas import GenerateVideoRequest


def test_generate_request_accepts_voice() -> None:
    req = GenerateVideoRequest(idea="Matsya Avatar myth", voice="en-US-JennyNeural")
    assert req.voice == "en-US-JennyNeural"


def test_safe_list_falls_back_when_list_fails(monkeypatch) -> None:
    def boom(**_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(
        "youtube_pipeline.audio.edge_voices.list_edge_voices",
        boom,
    )
    voices = safe_list_edge_voices(locale_prefix="en")
    assert len(voices) >= 6
    assert any(v["id"] == "en-US-ChristopherNeural" for v in voices)


def test_list_edge_voices_filters_locale(monkeypatch) -> None:
    sample = [
        {
            "ShortName": "en-US-JennyNeural",
            "Locale": "en-US",
            "Gender": "Female",
            "FriendlyName": "Microsoft Jenny",
        },
        {
            "ShortName": "hi-IN-SwaraNeural",
            "Locale": "hi-IN",
            "Gender": "Female",
            "FriendlyName": "Microsoft Swara",
        },
    ]

    async def fake_list():
        return sample

    import edge_tts

    monkeypatch.setattr(edge_tts, "list_voices", fake_list)
    # Clear cache
    from youtube_pipeline.audio import edge_voices as mod

    mod._VOICE_CACHE["voices"] = []
    mod._VOICE_CACHE["fetched_at"] = 0.0

    en = list_edge_voices(locale_prefix="en", force_refresh=True)
    assert len(en) == 1
    assert en[0]["id"] == "en-US-JennyNeural"

    all_voices = list_edge_voices(locale_prefix="all", force_refresh=False)
    # Cache already populated with all raw voices before filter — force refresh again
    mod._VOICE_CACHE["fetched_at"] = 0.0
    all_voices = list_edge_voices(locale_prefix="all", force_refresh=True)
    assert len(all_voices) == 2


def test_preview_voice_mp3_writes_file(tmp_path: Path, monkeypatch) -> None:
    class FakeCommunicate:
        def __init__(self, text: str, voice: str) -> None:
            self.text = text
            self.voice = voice

        async def save(self, path: str) -> None:
            Path(path).write_bytes(b"ID3preview")

    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate)
    path, url = preview_voice_mp3("en-US-JennyNeural", static_dir=tmp_path)
    assert path.exists()
    assert path.read_bytes() == b"ID3preview"
    assert url.startswith("/static/voice_previews/en-US-JennyNeural_")


def test_voices_endpoints(tmp_path: Path) -> None:
    fake_voices = curated_fallback_voices()
    with (
        patch(
            "youtube_pipeline.audio.edge_voices.safe_list_edge_voices",
            return_value=fake_voices,
        ),
        patch(
            "youtube_pipeline.audio.edge_voices.list_edge_voices",
            return_value=fake_voices,
        ),
        patch(
            "youtube_pipeline.audio.edge_voices.preview_voice_mp3",
            return_value=(tmp_path / "x.mp3", "/static/voice_previews/x.mp3"),
        ),
        patch("youtube_pipeline.api.main.STATIC_DIR", tmp_path),
    ):
        (tmp_path / "x.mp3").write_bytes(b"abc")
        from youtube_pipeline.api.main import app

        client = TestClient(app)
        listed = client.get("/api/v1/voices?locale=en")
        assert listed.status_code == 200
        body = listed.json()
        assert body["count"] >= 6
        assert body["voices"][0]["id"]

        preview = client.post(
            "/api/v1/voices/preview",
            json={"voice": "en-US-JennyNeural"},
        )
        assert preview.status_code == 200
        assert "preview_url" in preview.json()
        assert preview.json()["voice"] == "en-US-JennyNeural"

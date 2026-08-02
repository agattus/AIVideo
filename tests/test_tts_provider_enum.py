from __future__ import annotations

from config.settings import Settings, TTSProvider


def test_tts_provider_accepts_gtts() -> None:
    settings = Settings(tts_provider="gtts")
    assert settings.tts_provider == TTSProvider.GTTS
    assert settings.tts_provider.value == "gtts"


def test_tts_provider_accepts_edge_tts() -> None:
    settings = Settings(
        tts_provider="edge-tts",
        edge_tts_voice="en-US-JennyNeural",
    )
    assert settings.tts_provider == TTSProvider.EDGE_TTS
    assert settings.tts_provider.value == "edge-tts"
    assert settings.edge_tts_voice == "en-US-JennyNeural"


def test_edge_tts_voice_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.edge_tts_voice == "en-US-AriaNeural"
    assert settings.edge_tts_rate == "-20%"
    assert settings.edge_tts_scene_pause_ms == 450


def test_tts_provider_enum_members() -> None:
    assert {m.value for m in TTSProvider} == {
        "openai",
        "elevenlabs",
        "gtts",
        "edge-tts",
    }

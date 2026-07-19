from __future__ import annotations

from config.settings import Settings, TTSProvider


def test_tts_provider_accepts_gtts() -> None:
    settings = Settings(tts_provider="gtts")
    assert settings.tts_provider == TTSProvider.GTTS
    assert settings.tts_provider.value == "gtts"


def test_tts_provider_enum_members() -> None:
    assert {m.value for m in TTSProvider} == {"openai", "elevenlabs", "gtts"}

from __future__ import annotations

from config.settings import Settings, mask_secret, sanitize_secret


def test_sanitize_secret_strips_quotes_and_whitespace() -> None:
    assert sanitize_secret('  "gsk_abc"  ') == "gsk_abc"
    assert sanitize_secret("'gsk_abc'") == "gsk_abc"
    assert sanitize_secret("   ") is None
    assert sanitize_secret(None) is None


def test_settings_sanitizes_groq_key() -> None:
    settings = Settings(groq_api_key='  "gsk_testkey123456" ')
    assert settings.groq_api_key == "gsk_testkey123456"


def test_mask_secret() -> None:
    assert mask_secret(None) == "<unset>"
    preview = mask_secret("gsk_abcdefghijklmnop")
    assert "gsk_" in preview
    assert "len=" in preview
    # Must stay ASCII-safe for Windows consoles.
    assert preview.isascii()

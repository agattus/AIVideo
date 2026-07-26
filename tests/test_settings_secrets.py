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


def test_legacy_pixabay_asset_provider_remaps_to_pollinations() -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(asset_provider="pixabay")  # type: ignore[arg-type]
    assert settings.asset_provider == AssetProvider.POLLINATIONS

    settings2 = Settings(asset_provider="pexels")  # type: ignore[arg-type]
    assert settings2.asset_provider == AssetProvider.POLLINATIONS


def test_asset_provider_accepts_imagen_and_manual() -> None:
    from config.settings import AssetProvider, Settings

    assert Settings(asset_provider="imagen").asset_provider == AssetProvider.IMAGEN
    assert Settings(asset_provider="manual").asset_provider == AssetProvider.MANUAL
    assert Settings(asset_provider=AssetProvider.IMAGEN).asset_provider == AssetProvider.IMAGEN
    assert Settings(asset_provider=AssetProvider.MANUAL).asset_provider == AssetProvider.MANUAL


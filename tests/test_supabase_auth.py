"""Tests for Supabase JWT auth helpers (no live Supabase required)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from youtube_pipeline.api.auth import AuthUser, _decode_supabase_jwt, auth_is_required, require_user


def test_auth_not_required_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "")
    monkeypatch.setenv("AUTH_DISABLED", "0")
    from config.settings import get_settings

    get_settings.cache_clear()
    assert auth_is_required() is False
    assert require_user(None).user_id == "local-dev"
    get_settings.cache_clear()


def test_auth_required_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret-please-change")
    monkeypatch.setenv("AUTH_DISABLED", "0")
    from config.settings import get_settings

    get_settings.cache_clear()
    assert auth_is_required() is True
    get_settings.cache_clear()


def test_decode_valid_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret-please-change"
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)
    monkeypatch.setenv("AUTH_DISABLED", "0")
    from config.settings import get_settings

    get_settings.cache_clear()
    token = jwt.encode(
        {
            "sub": "11111111-1111-1111-1111-111111111111",
            "email": "director@s-studio.test",
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        secret,
        algorithm="HS256",
    )
    user = _decode_supabase_jwt(token)
    assert user.user_id == "11111111-1111-1111-1111-111111111111"
    assert user.email == "director@s-studio.test"
    get_settings.cache_clear()


def test_decode_rejects_bad_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret-please-change")
    monkeypatch.setenv("AUTH_DISABLED", "0")
    from config.settings import get_settings

    get_settings.cache_clear()
    with pytest.raises(HTTPException) as exc:
        _decode_supabase_jwt("not.a.jwt")
    assert exc.value.status_code == 401
    get_settings.cache_clear()


def test_require_user_passthrough() -> None:
    user = AuthUser(user_id="abc", email="a@b.c")
    assert require_user(user) is user

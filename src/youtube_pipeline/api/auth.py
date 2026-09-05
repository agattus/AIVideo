"""Supabase JWT auth for multi-user Studio API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from config.settings import get_settings
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    email: str | None = None


def auth_is_required() -> bool:
    """True when Supabase is configured and AUTH_DISABLED is not set."""
    settings = get_settings()
    if settings.auth_disabled:
        return False
    return bool(
        (settings.supabase_url or "").strip()
        and (settings.supabase_jwt_secret or "").strip()
    )


def _decode_supabase_jwt(token: str) -> AuthUser:
    import jwt

    settings = get_settings()
    secret = (settings.supabase_jwt_secret or "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SUPABASE_JWT_SECRET is not configured",
        )
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired session: {exc}",
        ) from exc

    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )
    email = payload.get("email")
    return AuthUser(user_id=user_id, email=str(email) if email else None)


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> AuthUser | None:
    """Resolve the caller. Returns None when auth is not required (local open mode)."""
    if not auth_is_required():
        return None
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in required. Missing Authorization Bearer token.",
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in required. Empty Bearer token.",
        )
    return _decode_supabase_jwt(token)


def require_user(user: Annotated[AuthUser | None, Depends(get_current_user)]) -> AuthUser:
    """Hard-require a signed-in user (for routes that must be multi-user)."""
    if user is None:
        # Open mode: synthetic local user so generate/list still work offline.
        return AuthUser(user_id="local-dev", email=None)
    return user

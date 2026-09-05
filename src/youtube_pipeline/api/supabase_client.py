"""Minimal Supabase REST helpers (service role) for jobs + storage."""

from __future__ import annotations

from typing import Any

import httpx

from config.settings import get_settings
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


def supabase_configured() -> bool:
    settings = get_settings()
    return bool(
        (settings.supabase_url or "").strip()
        and (settings.supabase_service_role_key or "").strip()
    )


def _headers(*, prefer: str | None = None) -> dict[str, str]:
    settings = get_settings()
    key = (settings.supabase_service_role_key or "").strip()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _rest(path: str) -> str:
    base = (get_settings().supabase_url or "").rstrip("/")
    return f"{base}/rest/v1/{path.lstrip('/')}"


def _storage(path: str) -> str:
    base = (get_settings().supabase_url or "").rstrip("/")
    return f"{base}/storage/v1/{path.lstrip('/')}"


def upsert_job_row(row: dict[str, Any]) -> None:
    if not supabase_configured():
        return
    try:
        response = httpx.post(
            _rest("jobs"),
            headers=_headers(prefer="resolution=merge-duplicates,return=minimal"),
            json=row,
            timeout=30.0,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Supabase job upsert failed | %s", exc)


def list_job_rows(*, user_id: str, limit: int = 40) -> list[dict[str, Any]]:
    if not supabase_configured():
        return []
    try:
        response = httpx.get(
            _rest("jobs"),
            headers=_headers(),
            params={
                "user_id": f"eq.{user_id}",
                "order": "updated_at.desc",
                "limit": str(limit),
                "select": "*",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Supabase job list failed | %s", exc)
        return []


def get_job_row(job_id: str) -> dict[str, Any] | None:
    if not supabase_configured():
        return None
    try:
        response = httpx.get(
            _rest("jobs"),
            headers=_headers(),
            params={"id": f"eq.{job_id}", "select": "*", "limit": "1"},
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and data:
            return data[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Supabase job get failed | %s", exc)
    return None


def upload_bytes(
    *,
    object_path: str,
    data: bytes,
    content_type: str,
    bucket: str = "job-assets",
) -> bool:
    if not supabase_configured():
        return False
    try:
        response = httpx.post(
            _storage(f"object/{bucket}/{object_path.lstrip('/')}"),
            headers={
                **_headers(),
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            content=data,
            timeout=120.0,
        )
        if response.status_code >= 400:
            # Retry as update
            response = httpx.put(
                _storage(f"object/{bucket}/{object_path.lstrip('/')}"),
                headers={
                    **_headers(),
                    "Content-Type": content_type,
                },
                content=data,
                timeout=120.0,
            )
        response.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Supabase storage upload failed | path=%s | %s", object_path, exc)
        return False


def create_signed_url(
    object_path: str,
    *,
    expires_in: int = 3600,
    bucket: str = "job-assets",
) -> str | None:
    if not supabase_configured():
        return None
    try:
        response = httpx.post(
            _storage(f"object/sign/{bucket}/{object_path.lstrip('/')}"),
            headers=_headers(),
            json={"expiresIn": expires_in},
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        signed = payload.get("signedURL") or payload.get("signedUrl")
        if not signed:
            return None
        base = (get_settings().supabase_url or "").rstrip("/")
        if str(signed).startswith("http"):
            return str(signed)
        return f"{base}/storage/v1{signed}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Supabase signed URL failed | path=%s | %s", object_path, exc)
        return None

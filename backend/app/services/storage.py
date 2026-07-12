"""Supabase Storage vía REST (secret key, bypass RLS)."""
import httpx

from app.config import settings

_BASE = f"{settings.supabase_url.rstrip('/')}/storage/v1"
_HEADERS = {
    "apikey": settings.supabase_secret_key,
    "Authorization": f"Bearer {settings.supabase_secret_key}",
}
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def upload(bucket: str, path: str, content: bytes, content_type: str = _XLSX) -> str:
    r = httpx.post(
        f"{_BASE}/object/{bucket}/{path}",
        headers={**_HEADERS, "Content-Type": content_type, "x-upsert": "true"},
        content=content,
        timeout=60,
    )
    r.raise_for_status()
    return f"{bucket}/{path}"


def download(bucket: str, path: str) -> bytes:
    r = httpx.get(f"{_BASE}/object/{bucket}/{path}", headers=_HEADERS, timeout=60)
    r.raise_for_status()
    return r.content

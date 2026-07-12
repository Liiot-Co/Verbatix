"""Storage de archivos: filesystem local (app_mode=local) o Supabase Storage
vía REST (app_mode=supabase, secret key, bypass RLS). Mismo bucket/path en
ambos, solo cambia dónde vive el byte."""
from pathlib import Path

import httpx

from app.core.config import settings

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Relativo al CWD (la app siempre corre desde backend/), no a este archivo:
# así el mismo path funciona corriendo bare o en el contenedor Docker.
_LOCAL_ROOT = Path(settings.local_storage_path).resolve()


def _local_path(bucket: str, path: str) -> Path:
    return _LOCAL_ROOT / bucket / path


def _local_upload(bucket: str, path: str, content: bytes, content_type: str = _XLSX) -> str:
    dest = _local_path(bucket, path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return f"{bucket}/{path}"


def _local_download(bucket: str, path: str) -> bytes:
    return _local_path(bucket, path).read_bytes()


if settings.app_mode == "local":
    upload = _local_upload
    download = _local_download
else:
    _BASE = f"{settings.supabase_url.rstrip('/')}/storage/v1"
    _HEADERS = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
    }

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

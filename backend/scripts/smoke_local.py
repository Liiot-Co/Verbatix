"""Smoke test Fase 1 — corre contra servidor local."""
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]

for line in (BACKEND / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k] = v

API = os.environ.get("API", "http://127.0.0.1:8001")
SUPABASE_URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SECRET_KEY"]
XLSX = ROOT / "LC 32406432 TRACK MULTICATEGORY GLORIA QUESO - RONDA 4 2026.xlsx"

if not XLSX.exists():
    print(f"No existe el Excel: {XLSX}")
    sys.exit(1)

client = httpx.Client(timeout=180.0)
headers_admin = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def main() -> None:
    for path in ("/health", "/health/db"):
        r = client.get(f"{API}{path}")
        print(path, r.status_code, r.text)
        r.raise_for_status()

    email = os.environ.get("SUPABASE_TEST_EMAIL", "smoke-test@verbatix.local")
    password = os.environ.get("SUPABASE_TEST_PASSWORD", "SmokeTest2026!")

    r = client.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers=headers_admin,
        json={"email": email, "password": password},
    )
    if r.status_code != 200:
        print("Creando usuario de prueba...")
        cr = client.post(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=headers_admin,
            json={"email": email, "password": password, "email_confirm": True},
        )
        print("create user", cr.status_code, cr.text[:300])
        cr.raise_for_status()
        r = client.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers=headers_admin,
            json={"email": email, "password": password},
        )
    r.raise_for_status()
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    print("token ok")

    r = client.get(f"{API}/me", headers=auth)
    print("/me", r.status_code, r.json())
    r.raise_for_status()

    r = client.post(
        f"{API}/api/v1/projects",
        headers={**auth, "Content-Type": "application/json"},
        json={"external_code": "32406432", "name": "TRACK GLORIA QUESO", "client_name": "Gloria"},
    )
    r.raise_for_status()
    proj = r.json()["id"]
    print("project", proj)

    r = client.post(
        f"{API}/api/v1/projects/{proj}/rounds",
        headers={**auth, "Content-Type": "application/json"},
        json={"name": "Ronda 1 - 2026", "round_number": 1},
    )
    r.raise_for_status()
    round_id = r.json()["id"]

    r = client.post(
        f"{API}/api/v1/rounds/{round_id}/studios",
        headers={**auth, "Content-Type": "application/json"},
        json={
            "name": "Marcas",
            "coding_type": "brands",
            "survey_question": "Q030 BE1: Que marcas de QUESO conoce?",
            "origin_mode": "from_scratch",
            "min_mentions_threshold": 3,
            "audit_percentage": 10,
        },
    )
    r.raise_for_status()
    studio = r.json()["id"]
    print("studio", studio)

    with XLSX.open("rb") as f:
        r = client.post(
            f"{API}/api/v1/studios/{studio}/files",
            headers=auth,
            files={"file": (XLSX.name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    print("upload", r.status_code, r.text[:500])
    r.raise_for_status()
    file_id = r.json()["file_id"]

    r = client.post(
        f"{API}/api/v1/studios/{studio}/files/{file_id}/import",
        headers={**auth, "Content-Type": "application/json"},
        json={"verbatims_sheet": "Verbatims_Marcas"},
    )
    print("import", r.status_code, r.text)
    r.raise_for_status()

    r = client.get(f"{API}/api/v1/studios/{studio}", headers=auth)
    print("FINAL", json.dumps(r.json(), indent=2, default=str))

    r = client.get(f"{API}/api/v1/studios/{studio}/mention-groups", headers=auth)
    groups = r.json()
    print(f"mention_groups total={len(groups)}")
    for g in groups[:8]:
        print(f"  {g['frequency_count']:4d}  {g['sample_text'][:55]}")


if __name__ == "__main__":
    main()

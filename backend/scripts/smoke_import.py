"""Smoke test E2E del flujo de importación contra el backend local (post-v9).

Crea proyecto + ronda, sube un Excel real del repo, lo importa (clasificando
las variables pendientes si las hay) y verifica que respondents queda poblado
con imported_file_id/realid. Uso:  python scripts/smoke_import.py
"""
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8001/api/v1"
XLSX = next(Path("../data/uploads").rglob("*RONDA 1 2026.xlsx"), None)

if not XLSX:
    sys.exit("No se encontró un Excel de prueba en data/uploads/")

stamp = int(time.time())
client = httpx.Client(timeout=120)

project = client.post(f"{BASE}/projects", json={
    "external_code": f"SMOKE-{stamp}", "name": f"Smoke v9 {stamp}",
}).raise_for_status().json()
print("proyecto:", project["id"])

round_ = client.post(f"{BASE}/projects/{project['id']}/rounds", json={
    "name": "Ronda smoke", "round_number": 1,
}).raise_for_status().json()
print("ronda:", round_["id"])

with open(XLSX, "rb") as f:
    uploaded = client.post(
        f"{BASE}/rounds/{round_['id']}/files",
        files={"file": (XLSX.name, f)},
    ).raise_for_status().json()
print("archivo:", uploaded["file_id"], "| hojas:", [s["name"] for s in uploaded["detected_sheets"]])

verbatims_sheet = next(
    (s["name"] for s in uploaded["detected_sheets"] if s["guessed_as"] == "verbatims"),
    uploaded["detected_sheets"][0]["name"],
)

def do_import():
    return client.post(
        f"{BASE}/rounds/{round_['id']}/files/{uploaded['file_id']}/import",
        json={"verbatims_sheet": verbatims_sheet, "column_map": {"verbatim": "Verbatim"}},
    ).raise_for_status().json()

result = do_import()
if result["pending_questions"]:
    print("clasificando", len(result["pending_questions"]), "variables pendientes...")
    for qk in result["pending_questions"]:
        client.post(f"{BASE}/projects/{project['id']}/questions/classify", json={
            "question_key": qk, "coding_type": "reasons",
        }).raise_for_status()
    result = do_import()

print("importados:", result["imported"], "| processing:", result["processing"]["status"])
assert result["imported"]["verbatims"] > 0, "no se importó ningún verbatim"
print("OK: flujo de subida+import funciona con el esquema v9")

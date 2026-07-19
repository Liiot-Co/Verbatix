"""Smoke test E2E de REQ-03 (cargas múltiples) contra el backend local.

Flujo completo: login -> proyecto + ronda -> carga 1 (.dau) -> carga 2 (.dau)
con un duplicado real (mismo realid) y una colisión de Serial (mismo Serial,
otra persona) -> revisión humana -> resolución -> motor desbloqueado.

Uso (dentro del contenedor backend):
    docker compose exec -T backend python scripts/smoke_multiload.py
"""
import sys
import time

import httpx

BASE = "http://localhost:8001/api/v1"
AUTH = "http://localhost:8001/api/auth"
EMAIL = "dev@local.test"
PASSWORD = "VerbatixAdmin2026"


def dau_bytes(records: list[dict]) -> bytes:
    """Arma un .dau mínimo válido (UTF-16LE + BOM, ##recstart/##v/##end)."""
    lines = []
    for i, record in enumerate(records, start=1):
        lines.append(f"##recstart {i}")
        for field, value in record.items():
            lines.append(f"##v '{field}' = '{value}'")
        lines.append(f"##end {i}")
    return b"\xff\xfe" + "\r\n".join(lines).encode("utf-16-le")


def main() -> None:
    stamp = int(time.time())
    client = httpx.Client(timeout=120)

    login = client.post(f"{AUTH}/login", json={"email": EMAIL, "password": PASSWORD})
    login.raise_for_status()
    token = login.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    print("login OK")

    project = client.post(f"{BASE}/projects", json={
        "external_code": f"REQ03-{stamp}", "name": f"Smoke REQ-03 {stamp}",
    }).raise_for_status().json()
    round_ = client.post(f"{BASE}/projects/{project['id']}/rounds", json={
        "name": "Ronda multicarga", "round_number": 1,
    }).raise_for_status().json()
    rid = round_["id"]
    print("proyecto:", project["id"], "| ronda:", rid)

    # ── Carga 1: Serial 1 (rev-AAA), Serial 2 (rev-BBB) ──
    load1 = dau_bytes([
        {"realid": "rev-AAA", "VYK[1].Slice": "Gloria", "VYK[2].Slice": "Laive"},
        {"realid": "rev-BBB", "VYK[1].Slice": "Pura vida"},
    ])
    up1 = client.post(f"{BASE}/rounds/{rid}/files", files={
        "file": ("dimension_parte_1.dau", load1),
    }).raise_for_status().json()
    assert up1["file_type"] == "dau", up1
    assert up1["suggested_source_label"] == "dimension parte 1", up1["suggested_source_label"]
    assert up1["duplicate_of"] is None

    def do_import(file_id: str, label: str) -> dict:
        return client.post(f"{BASE}/rounds/{rid}/files/{file_id}/import", json={
            "verbatims_sheet": "Registros DAU", "column_map": None, "source_label": label,
        }).raise_for_status().json()

    result1 = do_import(up1["file_id"], "Dimension Parte 1")
    if result1["pending_questions"]:
        print("clasificando", len(result1["pending_questions"]), "variables nuevas (columnas sin calzar)...")
        for qk in result1["pending_questions"]:
            client.post(f"{BASE}/projects/{project['id']}/questions/classify", json={
                "question_key": qk, "coding_type": "brands",
            }).raise_for_status()
        result1 = do_import(up1["file_id"], "Dimension Parte 1")
    assert result1["is_additional_load"] is False, "la carga 1 debe ser primera carga"
    assert result1["review"]["pending_flags"] == 0
    assert result1["processing"]["status"] == "queued", result1["processing"]
    print("carga 1 importada:", result1["imported"]["verbatims"], "verbatims — flujo primera carga intacto")

    # ── Mismo archivo otra vez: el checksum avisa, no duplica en silencio ──
    up_dup = client.post(f"{BASE}/rounds/{rid}/files", files={
        "file": ("dimension_parte_1.dau", load1),
    }).raise_for_status().json()
    assert up_dup["duplicate_of"] is not None, "checksum repetido debe avisar"
    print("re-subida del mismo archivo: aviso de duplicado OK ->", up_dup["duplicate_of"]["source_label"])

    # ── Carga 2: Serial 1 = rev-CCC (colisión de Serial, persona distinta),
    #             Serial 2 = rev-AAA (duplicado real) ──
    load2 = dau_bytes([
        {"realid": "rev-CCC", "VYK[1].Slice": "Bonle"},
        {"realid": "rev-AAA", "VYK[1].Slice": "Gloria", "VYK[2].Slice": "Anchor"},
    ])
    up2 = client.post(f"{BASE}/rounds/{rid}/files", files={
        "file": ("enfield_parte_2.dau", load2),
    }).raise_for_status().json()
    result2 = do_import(up2["file_id"], "Enfield Parte 2")
    assert result2["is_additional_load"] is True
    assert result2["processing"]["status"] == "blocked_on_review", result2["processing"]
    review = result2["review"]
    assert review["pending_flags"] == 1, review
    dup = review["duplicates"][0]
    assert dup["realid"] == "rev-AAA" and dup["serial"] == "2", dup
    assert dup["matches"][0]["source_label"] == "Dimension Parte 1", dup["matches"]
    assert any(c["serial"] == "1" for c in review["serial_collisions"]), review["serial_collisions"]
    print("carga 2: duplicado real flaggeado (insertado, pendiente) + colisión de Serial informativa OK")

    # La llave técnica (uuid de respondents) nunca viaja en la revisión.
    assert "respondent_id" not in dup, "no exponer la llave técnica"

    # ── Estado de la cola por endpoint dedicado ──
    state = client.get(f"{BASE}/rounds/{rid}/files/{up2['file_id']}/review").raise_for_status().json()
    assert state["requires_review"] is True and state["pending_flags"] == 1

    # ── Resolución humana: mantener ambos -> motor desbloqueado ──
    resolved = client.post(f"{BASE}/import-review/{dup['flag_id']}/resolve", json={
        "action": "keep",
    }).raise_for_status().json()
    assert resolved["status"] == "approved_keep" and resolved["pending_flags"] == 0
    assert resolved["processing"]["status"] == "queued", resolved
    print("duplicado resuelto (keep): motor en cola OK")

    # ── Las cargas y verbatims exponen su origen ──
    loads = client.get(f"{BASE}/rounds/{rid}/loads").raise_for_status().json()
    labels = {l["source_label"] for l in loads}
    assert {"Dimension Parte 1", "Enfield Parte 2"} <= labels, labels
    validated = [l for l in loads if l["status"] == "validated"]
    assert all(l["pending_flags"] == 0 for l in validated)

    sp = client.get(f"{BASE}/rounds/{rid}").raise_for_status().json()["subprojects"]
    brands_sp = next(s["id"] for s in sp if s["coding_type"] == "brands")

    # El motor corre en background; el listado exige fase de resolución.
    for _ in range(60):
        status = client.get(f"{BASE}/rounds/{rid}").raise_for_status().json()["status"]
        if status in ("preliminary_ready", "manual_coding"):
            break
        time.sleep(2)
    verbs = client.get(f"{BASE}/subprojects/{brands_sp}/verbatims").raise_for_status().json()
    by_label: dict[str, int] = {}
    for item in verbs["items"]:
        by_label[item["source_label"]] = by_label.get(item["source_label"], 0) + 1
        assert "respondent_id" not in item  # solo Serial visible, nunca el uuid
    assert by_label.get("Dimension Parte 1") and by_label.get("Enfield Parte 2"), by_label
    # Serial 1 aparece dos veces (una por carga), sin pisarse.
    serial_1 = {(v["respondent_external_id"], v["source_label"]) for v in verbs["items"] if v["respondent_external_id"] == "1"}
    assert len(serial_1) == 2, serial_1
    print("verbatims con carga de origen OK:", by_label)

    print("OK: flujo REQ-03 completo (primera carga intacta, duplicado real a revisión, "
          "Serial repetido informativo, checksum avisado, motor gateado y desbloqueado)")


if __name__ == "__main__":
    sys.exit(main())

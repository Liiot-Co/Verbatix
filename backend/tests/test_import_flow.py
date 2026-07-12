from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
Base.metadata.create_all(bind=engine)
TestingSessionLocal = sessionmaker(bind=engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)


def _build_fixture_xlsx() -> bytes:
    wb = Workbook()
    verbatims = wb.active
    verbatims.title = "Verbatims"
    verbatims.append(["Respondent ID", "Question ID", "Verbatim"])
    verbatims.append(["1001", "Q1", "Laive"])
    verbatims.append(["1002", "Q1", "Bonle"])
    verbatims.append(["1003", "Q1", ""])  # blank text -> skipped

    codebook = wb.create_sheet("LC")
    codebook.append(["CÓDIGO", "MENCIÓN PRINCIPAL", "CONTENIDO", "FRECUENCIA", "%"])
    codebook.append([1, "Laive", "laive", 10, 50])
    codebook.append([None, "NETO MARCAS DE QUESO", None, None, None])  # separator row -> skipped

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_full_import_flow():
    project = client.post(
        "/api/v1/projects",
        json={"external_code": "TEST-1", "name": "Test Project", "client_name": "ACME"},
    ).json()

    study = client.post(
        f"/api/v1/projects/{project['id']}/studies",
        json={"name": "Marcas", "coding_type": "brands", "survey_question": "Q1"},
    ).json()

    round_ = client.post(
        f"/api/v1/studies/{study['id']}/rounds",
        json={
            "name": "Ronda 1",
            "round_number": 1,
            "origin_mode": "from_scratch",
            "min_mentions_threshold": 3,
            "audit_percentage": 10,
        },
    ).json()
    assert round_["codebook"]["inherited_codes"] == 0

    xlsx_bytes = _build_fixture_xlsx()
    upload = client.post(
        f"/api/v1/rounds/{round_['id']}/files",
        files={"file": ("verbatims.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    sheet_types = {s["name"]: s["guessed_as"] for s in upload["detected_sheets"]}
    assert sheet_types == {"Verbatims": "verbatims", "LC": "codebook"}

    import_result = client.post(
        f"/api/v1/rounds/{round_['id']}/files/{upload['file_id']}/import",
        json={
            "verbatims_sheet": "Verbatims",
            "codebook_sheet": "LC",
            "column_map": {
                "respondent_id": "Respondent ID",
                "question_key": "Question ID",
                "verbatim": "Verbatim",
            },
        },
    ).json()
    assert import_result["imported"] == {
        "verbatims": 2,
        "codes": 1,
        "aliases": 1,
        "skipped_rows": 1,
    }
    assert import_result["round_status"] == "files_uploaded"

    verbatims = client.get(f"/api/v1/rounds/{round_['id']}/verbatims").json()
    assert verbatims["total"] == 2
    assert {v["original_text"] for v in verbatims["items"]} == {"Laive", "Bonle"}

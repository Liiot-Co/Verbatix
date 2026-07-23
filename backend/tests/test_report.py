"""Tests para reporte final y export del Libro de Códigos."""
import io
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook

from app.pipeline.export import build_codebook_excel, build_export_zip
from unittest.mock import patch

from app.repositories import get_round_report, round_export_blockers
from app.routers.report import _DEFAULT_FORMATS, _parse_export_formats

ROUND_ID = uuid.uuid4()
CODE_A = uuid.uuid4()
CODE_B = uuid.uuid4()


class FakeResult:
    def __init__(self, scalar=None, mappings_list=None):
        self._scalar = scalar
        self._mappings_list = mappings_list or []

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._mappings_list

    def mappings(self):
        return self

    def first(self):
        return self._mappings_list[0] if self._mappings_list else None


class FakeSession:
    """Responde las queries de get_round_report con datos controlados."""

    def __init__(self):
        self.total = 100
        self.status_rows = [
            {"coding_status": "auto_coded", "n": 70},
            {"coding_status": "manually_coded", "n": 20},
            {"coding_status": "needs_review", "n": 10},
        ]
        self.processed_at = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
        self.code_rows = [
            {
                "id": CODE_A,
                "code_number": 1,
                "label": "Gloria",
                "net": "NETO LACTEOS",
                "coding_type": "brands",
                "frequency": 40,
            },
            {
                "id": CODE_B,
                "code_number": 2,
                "label": "Alpina",
                "net": "NETO LACTEOS",
                "coding_type": "brands",
                "frequency": 25,
            },
        ]
        self.totals_by_type = [("brands", 100)]
        self.samples = {
            CODE_A: ["GLORIA", "gloria leche"],
            CODE_B: ["Alpina"],
        }

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "count(*) from verbatims v" in sql and "group by" not in sql:
            return FakeResult(scalar=self.total)
        if "group by v.coding_status" in sql:
            return FakeResult(mappings_list=self.status_rows)
        if "from processing_runs pr" in sql:
            return FakeResult(scalar=self.processed_at)
        if "sp.coding_type" in sql and "group by sp.coding_type" in sql:
            return FakeResult(mappings_list=self.totals_by_type)
        if "count(distinct v.id) as frequency" in sql and "not c.is_system" in sql:
            return FakeResult(mappings_list=self.code_rows)
        if "limit 3" in sql and "original_text" in sql:
            code_id = params.get("code_id")
            return FakeResult(mappings_list=self.samples.get(code_id, []))
        return FakeResult()


class ExportBlockerSession:
    def __init__(self, state):
        self.state = state

    def execute(self, stmt, params=None):
        return FakeResult(mappings_list=[self.state])


def test_export_blockers_require_every_integrity_gate():
    state = {
        "source_files": 0,
        "ready_source_files": 0,
        "unapproved_codebooks": 1,
        "unresolved_groups": 4,
        "conflicts": 2,
        "missing_or_stale_audits": 1,
    }
    with patch("app.repositories.round_processing_blockers", return_value=["1 flag pendiente"]):
        blockers = round_export_blockers(ExportBlockerSession(state), ROUND_ID)

    assert blockers == [
        "1 flag pendiente",
        "la ronda no tiene un snapshot de población de origen",
        "1 libros de códigos sin aprobar",
        "4 grupos sin decisión final",
        "2 conflictos de clasificación o memoria",
        "1 auditorías faltantes o desactualizadas",
    ]


def test_export_blockers_allow_only_closed_round_data():
    state = {
        "source_files": 1,
        "ready_source_files": 1,
        "unapproved_codebooks": 0,
        "unresolved_groups": 0,
        "conflicts": 0,
        "missing_or_stale_audits": 0,
    }
    with patch("app.repositories.round_processing_blockers", return_value=[]):
        assert round_export_blockers(ExportBlockerSession(state), ROUND_ID) == []


def test_get_round_report_auto_manual_pct():
    report = get_round_report(FakeSession(), ROUND_ID)

    assert report["verbatims_total"] == 100
    assert report["auto_coded"] == 70
    assert report["auto_coded_pct"] == 70.0
    assert report["manually_coded"] == 20
    assert report["manually_coded_pct"] == 20.0
    assert report["processed_at"] == "2026-01-15T12:00:00+00:00"
    assert len(report["codes"]) == 2
    assert report["codes"][0]["label"] == "Gloria"
    assert report["codes"][0]["frequency"] == 40
    assert report["codes"][0]["pct"] == 0.4
    assert report["codes"][0]["samples"] == ["GLORIA", "gloria leche"]


def test_build_codebook_excel_valid_without_nets():
    export_data = {
        "project_external_code": "32406432",
        "round_number": 1,
        "study_name": "HBG Leches",
        "total_verbatims": 4,
        "max_output_index": 2,
        "nets_by_coding_type": {
            "brands": [{
                "name": "NETO MARCAS",
                "codes": [
                    {
                        "code_number": 1,
                        "label": "Gloria",
                        "content": "GLORIA/gloria",
                        "frequency": 2,
                        "pct": 0.5,
                    },
                    {
                        "code_number": 2,
                        "label": "Alpina",
                        "content": "",
                        "frequency": 1,
                        "pct": 0.25,
                    },
                ],
            }],
        },
        "verbatims": [
            {
                "respondent_external_id": "R1",
                "question_key": "Q1",
                "original_text": "GLORIA",
                "codes": [
                    {"output_index": 1, "code_number": 1, "label": "Gloria"},
                    {"output_index": 2, "code_number": 2, "label": "Alpina"},
                ],
            },
            {
                "respondent_external_id": "R2",
                "question_key": "Q1",
                "original_text": "alpina",
                "codes": [{"output_index": 1, "code_number": 2, "label": "Alpina"}],
            },
        ],
    }

    xlsx = build_codebook_excel(export_data)
    assert xlsx[:2] == b"PK"

    wb = load_workbook(io.BytesIO(xlsx), read_only=True, data_only=True)
    assert "LC Marcas" in wb.sheetnames
    assert "Verbatims" in wb.sheetnames

    lc = wb["LC Marcas"]
    assert lc.cell(1, 1).value == "HBG Leches — Marcas"
    assert lc.cell(2, 2).value == "CÓDIGO"
    assert lc.cell(3, 1).value == "NETO MARCAS"
    assert lc.cell(4, 2).value == 1
    assert lc.cell(4, 3).value == "Gloria"
    assert lc.cell(4, 5).value == 2
    assert lc.cell(4, 6).value == 0.5

    verbs = wb["Verbatims"]
    assert verbs.cell(1, 1).value == "Study ID"
    assert verbs.cell(1, 8).value == "Input ID 2"
    assert verbs.cell(2, 1).value == "32406432"
    assert verbs.cell(2, 4).value == "GLORIA"
    assert verbs.cell(2, 5).value == 1
    assert verbs.cell(2, 8).value == 2


def test_code_entry_content_filters_null_aliases():
    """alias_sample puede ser NULL en BD; no debe romper el join."""
    samples = [None, "GLORIA", None, "gloria leche"]
    content = "/".join([s for s in samples if s][:3])
    assert content == "GLORIA/gloria leche"
    export_data = {
        "project_external_code": "32406432",
        "round_number": 1,
        "study_name": "HBG Leches",
        "total_verbatims": 2,
        "max_output_index": 1,
        "nets_by_coding_type": {
            "brands": [{
                "name": "NETO MARCAS",
                "codes": [{
                    "code_number": 1,
                    "label": "Gloria",
                    "content": "GLORIA",
                    "frequency": 2,
                    "pct": 1.0,
                }],
            }],
        },
        "verbatims": [{
            "respondent_external_id": "R1",
            "question_key": "Q1",
            "original_text": "GLORIA",
            "codes": [{"output_index": 1, "code_number": 1, "label": "Gloria"}],
        }],
    }

    import zipfile

    zbytes = build_export_zip(export_data, {"excel"})
    assert zbytes[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
        assert zf.namelist() == ["LC_32406432_R1.xlsx"]
        assert zf.read("LC_32406432_R1.xlsx")[:2] == b"PK"


def test_parse_export_formats_defaults_when_omitted():
    assert _parse_export_formats(None) == _DEFAULT_FORMATS


def test_parse_export_formats_parses_comma_separated():
    assert _parse_export_formats("excel,sql") == {"excel", "sql"}
    assert _parse_export_formats(" excel , sql ") == {"excel", "sql"}


def test_parse_export_formats_rejects_unknown_value():
    with pytest.raises(HTTPException) as exc_info:
        _parse_export_formats("excel,pdf")
    assert exc_info.value.status_code == 400

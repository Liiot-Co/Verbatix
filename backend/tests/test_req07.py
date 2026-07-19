"""Casos obligatorios de REQ-07 sin tocar una base real."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from openpyxl import Workbook

from app.pipeline.ingest.excel import parse_codebook
from app.pipeline.llm.client import _build_prompt
from app.repositories import (
    approve_scratch_codebooks_for_round,
    clone_codebook,
    create_code,
    create_codebook,
    insert_codebook_from_excel,
    seed_system_codes,
)
from app.routers.studios import _catalog_source


class Result:
    def __init__(self, *, scalar=None, mapping=None, rows=None, rowcount=0):
        self._scalar = scalar
        self._mapping = mapping
        self._rows = rows or []
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def first(self):
        return self._mapping

    def all(self):
        return self._rows


class CatalogSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, params))
        if "coalesce(max(version)" in sql:
            return Result(scalar=1)
        if "insert into codes" in sql and "select gen_random_uuid()" in sql:
            return Result(rowcount=3)
        if "insert into code_aliases" in sql and "select gen_random_uuid()" in sql:
            return Result(rowcount=4)
        if "with new_nets" in sql:
            return Result(rowcount=2)
        return Result()


class CreateCodeSession:
    def __init__(self, number_rows=None):
        self.number_rows = number_rows or []
        self.insert_sql = ""
        self.insert_params = None

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "lower(label) = lower(:label)" in sql:
            return Result(mapping=None)
        if "select id, code_number, label" in sql:
            return Result(rows=[])
        if "select code_number, is_system" in sql:
            return Result(rows=self.number_rows)
        if "insert into codes" in sql:
            self.insert_sql = sql
            self.insert_params = params
        return Result()


class ImportSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, params))
        if "select origin, status from codebooks" in sql:
            return Result(mapping={"origin": "imported_client_catalog", "status": "draft"})
        if "select count(*) from codes" in sql:
            return Result(scalar=0)
        return Result()


def _realistic_client_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "CATALOGO"
    ws.append(("NETO LÁCTEOS", None, None, None))
    ws.append((None, 1, "GLORIA", "gloria (3)/leche gloria (2)"))
    ws.append((None, 95, "CÓDIGO OFICIAL CLIENTE", "especial (1)"))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_scratch_catalog_and_system_numbers_are_immutable():
    db = CatalogSession()
    codebook_id = create_codebook(db, uuid.uuid4(), "brands", origin="scratch")
    seed_system_codes(db, codebook_id)

    codebook_insert = next(call for call in db.calls if "insert into codebooks" in call[0])
    system_numbers = [params["n"] for sql, params in db.calls if "insert into codes" in sql]
    assert codebook_insert[1]["origin"] == "scratch"
    assert system_numbers == [95, 96, 97, 98, 99]

    migration = (
        Path(__file__).parents[1]
        / "db/migrations/004_req07_catalog_provenance.sql"
    ).read_text(encoding="utf-8")
    assert "before update of code_number" in migration


def test_same_study_second_round_clones_numbers_and_uses_next_free():
    db = CatalogSession()
    source_codebook_id = uuid.uuid4()
    target_id = create_codebook(
        db,
        uuid.uuid4(),
        "brands",
        source_codebook_id,
        origin="inherited_round",
        status="approved",
    )
    copied = clone_codebook(db, source_codebook_id, target_id)

    code_copy_sql = next(sql for sql, _ in db.calls if "select gen_random_uuid()" in sql)
    target_insert = next(params for sql, params in db.calls if "insert into codebooks" in sql)
    assert target_insert["parent"] == source_codebook_id
    assert "code_number" in code_copy_sql
    assert "inherited_from_code_id" in code_copy_sql
    assert "where codebook_id = :src and is_active" in code_copy_sql
    assert copied == {"codes": 3, "aliases": 4, "nets": 2}

    create_db = CreateCodeSession([
        {"code_number": 10, "is_system": False},
        {"code_number": 95, "is_system": True},
    ])
    created = create_code(create_db, target_id, "Nueva marca", None, uuid.uuid4())
    assert created["code_number"] == 11


def test_cross_study_same_client_source_is_allowed():
    target_project = uuid.uuid4()
    source_project = uuid.uuid4()
    client_id = uuid.uuid4()
    source_subproject = uuid.uuid4()

    class SourceSession:
        def execute(self, stmt, params=None):
            if "from subprojects sp" in str(stmt):
                return Result(mapping={
                    "subproject_id": source_subproject,
                    "coding_type": "brands",
                    "codebook_id": uuid.uuid4(),
                    "round_id": uuid.uuid4(),
                    "project_id": source_project,
                    "proyecto_id": client_id,
                })
            return Result(mapping={"proyecto_id": client_id})

    source = _catalog_source(
        SourceSession(), target_project, "brands", source_subproject
    )
    assert source["project_id"] == source_project


def test_imported_client_catalog_preserves_exact_numbers_and_overflows_system_codes():
    parsed = parse_codebook(_realistic_client_workbook(), "CATALOGO")
    db = ImportSession()
    imported = insert_codebook_from_excel(
        db,
        uuid.uuid4(),
        parsed,
        imported_from_file_id=uuid.uuid4(),
        approved_by=uuid.uuid4(),
    )

    client_inserts = [
        (sql, params)
        for sql, params in db.calls
        if "insert into codes" in sql and "'imported_client'" in sql
    ]
    system_inserts = [
        params
        for sql, params in db.calls
        if "insert into codes" in sql and "'inherited'" in sql
    ]
    assert [params["n"] for _, params in client_inserts] == [1, 95]
    assert all("'imported_client'" in sql for sql, _ in client_inserts)
    assert [params["n"] for params in system_inserts] == [995, 996, 997, 998, 999]
    assert imported == {
        "codes": 2,
        "aliases": 3,
        "nets": 1,
        "system_codes_overflow": True,
    }
    prompt = _build_prompt(
        [
            {"code_number": params["n"], "label": "Sistema", "net": None,
             "aliases": [], "system_type": params["st"]}
            for params in system_inserts
        ],
        [{"id": "v1", "text": "no sé"}],
        "brands",
    )
    assert '"no sé" -> 996' in prompt
    assert "995 menciones confusas" in prompt

    impossible = {
        "nets": [],
        "codes": [
            {"code_number": 95, "label": "Cliente 95", "aliases": [], "net": None},
            {"code_number": 995, "label": "Cliente 995", "aliases": [], "net": None},
        ],
    }
    with pytest.raises(ValueError, match="simultáneamente"):
        insert_codebook_from_excel(
            ImportSession(),
            uuid.uuid4(),
            impossible,
            imported_from_file_id=uuid.uuid4(),
            approved_by=uuid.uuid4(),
        )


def test_reasons_catalog_cannot_be_inherited_by_brands():
    class WrongTypeSession:
        def execute(self, stmt, params=None):
            if "from subprojects sp" in str(stmt):
                return Result(mapping={
                    "subproject_id": uuid.uuid4(),
                    "coding_type": "reasons",
                    "codebook_id": uuid.uuid4(),
                    "round_id": uuid.uuid4(),
                    "project_id": TARGET_PROJECT,
                    "proyecto_id": None,
                })
            return Result(mapping={"proyecto_id": None})

    with pytest.raises(HTTPException, match="otro tipo"):
        _catalog_source(
            WrongTypeSession(), TARGET_PROJECT, "brands", uuid.uuid4()
        )


TARGET_PROJECT = uuid.uuid4()


def test_closing_origin_round_approves_scratch_catalog():
    class ApprovalSession:
        def __init__(self):
            self.sql = ""

        def execute(self, stmt, params=None):
            self.sql = str(stmt)
            return Result(rowcount=2)

    db = ApprovalSession()
    updated = approve_scratch_codebooks_for_round(
        db, uuid.uuid4(), uuid.uuid4()
    )
    assert updated == 2
    assert "cb.origin = 'scratch'" in db.sql
    assert "r.status = 'audit_approved'" in db.sql
    assert "status = 'approved'" in db.sql


def test_clone_and_import_keep_nets_linked_to_copied_codes():
    clone_db = CatalogSession()
    clone_codebook(clone_db, uuid.uuid4(), uuid.uuid4())
    net_copy_sql = next(sql for sql, _ in clone_db.calls if "with new_nets" in sql)
    assert "join codes nc" in net_copy_sql
    assert "nc.inherited_from_code_id = oc.id" in net_copy_sql

    import_db = ImportSession()
    insert_codebook_from_excel(
        import_db,
        uuid.uuid4(),
        parse_codebook(_realistic_client_workbook(), "CATALOGO"),
        imported_from_file_id=uuid.uuid4(),
        approved_by=uuid.uuid4(),
    )
    assert any("insert into nets" in sql for sql, _ in import_db.calls)
    assert any("insert into net_codes" in sql for sql, _ in import_db.calls)


def test_resolution_manual_code_keeps_existing_behavior_and_origin():
    db = CreateCodeSession()
    created = create_code(
        db, uuid.uuid4(), "Marca manual", None, uuid.uuid4()
    )
    assert created["code_number"] == 1
    assert "'analyst_manual'" in db.insert_sql
    assert db.insert_params["l"] == "marca manual"

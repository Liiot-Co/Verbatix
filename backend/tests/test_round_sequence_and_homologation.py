"""Casos obligatorios de round-sequence-and-homologation sin tocar una base real."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.repositories import next_round_number, round_setup_incomplete
from app.routers.studios import CatalogOriginIn, SubprojectsIn, create_round_subprojects


class Result:
    def __init__(self, *, scalar=None, mapping=None, rows=None):
        self._scalar = scalar
        self._mapping = mapping
        self._rows = rows or []

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def first(self):
        return self._mapping

    def all(self):
        return self._rows


class ScalarsResult:
    """execute(...).scalars().all() — usado por `existing_types` en
    create_round_subprojects, distinto de `.mappings().all()`."""

    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class NextRoundNumberSession:
    def __init__(self, max_round_number):
        self.max_round_number = max_round_number

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "max(round_number)" in sql:
            return Result(scalar=self.max_round_number)
        return Result()


def test_next_round_number_no_rounds_is_1():
    db = NextRoundNumberSession(None)
    assert next_round_number(db, uuid.uuid4()) == 1


def test_next_round_number_with_rounds_1_and_2_is_3():
    db = NextRoundNumberSession(2)
    assert next_round_number(db, uuid.uuid4()) == 3


def test_next_round_number_first_round_created_as_5_is_6():
    db = NextRoundNumberSession(5)
    assert next_round_number(db, uuid.uuid4()) == 6


class SetupIncompleteSession:
    """Simula las 4 queries de round_setup_incomplete en orden de ejecución."""

    def __init__(
        self,
        *,
        subproject_count=1,
        pending_client_catalogs=0,
        round_status="preliminary_ready",
        unclosed_files=0,
        no_files_count=0,
    ):
        self.subproject_count = subproject_count
        self.pending_client_catalogs = pending_client_catalogs
        self.round_status = round_status
        self.unclosed_files = unclosed_files
        self.no_files_count = no_files_count

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "select count(*) from subprojects where round_id" in sql:
            return Result(scalar=self.subproject_count)
        if "cb.origin = 'imported_client_catalog'" in sql:
            return Result(scalar=self.pending_client_catalogs)
        if "select status from rounds where id" in sql:
            return Result(mapping={"status": self.round_status})
        if "coalesce(dataset_snapshot ->> 'status'" in sql:
            return Result(scalar=self.unclosed_files)
        if "file_type in ('verbatims_xlsx', 'combined_xlsx', 'dau')" in sql:
            return Result(scalar=self.no_files_count)
        return Result()


def test_round_without_subprojects_is_incomplete():
    db = SetupIncompleteSession(subproject_count=0)
    assert round_setup_incomplete(db, uuid.uuid4()) is True


def test_round_with_pending_client_catalog_is_incomplete():
    db = SetupIncompleteSession(subproject_count=2, pending_client_catalogs=1)
    assert round_setup_incomplete(db, uuid.uuid4()) is True


def test_round_fully_processed_is_complete():
    db = SetupIncompleteSession(
        subproject_count=2,
        pending_client_catalogs=0,
        round_status="preliminary_ready",
    )
    assert round_setup_incomplete(db, uuid.uuid4()) is False


def test_round_with_scratch_subprojects_but_no_file_imported_is_incomplete():
    db = SetupIncompleteSession(
        subproject_count=2,
        pending_client_catalogs=0,
        round_status="created",
        unclosed_files=0,
        no_files_count=0,
    )
    assert round_setup_incomplete(db, uuid.uuid4()) is True


class SubprojectsRoundSession:
    """Solo responde a la query de coding_types existentes — usada para probar
    la validación de origen antes de tocar cualquier otra tabla."""

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "select coding_type from subprojects where round_id" in sql:
            return ScalarsResult([])
        raise AssertionError(f"Query inesperada en el test: {sql}")

    def commit(self):
        pass


def _patch_round_guards(monkeypatch, round_number: int):
    monkeypatch.setattr(
        "app.routers.studios.require_round",
        lambda *a, **k: {
            "project_id": uuid.uuid4(),
            "round_number": round_number,
            "min_mentions_threshold": 3,
            "audit_percentage": 10,
        },
    )
    monkeypatch.setattr("app.routers.studios.require_capability", lambda *a, **k: None)
    # Corta antes de tocar codebooks reales: el gate de origen (Task 3) ya
    # decidió si sigue o no — lo que pase después no es lo que este test cubre.
    monkeypatch.setattr(
        "app.routers.studios._create_subprojects",
        lambda *a, **k: ({}, None),
    )


def test_non_first_round_rejects_scratch(monkeypatch):
    _patch_round_guards(monkeypatch, round_number=2)
    payload = SubprojectsIn(catalog_origins={
        "brands": CatalogOriginIn(origin="scratch", source_subproject_id=None),
    })
    with pytest.raises(HTTPException) as exc:
        create_round_subprojects(
            uuid.uuid4(), payload, db=SubprojectsRoundSession(), user={"id": uuid.uuid4()},
        )
    assert exc.value.detail["code"] == "non_first_round_requires_homologation"


def test_non_first_round_allows_inherited_round(monkeypatch):
    """round-sequence-and-homologation: heredar de una ronda/estudio anterior
    debe permitirse en rondas no-primeras, igual que homologar — solo
    'scratch' (crear desde cero) queda bloqueado."""
    _patch_round_guards(monkeypatch, round_number=2)
    payload = SubprojectsIn(catalog_origins={
        "brands": CatalogOriginIn(origin="inherited_round", source_subproject_id=uuid.uuid4()),
    })
    result = create_round_subprojects(
        uuid.uuid4(), payload, db=SubprojectsRoundSession(), user={"id": uuid.uuid4()},
    )
    assert result["subprojects"] == []


def test_non_first_round_allows_imported_client_catalog(monkeypatch):
    _patch_round_guards(monkeypatch, round_number=3)
    payload = SubprojectsIn(catalog_origins={
        "brands": CatalogOriginIn(origin="imported_client_catalog", source_subproject_id=None),
    })
    result = create_round_subprojects(
        uuid.uuid4(), payload, db=SubprojectsRoundSession(), user={"id": uuid.uuid4()},
    )
    assert result["subprojects"] == []


def test_first_round_allows_scratch(monkeypatch):
    _patch_round_guards(monkeypatch, round_number=1)
    payload = SubprojectsIn(catalog_origins={
        "brands": CatalogOriginIn(origin="scratch", source_subproject_id=None),
    })
    result = create_round_subprojects(
        uuid.uuid4(), payload, db=SubprojectsRoundSession(), user={"id": uuid.uuid4()},
    )
    assert result["subprojects"] == []

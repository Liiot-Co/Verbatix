"""Aprobación de borradores scratch: idempotencia y libros vacíos hermanos."""
from __future__ import annotations

import uuid
from unittest.mock import patch

from app.repositories import approve_scratch_codebook_draft

ROUND_ID = uuid.uuid4()
SUBPROJECT_ID = uuid.uuid4()
CODEBOOK_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


class FakeResult:
    def __init__(self, scalar=None, mapping_rows=None, scalar_rows=None, rowcount=0):
        self._scalar = scalar
        self._mapping_rows = mapping_rows or []
        self._scalar_rows = scalar_rows if scalar_rows is not None else self._mapping_rows
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def mappings(self):
        return self

    def all(self):
        return self._scalar_rows if self._scalar_rows is not None else self._mapping_rows

    def first(self):
        return self._mapping_rows[0] if self._mapping_rows else None


class FakeSession:
    def __init__(self, *, book_status: str = "approved", pending_books: int = 0):
        self.book_status = book_status
        self.pending_books = pending_books
        self.statements: list[str] = []

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).lower().split())
        self.statements.append(sql)
        if "for update of cb, sp" in sql:
            return FakeResult(mapping_rows=[{
                "id": CODEBOOK_ID,
                "origin": "scratch",
                "status": self.book_status,
                "coding_type": "brands",
                "round_id": ROUND_ID,
            }])
        if "select count(*)" in sql and "cb.status not in" in sql:
            return FakeResult(scalar=self.pending_books)
        if "update codebooks cb" in sql and "not exists" in sql:
            self.pending_books = 0
            return FakeResult(rowcount=1)
        return FakeResult()


def test_already_approved_draft_returns_round_id_and_can_resume_processing():
    db = FakeSession(book_status="approved", pending_books=1)
    result = approve_scratch_codebook_draft(db, SUBPROJECT_ID, [], USER_ID)

    assert "round_id" in result
    assert result["round_id"] == str(ROUND_ID)
    assert result["ready_to_process"] is True
    assert any("update rounds set status = 'processing'" in sql for sql in db.statements)


def test_approve_auto_closes_empty_sibling_scratch_books():
    code_id = uuid.uuid4()

    class ApprovingSession(FakeSession):
        def execute(self, stmt, params=None):
            sql = " ".join(str(stmt).lower().split())
            self.statements.append(sql)
            if "for update of cb, sp" in sql:
                return FakeResult(mapping_rows=[{
                    "id": CODEBOOK_ID,
                    "origin": "scratch",
                    "status": "draft",
                    "coding_type": "brands",
                    "round_id": ROUND_ID,
                }])
            if "select id from codes" in sql and "approval_status = 'pending'" in sql:
                return FakeResult(scalar_rows=[code_id])
            if "select count(*)" in sql and "cb.status not in" in sql:
                return FakeResult(scalar=0)
            if "update codebooks cb" in sql and "not exists" in sql:
                return FakeResult(rowcount=1)
            return FakeResult()

    db = ApprovingSession(book_status="draft", pending_books=1)
    decisions = [{
        "code_id": code_id,
        "decision": "approve",
        "label": "Gloria",
        "definition": "Marca láctea",
        "inclusion_criteria": ["Gloria"],
        "exclusion_criteria": [],
        "examples": ["gloria"],
        "net_name": None,
    }]
    with patch("app.repositories.log_action"):
        result = approve_scratch_codebook_draft(db, SUBPROJECT_ID, decisions, USER_ID)

    assert result["ready_to_process"] is True
    assert result["round_id"] == str(ROUND_ID)
    assert any("not exists" in sql and "update codebooks cb" in sql for sql in db.statements)

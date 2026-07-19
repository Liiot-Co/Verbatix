"""Alcance de ronda: Solo Marcas / Solo Razones / Ambas."""
from __future__ import annotations

import uuid

from app.repositories import insert_verbatims


PROJECT_ID = uuid.uuid4()
ROUND_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()
SUBPROJECT_BRANDS = uuid.uuid4()


class FakeResult:
    def __init__(self, scalar=None, mappings_list=None, rowcount=1):
        self._scalar = scalar
        self._mappings_list = mappings_list or []
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def all(self):
        return self._mappings_list

    def first(self):
        return self._mappings_list[0] if self._mappings_list else None


class BrandsOnlySession:
    """Ronda configurada solo con Marcas."""

    def __init__(self):
        self.questions: dict[tuple, dict] = {}
        self.respondents: dict[tuple, uuid.UUID] = {}
        self.inserted_verbatims: list[dict] = []

    def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        params = params or {}

        if "select id, question_key, coding_type from questions where project_id" in sql:
            return FakeResult(mappings_list=[
                {"id": q["id"], "question_key": qk, "coding_type": q["coding_type"]}
                for (project, qk), q in self.questions.items()
                if project == params["project"]
            ])

        if "select id from questions where project_id" in sql:
            q = self.questions.get((params["project"], params["qk"]))
            return FakeResult(scalar=q["id"] if q else None)

        if "join question_aliases qa" in sql or "from question_aliases" in sql:
            return FakeResult(mappings_list=[])

        if "insert into questions" in sql:
            self.questions[(params["project"], params["qk"])] = {
                "id": params["id"], "coding_type": params["ct"],
            }
            return FakeResult()

        if "select id, coding_type from subprojects where round_id" in sql:
            return FakeResult(mappings_list=[
                {"id": SUBPROJECT_BRANDS, "coding_type": "brands"},
            ])

        if "insert into respondents" in sql:
            for p in params if isinstance(params, list) else [params]:
                key = (p["round"], p["resp"])
                if key not in self.respondents:
                    self.respondents[key] = p["id"]
            return FakeResult(rowcount=1)

        if "select respondent_external_id, id from respondents" in sql:
            resps = set(params["resps"])
            return FakeResult(mappings_list=[
                {"respondent_external_id": resp, "id": rid}
                for (round_id, resp), rid in self.respondents.items()
                if round_id == params["round"] and resp in resps
            ])

        if "insert into verbatims" in sql:
            self.inserted_verbatims.extend(params if isinstance(params, list) else [params])
            return FakeResult(rowcount=1)

        return FakeResult()


def test_brands_only_round_inserts_brands_and_skips_preclassified_reasons():
    db = BrandsOnlySession()
    reasons_key = "CUST_REASON[1]"
    db.questions[(PROJECT_ID, reasons_key)] = {
        "id": uuid.uuid4(), "coding_type": "reasons",
    }
    rows = [
        {
            "respondent_external_id": "1",
            "question_key": "VYK[1].Slice",
            "original_text": "gloria",
        },
        {
            "respondent_external_id": "1",
            "question_key": reasons_key,
            "original_text": "por el precio",
        },
    ]

    n_inserted, _, pending, skipped = insert_verbatims(
        db, ROUND_ID, PROJECT_ID, FILE_ID, rows
    )

    assert n_inserted == 1
    assert pending == []
    assert skipped == {"reasons": 1}
    assert db.inserted_verbatims[0]["sp"] == SUBPROJECT_BRANDS


def test_brands_only_round_leaves_reasons_pattern_as_pending():
    """Patrón NBS de razones no auto-clasifica si la ronda no tiene Razones."""
    db = BrandsOnlySession()
    rows = [{
        "respondent_external_id": "8",
        "question_key": "NBS_UNAIDBlock[{_1}].NBS_UNAID",
        "original_text": "el precio",
    }]

    n_inserted, _, pending, skipped = insert_verbatims(
        db, ROUND_ID, PROJECT_ID, FILE_ID, rows
    )

    assert n_inserted == 0
    assert pending == ["NBS_UNAIDBlock[{_1}].NBS_UNAID"]
    assert skipped == {}
    assert db.inserted_verbatims == []

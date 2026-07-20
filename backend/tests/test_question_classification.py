"""Tarea 9 (app v8 Fase 3): una question_key nueva no debe hacer fallar el import —
insert_verbatims la deja pendiente, y una vez el analista la clasifica con
classify_question, reintentar insert_verbatims con las MISMAS filas ya no la deja
pendiente y el verbatim se inserta en el subproject correcto (sección 2.5)."""
import uuid

import pytest

from app.repositories import classify_question, insert_verbatims

PROJECT_ID = uuid.uuid4()
ROUND_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()
SUBPROJECT_BRANDS = uuid.uuid4()
SUBPROJECT_REASONS = uuid.uuid4()
QUESTION_KEY = "CUST_BE1[1].Slice"  # no sigue ningún patrón conocido: requiere clasificación manual


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


class FakeSession:
    """Estado mínimo: questions (project_id, question_key) -> {id, coding_type},
    respondents por (round_id, ext_id), y un contador de verbatims insertados."""

    def __init__(self):
        self.questions: dict[tuple, dict] = {}
        self.respondents: dict[tuple, uuid.UUID] = {}
        self.inserted_verbatims: list[dict] = []
        self.inserted_respondents: list[dict] = []

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).lower().split())
        params = params or {}

        if "from questions where project_id" in sql and "question_key" in sql and "select" in sql and "insert" not in sql:
            if "and question_key" in sql:
                q = self.questions.get((params["project"], params["qk"]))
                if q:
                    return FakeResult(mappings_list=[{
                        "id": q["id"], "coding_type": q["coding_type"],
                    }])
                return FakeResult(mappings_list=[])
            return FakeResult(mappings_list=[
                {
                    "id": q["id"],
                    "question_key": qk,
                    "coding_type": q["coding_type"],
                }
                for (project, qk), q in self.questions.items()
                if project == params["project"]
            ])

        if "select id from questions where project_id" in sql:
            q = self.questions.get((params["project"], params["qk"]))
            return FakeResult(scalar=q["id"] if q else None)

        if "join question_aliases qa" in sql:
            return FakeResult(mappings_list=[])  # sin alias en este test

        if "insert into questions" in sql:
            self.questions[(params["project"], params["qk"])] = {
                "id": params["id"],
                "coding_type": params["ct"],
            }
            return FakeResult()

        if "select expected_max_mentions from rounds" in sql:
            return FakeResult(scalar=None)

        if "from subprojects where round_id" in sql and "single_code_per_response" in sql:
            return FakeResult(mappings_list=[
                {"id": SUBPROJECT_BRANDS, "coding_type": "brands", "single_code_per_response": False},
                {"id": SUBPROJECT_REASONS, "coding_type": "reasons", "single_code_per_response": False},
            ])

        if "select id, coding_type from subprojects where round_id" in sql:
            return FakeResult(mappings_list=[
                {"id": SUBPROJECT_BRANDS, "coding_type": "brands"},
                {"id": SUBPROJECT_REASONS, "coding_type": "reasons"},
            ])

        if "update imported_files" in sql:
            return FakeResult()

        if "insert into question_mention_decisions" in sql:
            return FakeResult()

        if "select coding_type from questions where id" in sql:
            for q in self.questions.values():
                if q["id"] == params["id"]:
                    return FakeResult(scalar=q["coding_type"])
            return FakeResult(scalar=None)

        if "select id, coding_type from subprojects where round_id" in sql:
            return FakeResult(mappings_list=[
                {"id": SUBPROJECT_BRANDS, "coding_type": "brands"},
                {"id": SUBPROJECT_REASONS, "coding_type": "reasons"},
            ])

        if "insert into respondents" in sql:
            for p in params if isinstance(params, list) else [params]:
                self.inserted_respondents.append(p)
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


def _sample_rows():
    return [{
        "respondent_external_id": "8",
        "question_key": QUESTION_KEY,
        "original_text": "pura vida",
    }]


def test_unclassified_question_key_is_pending_not_a_failure():
    db = FakeSession()
    n_inserted, _, pending, _skipped = insert_verbatims(db, ROUND_ID, PROJECT_ID, FILE_ID, _sample_rows())

    assert n_inserted == 0
    assert pending == [QUESTION_KEY]
    assert db.inserted_verbatims == []


def test_classifying_then_retrying_inserts_the_verbatim():
    db = FakeSession()
    insert_verbatims(db, ROUND_ID, PROJECT_ID, FILE_ID, _sample_rows())  # 1st pass: pending

    classify_question(db, PROJECT_ID, QUESTION_KEY, "brands")

    n_inserted, _, pending, _skipped = insert_verbatims(db, ROUND_ID, PROJECT_ID, FILE_ID, _sample_rows())

    assert pending == []
    assert n_inserted == 1
    assert db.inserted_verbatims[0]["sp"] == SUBPROJECT_BRANDS


def test_insert_preserves_realid_and_repeated_mentions_with_stable_positions():
    db = FakeSession()
    classify_question(db, PROJECT_ID, QUESTION_KEY, "brands")
    rows = [
        {
            "respondent_external_id": "8", "realid": "persona-real-8",
            "question_key": QUESTION_KEY, "original_text": "Gloria",
            "source_row_number": 20,
        },
        {
            "respondent_external_id": "8", "realid": "persona-real-8",
            "question_key": QUESTION_KEY, "original_text": "Laive",
            "source_row_number": 21,
        },
    ]

    n_inserted, _, pending, _ = insert_verbatims(
        db, ROUND_ID, PROJECT_ID, FILE_ID, rows
    )

    assert pending == []
    assert n_inserted == 2
    assert db.inserted_respondents[0]["realid"] == "persona-real-8"
    assert [row["position"] for row in db.inserted_verbatims] == [1, 2]
    assert [row["source_row"] for row in db.inserted_verbatims] == [20, 21]
    assert [row["txt"] for row in db.inserted_verbatims] == ["Gloria", "Laive"]


def test_classify_question_is_idempotent_per_project():
    db = FakeSession()
    first_id = classify_question(db, PROJECT_ID, QUESTION_KEY, "brands")
    second_id = classify_question(db, PROJECT_ID, QUESTION_KEY, "reasons")

    assert first_id == second_id
    assert db.questions[(PROJECT_ID, QUESTION_KEY)]["coding_type"] == "brands"


def test_known_nbs_unaid_pattern_auto_classifies_as_reasons_without_pending():
    db = FakeSession()
    rows = [{
        "respondent_external_id": "8",
        "question_key": "NBS_UNAIDBlock[{_1}].NBS_UNAID",
        "original_text": "el precio",
    }]

    n_inserted, _, pending, _skipped = insert_verbatims(db, ROUND_ID, PROJECT_ID, FILE_ID, rows)

    assert pending == []
    assert n_inserted == 1
    assert db.inserted_verbatims[0]["sp"] == SUBPROJECT_REASONS


def test_known_nbs_unaid_fup_pattern_auto_classifies_as_brands_without_pending():
    db = FakeSession()
    rows = [{
        "respondent_external_id": "8",
        "question_key": "NBS_UNAID_FUP_ADD[{_4}].Slice",
        "original_text": "pura vida",
    }]

    n_inserted, _, pending, _skipped = insert_verbatims(db, ROUND_ID, PROJECT_ID, FILE_ID, rows)

    assert pending == []
    assert n_inserted == 1
    assert db.inserted_verbatims[0]["sp"] == SUBPROJECT_BRANDS


def test_known_vyk_pattern_auto_classifies_as_brands_without_pending():
    db = FakeSession()
    rows = [{
        "respondent_external_id": "8",
        "question_key": "VYK[1].Slice",
        "original_text": "gloria",
    }]

    n_inserted, _, pending, _skipped = insert_verbatims(db, ROUND_ID, PROJECT_ID, FILE_ID, rows)

    assert pending == []
    assert n_inserted == 1
    assert db.inserted_verbatims[0]["sp"] == SUBPROJECT_BRANDS


# ── field_selections (wizard de selección de campos) ──


def test_field_selections_none_is_a_pure_regression_noop():
    db = FakeSession()
    n_inserted, _, pending, _skipped = insert_verbatims(
        db, ROUND_ID, PROJECT_ID, FILE_ID, _sample_rows(), field_selections=None,
    )
    assert n_inserted == 0
    assert pending == [QUESTION_KEY]


def test_field_selections_excluded_field_is_dropped_entirely():
    db = FakeSession()
    n_inserted, _, pending, _skipped = insert_verbatims(
        db, ROUND_ID, PROJECT_ID, FILE_ID, _sample_rows(),
        field_selections=[{"field": QUESTION_KEY, "included": False, "coding_type": None}],
    )
    assert n_inserted == 0
    assert pending == []
    assert db.inserted_verbatims == []


def test_field_selections_explicit_coding_type_skips_pending():
    db = FakeSession()
    n_inserted, _, pending, _skipped = insert_verbatims(
        db, ROUND_ID, PROJECT_ID, FILE_ID, _sample_rows(),
        field_selections=[{"field": QUESTION_KEY, "included": True, "coding_type": "brands"}],
    )
    assert pending == []
    assert n_inserted == 1
    assert db.inserted_verbatims[0]["sp"] == SUBPROJECT_BRANDS


def test_field_selections_coding_type_outside_round_scope_raises():
    db = FakeSession()
    with pytest.raises(ValueError):
        insert_verbatims(
            db, ROUND_ID, PROJECT_ID, FILE_ID, _sample_rows(),
            field_selections=[{"field": QUESTION_KEY, "included": True, "coding_type": "not_a_real_scope"}],
        )

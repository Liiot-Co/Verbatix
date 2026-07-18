"""Tarea 9 (app v8 Fase 3): una question_key nueva no debe hacer fallar el import —
insert_verbatims la deja pendiente, y una vez el analista la clasifica con
classify_question, reintentar insert_verbatims con las MISMAS filas ya no la deja
pendiente y el verbatim se inserta en el subproject correcto (sección 2.5)."""
import uuid

from app.repositories import classify_question, insert_verbatims

PROJECT_ID = uuid.uuid4()
ROUND_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()
SUBPROJECT_BRANDS = uuid.uuid4()
SUBPROJECT_REASONS = uuid.uuid4()
QUESTION_KEY = "NBS_UNAID_FUP_ADD[{_4}].Slice"


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

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}

        if "select id from questions where project_id" in sql:
            q = self.questions.get((params["project"], params["qk"]))
            return FakeResult(scalar=q["id"] if q else None)

        if "join question_aliases qa" in sql:
            return FakeResult(scalar=None)  # sin alias en este test

        if "insert into questions" in sql:
            self.questions[(params["project"], params["qk"])] = {
                "id": params["id"], "coding_type": params["ct"],
            }
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
            key = (params["round"], params["resp"])
            if key not in self.respondents:
                self.respondents[key] = uuid.uuid4()
            return FakeResult(scalar=self.respondents[key])

        if "insert into verbatims" in sql:
            self.inserted_verbatims.append(params)
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
    n_inserted, _, pending = insert_verbatims(db, ROUND_ID, PROJECT_ID, FILE_ID, _sample_rows())

    assert n_inserted == 0
    assert pending == [QUESTION_KEY]
    assert db.inserted_verbatims == []


def test_classifying_then_retrying_inserts_the_verbatim():
    db = FakeSession()
    insert_verbatims(db, ROUND_ID, PROJECT_ID, FILE_ID, _sample_rows())  # 1st pass: pending

    classify_question(db, PROJECT_ID, QUESTION_KEY, "brands")

    n_inserted, _, pending = insert_verbatims(db, ROUND_ID, PROJECT_ID, FILE_ID, _sample_rows())

    assert pending == []
    assert n_inserted == 1
    assert db.inserted_verbatims[0]["sp"] == SUBPROJECT_BRANDS


def test_classify_question_is_idempotent_per_project():
    db = FakeSession()
    first_id = classify_question(db, PROJECT_ID, QUESTION_KEY, "brands")
    second_id = classify_question(db, PROJECT_ID, QUESTION_KEY, "reasons")

    assert first_id == second_id
    assert db.questions[(PROJECT_ID, QUESTION_KEY)]["coding_type"] == "brands"

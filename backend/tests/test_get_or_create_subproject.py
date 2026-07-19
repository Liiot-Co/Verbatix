"""get_or_create_subproject: una ronda ya no nace con Marcas y Razones fijos
(create_round dejó de crearlos) — el subproyecto de cada coding_type se crea
la primera vez que insert_verbatims (o el import de codebook) lo necesita."""
import uuid

from app.repositories import get_or_create_subproject

PROJECT_ID = uuid.uuid4()
ROUND_ID = uuid.uuid4()
SOURCE_PROJECT_ID = uuid.uuid4()
SOURCE_ROUND_ID = uuid.uuid4()


class FakeResult:
    def __init__(self, scalar=None, mappings_list=None, rowcount=0):
        self._scalar = scalar
        self._mappings_list = mappings_list if mappings_list is not None else []
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
    """Estado mínimo: subprojects (round_id, coding_type) -> id, codebooks
    (project_id, coding_type) -> id, codes por codebook, rounds por id."""

    def __init__(self, rounds=None):
        self.subprojects: dict[tuple, uuid.UUID] = {}
        self.codebooks: dict[tuple, uuid.UUID] = {}
        self.codes: dict[uuid.UUID, list] = {}
        self.rounds = rounds or {}
        self.subproject_params: dict | None = None

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}

        if "select id from subprojects where round_id" in sql:
            return FakeResult(scalar=self.subprojects.get((params["round"], params["ct"])))

        if "select id from codebooks where project_id" in sql and "order by version desc" in sql:
            return FakeResult(scalar=self.codebooks.get((params["project"], params["ct"])))

        if "coalesce(max(version), 0) + 1 from codebooks" in sql:
            return FakeResult(scalar=1)

        if "insert into codebooks" in sql:
            self.codebooks[(params["project"], params["ct"])] = params["id"]
            self.codes[params["id"]] = []
            return FakeResult()

        if "insert into codes" in sql:
            self.codes.setdefault(params["cb"], []).append(params["n"])
            return FakeResult()

        if "select origin_mode, source_round_id from rounds" in sql:
            row = self.rounds.get(params["id"])
            return FakeResult(mappings_list=[row] if row else [])

        if "select project_id from rounds where id" in sql:
            row = self.rounds.get(params["id"])
            return FakeResult(scalar=row["project_id"] if row else None)

        if "insert into subprojects" in sql:
            self.subprojects[(params["round"], params["ct"])] = params["id"]
            self.subproject_params = params
            return FakeResult()

        return FakeResult()


def test_creates_codebook_with_system_codes_and_subproject_on_first_call():
    db = FakeSession(rounds={ROUND_ID: {"origin_mode": "from_scratch", "source_round_id": None}})

    sp_id = get_or_create_subproject(db, ROUND_ID, PROJECT_ID, "brands")

    assert db.subprojects[(ROUND_ID, "brands")] == sp_id
    cb_id = db.codebooks[(PROJECT_ID, "brands")]
    assert len(db.codes[cb_id]) == 5  # SYSTEM_CODES (95..99)


def test_second_call_is_idempotent_and_reuses_the_same_subproject():
    db = FakeSession(rounds={ROUND_ID: {"origin_mode": "from_scratch", "source_round_id": None}})

    first_id = get_or_create_subproject(db, ROUND_ID, PROJECT_ID, "brands")
    second_id = get_or_create_subproject(db, ROUND_ID, PROJECT_ID, "brands")

    assert first_id == second_id
    assert len(db.codebooks) == 1  # no se creó un segundo codebook


def test_different_coding_types_get_separate_subprojects_and_codebooks():
    db = FakeSession(rounds={ROUND_ID: {"origin_mode": "from_scratch", "source_round_id": None}})

    brands_id = get_or_create_subproject(db, ROUND_ID, PROJECT_ID, "brands")
    reasons_id = get_or_create_subproject(db, ROUND_ID, PROJECT_ID, "reasons")

    assert brands_id != reasons_id
    assert set(db.codebooks) == {(PROJECT_ID, "brands"), (PROJECT_ID, "reasons")}


def test_applies_min_mentions_and_audit_percentage_captured_at_import_time():
    """Se fijan solo en la creación (capturados en el wizard al soltar el
    archivo) — no hay endpoint para editarlas después, ver update_subproject."""
    db = FakeSession(rounds={ROUND_ID: {"origin_mode": "from_scratch", "source_round_id": None}})

    get_or_create_subproject(
        db, ROUND_ID, PROJECT_ID, "brands", min_mentions_threshold=7, audit_percentage=25.0
    )

    assert db.subproject_params["min_m"] == 7
    assert db.subproject_params["audit"] == 25.0


def test_defaults_to_none_when_not_provided_by_caller():
    db = FakeSession(rounds={ROUND_ID: {"origin_mode": "from_scratch", "source_round_id": None}})

    get_or_create_subproject(db, ROUND_ID, PROJECT_ID, "brands")

    assert db.subproject_params["min_m"] is None
    assert db.subproject_params["audit"] is None

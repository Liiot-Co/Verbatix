"""REQ-08 / REQ-04: código único por Marcas|Razones; máx. esperado por ronda."""
import uuid

import pytest

from app.pipeline.ingest import dau
from app.pipeline.question_controls import (
    SingleCodeViolation,
    apply_mention_limits,
    assert_single_code_assignment,
    cap_codes_for_single_response,
    expand_brand_mentions,
    max_mentions_across_keys,
    split_mentions,
)
from app.repositories import insert_verbatims

PROJECT_ID = uuid.uuid4()
ROUND_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()
SUBPROJECT_BRANDS = uuid.uuid4()
SUBPROJECT_REASONS = uuid.uuid4()


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
    def __init__(self, *, brands_only: bool = False):
        self.questions: dict[tuple, dict] = {}
        self.respondents: dict[tuple, uuid.UUID] = {}
        self.inserted_verbatims: list[dict] = []
        self.decisions: list[dict] = []
        self.file_updates: list[dict] = []
        self.brands_only = brands_only
        self.expected_max_mentions: int | None = None
        self.single_by_type: dict[str, bool] = {"brands": False, "reasons": False}

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).lower().split())
        params = params or {}

        if "from questions where project_id" in sql and "question_key" in sql and "insert" not in sql:
            if "and question_key" in sql:
                q = self.questions.get((params["project"], params["qk"]))
                if q:
                    return FakeResult(mappings_list=[{"id": q["id"], "coding_type": q["coding_type"]}])
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

        if "join question_aliases" in sql:
            return FakeResult(mappings_list=[])

        if "insert into questions" in sql:
            self.questions[(params["project"], params["qk"])] = {
                "id": params["id"],
                "coding_type": params["ct"],
            }
            return FakeResult()

        if "update rounds" in sql and "expected_max_mentions" in sql:
            self.expected_max_mentions = params.get("max_m")
            return FakeResult()

        if "update subprojects" in sql and "single_code_per_response" in sql:
            self.single_by_type[params["ct"]] = bool(params["single"])
            return FakeResult()

        if "select expected_max_mentions from rounds" in sql:
            return FakeResult(scalar=self.expected_max_mentions)

        if "from subprojects where round_id" in sql and "single_code_per_response" in sql:
            rows = [{
                "id": SUBPROJECT_BRANDS,
                "coding_type": "brands",
                "single_code_per_response": self.single_by_type.get("brands", False),
            }]
            if not self.brands_only:
                rows.append({
                    "id": SUBPROJECT_REASONS,
                    "coding_type": "reasons",
                    "single_code_per_response": self.single_by_type.get("reasons", False),
                })
            return FakeResult(mappings_list=rows)

        if "select id, coding_type from subprojects" in sql:
            rows = [{"id": SUBPROJECT_BRANDS, "coding_type": "brands"}]
            if not self.brands_only:
                rows.append({"id": SUBPROJECT_REASONS, "coding_type": "reasons"})
            return FakeResult(mappings_list=rows)

        if "update imported_files" in sql:
            self.file_updates.append(dict(params))
            return FakeResult()

        if "insert into question_mention_decisions" in sql:
            self.decisions.append(dict(params))
            return FakeResult()

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


def _rows_for(question_key: str, texts: list[tuple[str, str]]) -> list[dict]:
    return [
        {
            "respondent_external_id": resp,
            "question_key": question_key,
            "original_text": text,
        }
        for resp, text in texts
    ]


def test_req04_overflow_requires_decision_and_both_options_work():
    qk = "CUST_MULTI"
    rows = _rows_for(qk, [
        ("1", "a"), ("1", "b"), ("1", "c"), ("1", "d"),
        ("2", "x"), ("2", "y"),
    ])
    assert max_mentions_across_keys(rows, {qk}) == 4

    db = FakeSession()
    with pytest.raises(ValueError, match="process_all o limit_to_expected"):
        insert_verbatims(
            db, ROUND_ID, PROJECT_ID, FILE_ID, rows,
            field_selections=[{"field": qk, "included": True, "coding_type": "brands"}],
            expected_max_mentions=2,
            mentions_decision=None,
            single_code_by_type={"brands": False},
        )

    db_all = FakeSession()
    n_all, _, pending, _ = insert_verbatims(
        db_all, ROUND_ID, PROJECT_ID, FILE_ID, rows,
        field_selections=[{"field": qk, "included": True, "coding_type": "brands"}],
        expected_max_mentions=2,
        mentions_decision="process_all",
        single_code_by_type={"brands": False},
    )
    assert pending == []
    assert n_all == 6
    assert db_all.decisions[0]["decision"] == "process_all"
    assert db_all.expected_max_mentions == 2

    db_lim = FakeSession()
    n_lim, _, pending, _ = insert_verbatims(
        db_lim, ROUND_ID, PROJECT_ID, FILE_ID, rows,
        field_selections=[{"field": qk, "included": True, "coding_type": "brands"}],
        expected_max_mentions=2,
        mentions_decision="limit_to_expected",
        single_code_by_type={"brands": False},
    )
    assert pending == []
    assert n_lim == 4  # 2+2
    assert db_lim.decisions[0]["decision"] == "limit_to_expected"


def test_req04_no_alert_when_within_expected():
    qk = "CUST_OK"
    rows = _rows_for(qk, [("1", "a"), ("1", "b"), ("2", "x")])
    db = FakeSession()
    n, _, pending, _ = insert_verbatims(
        db, ROUND_ID, PROJECT_ID, FILE_ID, rows,
        field_selections=[{"field": qk, "included": True, "coding_type": "brands"}],
        expected_max_mentions=3,
        mentions_decision=None,
        single_code_by_type={"brands": False},
    )
    assert pending == []
    assert n == 3
    assert db.decisions == []


def test_req08_single_code_keeps_only_first_mention():
    qk = "CUST_SINGLE"
    rows = _rows_for(qk, [("1", "primero"), ("1", "segundo"), ("2", "solo")])
    limited = apply_mention_limits(rows, single_code_keys={qk}, limited_keys={})
    assert len(limited) == 2
    assert [r["original_text"] for r in limited] == ["primero", "solo"]

    db = FakeSession()
    n, _, _, _ = insert_verbatims(
        db, ROUND_ID, PROJECT_ID, FILE_ID, rows,
        field_selections=[{"field": qk, "included": True, "coding_type": "brands"}],
        expected_max_mentions=None,
        mentions_decision=None,
        single_code_by_type={"brands": True},
    )
    assert n == 2
    assert db.single_by_type["brands"] is True


def test_req08_cap_allows_one_content_plus_one_system():
    codes = [
        {"id": "c1", "is_system": False},
        {"id": "c2", "is_system": False},
        {"id": "s95", "is_system": True},
    ]
    capped = cap_codes_for_single_response(codes, single_code=True)
    assert [c["id"] for c in capped] == ["c1", "s95"]


def test_req08_resolution_rejects_two_content_codes():
    with pytest.raises(SingleCodeViolation):
        assert_single_code_assignment(
            [{"id": "a", "is_system": False}, {"id": "b", "is_system": False}],
            single_code=True,
        )
    assert_single_code_assignment(
        [{"id": "a", "is_system": False}, {"id": "s", "is_system": True}],
        single_code=True,
    )


def test_split_mentions_is_deterministic_and_order_preserving():
    assert split_mentions("Gloria, bonle") == ["Gloria", "bonle"]
    assert split_mentions("Bonlé y Laive") == ["Bonlé", "Laive"]
    assert split_mentions("paria, laive, gloria, bonle") == ["paria", "laive", "gloria", "bonle"]
    # Una sola marca no se parte.
    assert split_mentions("Gloria") == ["Gloria"]
    # Corte ambiguo (deja un fragmento de 1 char) -> se conserva entero para que
    # siga su curso normal, no se rompe en pedazos inservibles.
    assert split_mentions("a, gloria") == ["a, gloria"]
    assert split_mentions("") == []


def test_expand_brand_mentions_only_touches_brand_keys():
    rows = [
        {"question_key": "BE1", "respondent_external_id": "1", "original_text": "Gloria, bonle"},
        {"question_key": "R1", "respondent_external_id": "1", "original_text": "rico y barato"},
    ]
    expanded = expand_brand_mentions(rows, brand_keys={"BE1"})
    texts = [(r["question_key"], r["original_text"]) for r in expanded]
    # La marca se parte en dos menciones ordenadas; la razón queda intacta.
    assert texts == [("BE1", "Gloria"), ("BE1", "bonle"), ("R1", "rico y barato")]


def test_single_field_multibrand_single_code_keeps_first_mention():
    """Código único = Sí: "Gloria, bonle" -> solo la primera mención (Gloria)."""
    rows = expand_brand_mentions(
        [{"question_key": "BE1", "respondent_external_id": "7", "original_text": "Gloria, bonle"}],
        brand_keys={"BE1"},
    )
    limited = apply_mention_limits(rows, single_code_keys={"BE1"}, limited_keys={})
    assert [r["original_text"] for r in limited] == ["Gloria"]


def test_single_field_multibrand_multi_code_respects_max_mentions():
    """Código único = No con máx. 3: "paria, laive, gloria, bonle" -> las 3 primeras."""
    rows = expand_brand_mentions(
        [{"question_key": "BE1", "respondent_external_id": "7",
          "original_text": "paria, laive, gloria, bonle"}],
        brand_keys={"BE1"},
    )
    limited = apply_mention_limits(rows, single_code_keys=set(), limited_keys={"BE1": 3})
    assert [r["original_text"] for r in limited] == ["paria", "laive", "gloria"]


def test_req08_defaults_vyk_and_nbs_suggest_multi_and_are_overridable():
    assert dau.guess_single_code_default("VYK[1].Slice") is False
    assert dau.guess_single_code_default("NBS_UNAIDBlock[{_1}].NBS_UNAID") is False
    assert dau.guess_single_code_default("CUST_BE1[1].Slice") is None

    # El analista puede forzar código único en Marcas aunque la sugerencia sea multi.
    db = FakeSession()
    qk = "VYK[1].Slice"
    rows = _rows_for(qk, [("1", "gloria"), ("1", "alpina")])
    n, _, _, _ = insert_verbatims(
        db, ROUND_ID, PROJECT_ID, FILE_ID, rows,
        field_selections=[{"field": qk, "included": True, "coding_type": "brands"}],
        single_code_by_type={"brands": True},
    )
    assert n == 1
    assert db.single_by_type["brands"] is True


def test_req08_same_switch_on_brands_and_reasons():
    for coding_type, qk, sp in (
        ("brands", "CUST_BRAND", SUBPROJECT_BRANDS),
        ("reasons", "CUST_REASON", SUBPROJECT_REASONS),
    ):
        db = FakeSession()
        rows = _rows_for(qk, [("1", "uno"), ("1", "dos")])
        n, _, _, _ = insert_verbatims(
            db, ROUND_ID, PROJECT_ID, FILE_ID, rows,
            field_selections=[{"field": qk, "included": True, "coding_type": coding_type}],
            single_code_by_type={coding_type: True},
        )
        assert n == 1
        assert db.inserted_verbatims[0]["sp"] == sp
        assert db.single_by_type[coding_type] is True


def test_regression_untouched_controls_import_all_mentions():
    """Sin tocar interruptor ni máx. esperado = comportamiento previo."""
    qk = "CUST_REGRESSION"
    rows = _rows_for(qk, [("1", "a"), ("1", "b"), ("1", "c")])
    db = FakeSession()
    n, _, pending, _ = insert_verbatims(
        db, ROUND_ID, PROJECT_ID, FILE_ID, rows,
        field_selections=None,
    )
    assert pending == [qk]
    assert n == 0

    db2 = FakeSession()
    n2, _, pending2, _ = insert_verbatims(
        db2, ROUND_ID, PROJECT_ID, FILE_ID, rows,
        field_selections=[{"field": qk, "included": True, "coding_type": "brands"}],
        single_code_by_type={"brands": False},
        expected_max_mentions=None,
        mentions_decision=None,
    )
    assert pending2 == []
    assert n2 == 3

"""Unit test for process_studio's brands -> fuzzy, then LLM on the leftovers -> orchestration.

ponytail: mocks _process_brands/classify_studio themselves (each already covered by
test_fuzzy.py/test_classification.py) — this only proves process_studio calls both for
'brands' studios and merges their stats, not the engines' internals.
"""
import uuid
from unittest.mock import patch

from app.pipeline.process import _prefilter_garbage, process_studio


class FakeResult:
    def __init__(self, scalar=None, rowcount=0, mapping_rows=None):
        self._scalar = scalar
        self.rowcount = rowcount
        self._mapping_rows = mapping_rows or []

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def all(self):
        return self._mapping_rows


class FakeSession:
    def __init__(self, coding_type, execute=None):
        self._coding_type = coding_type
        self._execute_override = execute

    def execute(self, stmt, params=None):
        if self._execute_override:
            return self._execute_override(stmt, params)
        sql = str(stmt)
        if "select coding_type from studio" in sql:
            return FakeResult(scalar=self._coding_type)
        return FakeResult()

    def commit(self):
        pass


def test_brands_studio_runs_llm_on_fuzzy_leftovers():
    fuzzy_result = {"run_id": "fuzzy-run", "groups_classified": 3, "anomalies": 2, "total": 5}
    llm_result = {"run_id": "llm-run", "groups_classified": 1, "anomalies": 1, "total": 2}

    db = FakeSession(coding_type="brands")
    with (
        patch("app.pipeline.process._process_brands", return_value=fuzzy_result) as fuzzy_mock,
        patch("app.pipeline.process.classify_studio", return_value=llm_result) as llm_mock,
    ):
        result = process_studio(db, uuid.uuid4())

    fuzzy_mock.assert_called_once()
    llm_mock.assert_called_once()
    assert result["groups_classified"] == 4  # 3 fuzzy + 1 llm
    assert result["anomalies"] == 1  # only what the LLM still couldn't resolve
    assert result["total"] == 5


NO_SABE_VARIANTS = ["no sabe", "no se", "nose", "no sabria decir", "no conozco"]


def test_prefilter_auto_codes_system_alias_and_flags_real_garbage():
    """One garbage group (short text) -> anomaly. One 'no se' group -> auto_coded
    straight to its system code, skipping manual review entirely."""
    updates = []  # every UPDATE/INSERT, for assertions below

    def fake_execute(stmt, params=None):
        sql = str(stmt)
        if "from codebooks" in sql:
            return FakeResult(scalar="cb-1")
        if "select id, system_type from codes" in sql:
            return FakeResult(mapping_rows=[{"id": "code-96", "system_type": "no_answer"}])
        if "select id from mention_groups" in sql:
            rows = [{"id": "group-2"}] if params.get("variants") == NO_SABE_VARIANTS else []
            return FakeResult(mapping_rows=rows)
        if sql.strip().startswith("update mention_groups") and "anomaly" in sql:
            return FakeResult(rowcount=1)  # the short-text garbage group
        updates.append((sql, params))
        return FakeResult(rowcount=1)

    with patch("app.pipeline.process._current_codebook_id", return_value="cb-1"):
        total = _prefilter_garbage(FakeSession(coding_type=None, execute=fake_execute), uuid.uuid4())

    assert total == 2  # 1 garbage + 1 "no se" resolved
    assert any("status = 'auto_coded'" in sql for sql, _ in updates)
    insert_sql, insert_params = next((s, p) for s, p in updates if s.strip().startswith("insert into verbatim_codes"))
    assert insert_params["code"] == "code-96"


def test_reasons_studio_skips_fuzzy():
    llm_result = {"run_id": "llm-run", "groups_classified": 2, "anomalies": 0, "total": 2}

    db = FakeSession(coding_type="reasons")
    with (
        patch("app.pipeline.process._process_brands") as fuzzy_mock,
        patch("app.pipeline.process.classify_studio", return_value=llm_result) as llm_mock,
    ):
        result = process_studio(db, uuid.uuid4())

    fuzzy_mock.assert_not_called()
    llm_mock.assert_called_once()
    assert result == llm_result

"""Unit test for process_studio's brands -> fuzzy, then LLM on the leftovers -> orchestration.

ponytail: mocks _process_brands/classify_studio themselves (each already covered by
test_fuzzy.py/test_classification.py) — this only proves process_studio calls both for
'brands' studios and merges their stats, not the engines' internals.
"""
import uuid
from unittest.mock import patch

from app.pipeline.process import process_studio


class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar(self):
        return self._scalar


class FakeSession:
    def __init__(self, coding_type):
        self._coding_type = coding_type

    def execute(self, stmt, params=None):
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

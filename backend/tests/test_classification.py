"""Pure unit test for the classification engine's decision logic.

ponytail: fakes the DB session instead of hitting Postgres — the new schema
uses gen_random_uuid()/now()/on-conflict, which SQLite (used by the other
tests) can't run. This only verifies the matched/unmatched branching and the
SQL params sent, not real persistence.
"""
import uuid
from unittest.mock import patch

from app.pipeline import classify_studio


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class FakeSession:
    def __init__(self, codes, groups):
        self._codes = codes
        self._groups = groups
        self.executed = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, params))
        if "from codes c" in sql:
            return FakeResult(rows=self._codes)
        if "from mention_groups" in sql and "select id, sample_text" in sql:
            return FakeResult(rows=self._groups)
        return FakeResult()

    def commit(self):
        pass


def test_classify_studio_matches_and_flags_anomaly():
    group_matched = {"id": uuid.uuid4(), "sample_text": "muy caro"}
    group_unmatched = {"id": uuid.uuid4(), "sample_text": "asdf"}
    codes = [
        {"id": uuid.uuid4(), "code_number": 1, "label": "Precio"},
        {"id": uuid.uuid4(), "code_number": 97, "label": "Otras menciones"},
    ]
    db = FakeSession(codes=codes, groups=[group_matched, group_unmatched])

    fake_results = [
        {"verbatim_id": str(group_matched["id"]), "code_numbers": [1]},
        {"verbatim_id": str(group_unmatched["id"]), "code_numbers": []},
    ]

    with patch("app.pipeline.classify_llm.classify_batch", return_value=fake_results):
        summary = classify_studio(db, uuid.uuid4())

    assert summary["groups_classified"] == 1
    assert summary["anomalies"] == 1
    assert summary["total"] == 2

    assert any(p.get("id") == group_unmatched["id"] for sql, p in db.executed if p and "anomaly" in sql)
    assert any(p.get("code") == codes[0]["id"] for _, p in db.executed if p and "code" in p)

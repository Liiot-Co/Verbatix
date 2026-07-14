"""Pure unit test for the classification engine's decision logic.

ponytail: fakes the DB session instead of hitting Postgres — the new schema
uses gen_random_uuid()/now()/on-conflict, which SQLite (used by the other
tests) can't run. This only verifies the matched/unmatched branching and the
SQL params sent, not real persistence.
"""
import uuid
from unittest.mock import patch

from app.pipeline import classify_round


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


def test_classify_round_matches_and_flags_anomaly():
    group_matched = {"id": uuid.uuid4(), "sample_text": "muy caro"}
    group_unmatched = {"id": uuid.uuid4(), "sample_text": "asdf"}
    group_low_confidence = {"id": uuid.uuid4(), "sample_text": "algo raro"}
    group_anomaly = {"id": uuid.uuid4(), "sample_text": "Edan"}
    codes = [
        {"id": uuid.uuid4(), "code_number": 1, "label": "Precio", "net_name": None, "system_type": None, "aliases": []},
        {"id": uuid.uuid4(), "code_number": 97, "label": "Otras menciones", "net_name": None, "system_type": "other_mentions", "aliases": []},
        {"id": uuid.uuid4(), "code_number": 95, "label": "Menciones confusas/Incorrectas", "net_name": None, "system_type": "anomaly", "aliases": []},
    ]
    db = FakeSession(codes=codes, groups=[group_matched, group_unmatched, group_low_confidence, group_anomaly])

    fake_results = [
        {"verbatim_id": str(group_matched["id"]), "code_numbers": [1], "confidence": 0.95},
        {"verbatim_id": str(group_unmatched["id"]), "code_numbers": [], "confidence": 0.1},
        # Matched a code, but below llm_confidence_threshold — should still go to human review.
        {"verbatim_id": str(group_low_confidence["id"]), "code_numbers": [1], "confidence": 0.3},
        # High confidence but the code itself is the "anomaly" system code — a human should
        # still confirm it rather than it auto-closing as a confusing/incorrect mention.
        {"verbatim_id": str(group_anomaly["id"]), "code_numbers": [95], "confidence": 0.9},
    ]

    with patch("app.pipeline.llm.classify.classify_batch", return_value=fake_results):
        summary = classify_round(db, uuid.uuid4())

    assert summary["groups_classified"] == 1
    assert summary["anomalies"] == 3
    assert summary["total"] == 4

    def has_param(key, value, stmt_filter=""):
        for sql, p in db.executed:
            if stmt_filter and stmt_filter not in sql:
                continue
            if isinstance(p, list):
                if any(isinstance(item, dict) and item.get(key) == value for item in p):
                    return True
            elif isinstance(p, dict):
                if p.get(key) == value:
                    return True
        return False

    assert has_param("id", group_unmatched["id"], "anomaly")
    assert has_param("id", group_low_confidence["id"], "anomaly")
    assert has_param("id", group_anomaly["id"], "anomaly")
    assert has_param("code", codes[0]["id"])

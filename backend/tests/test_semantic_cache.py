"""Semantic cache write path — mocks embed() so tests never load the real
fastembed model (network/weight cost, per Task C2 acceptance criteria)."""
import uuid
from unittest.mock import patch

from app.pipeline.semantic import cache


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._scalar


class FakeSession:
    def __init__(self):
        self.executed = []

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        return FakeResult()


class FakeLookupSession:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.executed = []

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        return FakeResult(rows=self._rows)


def test_write_embeds_text_and_inserts_with_code_id():
    db = FakeSession()
    code_id = str(uuid.uuid4())

    with patch.object(cache, "embed", return_value=[0.1, 0.2, 0.3]):
        cache.write(db, code_id, "muy fresco", 0.92)

    sql, params = db.executed[0]
    assert "insert into reason_embeddings" in sql
    assert "from codes c where c.id = :code" in sql
    assert params["code"] == code_id
    assert params["text"] == "muy fresco"
    assert params["conf"] == 0.92
    assert params["embedding"] == "[0.1,0.2,0.3]"


def test_to_pgvector_formats_as_bracketed_csv():
    assert cache._to_pgvector([1.0, -2.5, 0.0]) == "[1.0,-2.5,0.0]"


def test_lookup_returns_match_above_threshold():
    code_id = str(uuid.uuid4())
    db = FakeLookupSession(rows=[{"code_id": code_id, "similarity": 0.95}])

    with patch.object(cache, "embed", return_value=[0.1, 0.2]), \
         patch.object(cache.settings, "semantic_cache_similarity_threshold", 0.9):
        match = cache.lookup(db, "cb-1", "muy fresco")

    assert match == {"code_id": code_id, "similarity": 0.95}
    sql, params = db.executed[0]
    assert "reason_embeddings" in sql
    assert "<=>" in sql
    assert params["cb"] == "cb-1"


def test_lookup_returns_none_below_threshold():
    db = FakeLookupSession(rows=[{"code_id": "code-1", "similarity": 0.8}])

    with patch.object(cache, "embed", return_value=[0.1, 0.2]), \
         patch.object(cache.settings, "semantic_cache_similarity_threshold", 0.9):
        match = cache.lookup(db, "cb-1", "algo distinto")

    assert match is None


def test_lookup_returns_none_when_no_rows():
    db = FakeLookupSession(rows=[])

    with patch.object(cache, "embed", return_value=[0.1, 0.2]):
        match = cache.lookup(db, "cb-1", "texto nuevo")

    assert match is None

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

    def scalar(self):
        return self._scalar


class FakeSession:
    def __init__(self):
        self.executed = []

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        return FakeResult()


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

"""create_code() must store the normalized label, not whatever case the analyst typed —
otherwise codebook labels drift (e.g. "Nestlé" vs "nestle" vs "NESTLE") depending on who
created them."""
import uuid

from app.repositories import create_code

CODEBOOK_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


class FakeResult:
    def __init__(self, scalar=None, mapping=None, mappings_list=None):
        self._scalar = scalar
        self._mapping = mapping
        self._mappings_list = mappings_list or []

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def first(self):
        return self._mapping

    def all(self):
        return self._mappings_list


class FakeSession:
    def __init__(self):
        self.insert_params = None

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "lower(label) = lower(:label)" in sql:
            return FakeResult(mapping=None)
        if "where codebook_id = :cb and is_active" in sql and "select id, code_number, label" in sql:
            return FakeResult(mappings_list=[])
        if "coalesce(max(code_number), 0) + 1" in sql:
            return FakeResult(scalar=1)
        if "insert into codes" in sql:
            self.insert_params = params
            return FakeResult()
        return FakeResult()


def test_create_code_stores_normalized_label_not_typed_case():
    db = FakeSession()
    result = create_code(db, CODEBOOK_ID, "Nestlé", None, USER_ID)

    assert result["label"] == "nestle"
    assert db.insert_params["l"] == "nestle"

<<<<<<< Updated upstream
"""Pure unit test for the classification engine's decision logic.

ponytail: fakes the DB session instead of hitting Postgres — the new schema
uses gen_random_uuid()/now()/on-conflict, which SQLite (used by the other
tests) can't run. This only verifies the matched/unmatched branching and the
SQL params sent, not real persistence.
"""
import uuid
from unittest.mock import patch

from app.classification import classify_studio


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
        {"group_id": str(group_matched["id"]), "code_numbers": [1]},
        {"group_id": str(group_unmatched["id"]), "code_numbers": []},
    ]

    with patch("app.classification.engine.classify_batch", return_value=fake_results):
        summary = classify_studio(db, uuid.uuid4())

    assert summary["groups_classified"] == 1
    assert summary["anomalies"] == 1
    assert summary["total"] == 2

    assert any(p.get("id") == group_unmatched["id"] for sql, p in db.executed if p and "anomaly" in sql)
    assert any(p.get("code") == codes[0]["id"] for _, p in db.executed if p and "code" in p)
=======
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.classification import classify_verbatims
from app.models import Base, Code, Codebook, Round, Study, Verbatim

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
Base.metadata.create_all(bind=engine)
TestingSessionLocal = sessionmaker(bind=engine)


def _make_round_with_codebook(db):
    study = Study(id=uuid.uuid4(), project_id=uuid.uuid4(), name="Razones", coding_type="reasons")
    db.add(study)
    round_ = Round(id=uuid.uuid4(), study_id=study.id, name="R1", round_number=1, origin_mode="from_scratch")
    db.add(round_)
    codebook = Codebook(id=uuid.uuid4(), round_id=round_.id)
    db.add(codebook)
    db.flush()

    code_precio = Code(codebook_id=codebook.id, code_number=1, label="Precio")
    code_otras = Code(codebook_id=codebook.id, code_number=97, label="Otras menciones")
    db.add_all([code_precio, code_otras])
    db.commit()
    return round_, code_precio, code_otras


def test_classify_verbatims_assigns_codes_and_flags_unmatched():
    db = TestingSessionLocal()
    round_, code_precio, code_otras = _make_round_with_codebook(db)

    v_matched = Verbatim(round_id=round_.id, original_text="muy caro", coding_status="pending")
    v_unmatched = Verbatim(round_id=round_.id, original_text="asdf", coding_status="pending")
    db.add_all([v_matched, v_unmatched])
    db.commit()

    fake_results = [
        {"verbatim_id": str(v_matched.id), "code_numbers": [1]},
        {"verbatim_id": str(v_unmatched.id), "code_numbers": []},
    ]

    with patch("app.classification.engine.classify_batch", return_value=fake_results):
        summary = classify_verbatims(db, round_.id)

    assert summary == {"classified": 1, "needs_review": 1, "total": 2}
    db.refresh(v_matched)
    db.refresh(v_unmatched)
    assert v_matched.coding_status == "coded"
    assert v_unmatched.coding_status == "needs_review"

    db.close()
>>>>>>> Stashed changes

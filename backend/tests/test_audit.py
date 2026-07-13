"""Unit tests para la orquestación de auditoría (app/pipeline/audit.py).

Misma convención que test_resolution.py: se parchean las funciones de repositorio
(cada una cubierta por su propio camino de integración) — esto prueba que el
orquestador muestrea, secuencia y guarda correctamente.
"""
import uuid
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from app.pipeline.audit import (
    AuditConflict,
    AuditPrecondition,
    approve_session,
    review_item,
    select_sample,
    start_audit_session,
    update_item,
)

STUDIO_ID = uuid.uuid4()
SESSION_ID = str(uuid.uuid4())
ITEM_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
CODE_A = str(uuid.uuid4())
CODE_B = str(uuid.uuid4())


class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar(self):
        return self._scalar


class FakeSession:
    """Responde la única query ad-hoc de start_audit_session: ¿existe el estudio?"""

    def __init__(self, studio_exists=True):
        self.studio_exists = studio_exists
        self.committed = False

    def execute(self, stmt, params=None):
        if "select 1 from studio" in str(stmt):
            return FakeResult(scalar=1 if self.studio_exists else None)
        return FakeResult()

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


def _population(n: int, code_id: str = CODE_A) -> list[dict]:
    return [
        {"verbatim_id": str(uuid.uuid4()),
         "codes": [{"code_id": code_id, "code_number": 1, "label": "alpina", "source": "engine_fuzzy"}]}
        for _ in range(n)
    ]


# ── select_sample: muestreo global, reproducible ──


def test_sample_pct_zero_is_empty():
    assert select_sample(_population(50), 0, seed=7) == []


def test_sample_pct_100_is_whole_population():
    pop = _population(37)
    assert len(select_sample(pop, 100, seed=7)) == 37


def test_sample_size_is_ceil_with_min_one():
    # ceil(10 * 6%) = 1 — con pct > 0 y población no vacía nunca da 0.
    assert len(select_sample(_population(10), 6, seed=7)) == 1
    assert len(select_sample(_population(100), 6, seed=7)) == 6
    assert len(select_sample(_population(3), 1, seed=7)) == 1


def test_sample_is_deterministic_for_same_seed():
    pop = _population(80)
    first = select_sample(pop, 10, seed=42)
    second = select_sample(pop, 10, seed=42)
    assert [v["verbatim_id"] for v in first] == [v["verbatim_id"] for v in second]


def test_sample_changes_with_seed():
    pop = _population(200)
    a = {v["verbatim_id"] for v in select_sample(pop, 5, seed=1)}
    b = {v["verbatim_id"] for v in select_sample(pop, 5, seed=2)}
    assert a != b


def test_bigger_pct_is_superset_of_smaller():
    # Orden total fijo por hash(id:seed) → subir el % solo agrega, no reordena.
    pop = _population(100)
    small = {v["verbatim_id"] for v in select_sample(pop, 5, seed=9)}
    big = {v["verbatim_id"] for v in select_sample(pop, 20, seed=9)}
    assert small <= big


def test_empty_population_yields_empty_sample():
    assert select_sample([], 50, seed=7) == []


# ── start_audit_session ──


class StartMocks:
    def __init__(self, stack: ExitStack, *, existing=None, can_close=True, pct=10.0,
                 run={"id": str(uuid.uuid4()), "random_seed": 42}, population=None):
        base = "app.pipeline.audit."
        self.get_summary = stack.enter_context(
            patch(base + "get_audit_summary", side_effect=[existing, {"id": SESSION_ID, "status": "in_progress"}])
        )
        stack.enter_context(patch(base + "get_resolution_summary",
                                  return_value={"can_close": can_close, "pending": 0 if can_close else 4}))
        stack.enter_context(patch(base + "get_round_audit_percentage", return_value=pct))
        stack.enter_context(patch(base + "get_latest_processing_run", return_value=run))
        self.set_seed = stack.enter_context(patch(base + "set_run_random_seed"))
        stack.enter_context(patch(base + "get_coded_population", return_value=population or []))
        self.create_session = stack.enter_context(patch(base + "create_audit_session", return_value=SESSION_ID))
        self.create_review = stack.enter_context(
            patch(base + "create_audit_code_review", side_effect=lambda *a: str(uuid.uuid4()))
        )
        self.create_item = stack.enter_context(patch(base + "create_audit_item"))
        self.set_status = stack.enter_context(patch(base + "set_studio_status"))
        self.log = stack.enter_context(patch(base + "log_action"))


def test_start_is_idempotent_when_session_exists():
    db = FakeSession()
    existing = {"id": SESSION_ID, "status": "in_progress", "is_stale": False}
    with ExitStack() as stack:
        mocks = StartMocks(stack, existing=existing)
        result = start_audit_session(db, STUDIO_ID, user_id=USER_ID)

    assert result is existing
    mocks.create_session.assert_not_called()
    assert not db.committed


def test_start_requires_studio():
    db = FakeSession(studio_exists=False)
    with ExitStack() as stack:
        StartMocks(stack)
        with pytest.raises(LookupError):
            start_audit_session(db, STUDIO_ID, user_id=USER_ID)


def test_start_requires_resolution_complete():
    db = FakeSession()
    with ExitStack() as stack:
        StartMocks(stack, can_close=False)
        with pytest.raises(AuditPrecondition):
            start_audit_session(db, STUDIO_ID, user_id=USER_ID)
    assert not db.committed


def test_start_materializes_sample_grouped_by_primary_code():
    db = FakeSession()
    pop = _population(3, CODE_A) + _population(2, CODE_B)
    with ExitStack() as stack:
        mocks = StartMocks(stack, pct=100.0, population=pop)
        start_audit_session(db, STUDIO_ID, user_id=USER_ID)

    # pct 100 → 5 items; un review por código presente en la muestra.
    _, _, _, _, total = mocks.create_session.call_args[0]
    assert total == 5
    assert mocks.create_review.call_count == 2
    assert mocks.create_item.call_count == 5
    mocks.set_status.assert_called_once_with(db, STUDIO_ID, "audit_pending")
    assert db.committed


def test_start_with_pct_zero_creates_empty_satisfied_session():
    db = FakeSession()
    with ExitStack() as stack:
        mocks = StartMocks(stack, pct=0.0, population=_population(40))
        start_audit_session(db, STUDIO_ID, user_id=USER_ID)

    _, _, _, _, total = mocks.create_session.call_args[0]
    assert total == 0
    mocks.create_review.assert_not_called()
    mocks.create_item.assert_not_called()


def test_start_persists_seed_when_run_has_none():
    db = FakeSession()
    run_id = str(uuid.uuid4())
    with ExitStack() as stack:
        mocks = StartMocks(stack, run={"id": run_id, "random_seed": None}, population=_population(5))
        start_audit_session(db, STUDIO_ID, user_id=USER_ID)

    mocks.set_seed.assert_called_once()
    assert mocks.set_seed.call_args[0][1] == uuid.UUID(run_id)


def test_start_resamples_only_stale_sessions():
    db = FakeSession()
    stale = {"id": SESSION_ID, "status": "in_progress", "is_stale": True}
    with ExitStack() as stack:
        mocks = StartMocks(stack, existing=stale, population=_population(5))
        start_audit_session(db, STUDIO_ID, user_id=USER_ID, resample=True)
    mocks.create_session.assert_called_once()

    db2 = FakeSession()
    fresh = {"id": SESSION_ID, "status": "in_progress", "is_stale": False}
    with ExitStack() as stack:
        mocks = StartMocks(stack, existing=fresh, population=_population(5))
        result = start_audit_session(db2, STUDIO_ID, user_id=USER_ID, resample=True)
    assert result is fresh
    mocks.create_session.assert_not_called()


# ── review_item ──


def _item(status="pending", session_status="in_progress"):
    return {
        "id": str(ITEM_ID), "status": status, "comment": None,
        "verbatim_id": str(uuid.uuid4()), "codes_snapshot": [],
        "review_id": str(uuid.uuid4()), "corrections_count": 0,
        "session_id": SESSION_ID, "session_status": session_status,
        "total_items": 10, "reviewed_items": 3, "studio_id": str(STUDIO_ID),
    }


class ReviewMocks:
    def __init__(self, stack: ExitStack, item):
        base = "app.pipeline.audit."
        stack.enter_context(patch(base + "get_audit_item", return_value=item))
        self.deactivate = stack.enter_context(patch(base + "deactivate_verbatim_codes"))
        self.assign = stack.enter_context(patch(base + "assign_codes_to_verbatim"))
        self.set_coding = stack.enter_context(patch(base + "set_verbatim_coding_status"))
        self.update_item = stack.enter_context(patch(base + "update_audit_item_review"))
        self.bump = stack.enter_context(patch(base + "increment_review_corrections"))
        self.refresh = stack.enter_context(
            patch(base + "refresh_audit_session_progress",
                  return_value={"total_items": 10, "reviewed_items": 4, "target_met": False})
        )
        stack.enter_context(patch(base + "get_audit_summary", return_value={"status": "in_progress"}))
        stack.enter_context(patch(base + "_current_codebook_id", return_value=uuid.uuid4()))
        self.create_code = stack.enter_context(
            patch(base + "create_code",
                  return_value={"id": str(uuid.uuid4()), "code_number": 7, "label": "nueva", "is_new": True})
        )
        self.log = stack.enter_context(patch(base + "log_action"))


def test_review_item_not_found():
    db = FakeSession()
    with patch("app.pipeline.audit.get_audit_item", return_value=None):
        with pytest.raises(LookupError):
            review_item(db, ITEM_ID, {"action": "correct"}, user_id=USER_ID)


def test_review_blocked_after_approval():
    db = FakeSession()
    with ExitStack() as stack:
        ReviewMocks(stack, _item(session_status="approved"))
        with pytest.raises(AuditConflict):
            review_item(db, ITEM_ID, {"action": "correct"}, user_id=USER_ID)


def test_review_conflict_on_expected_status_mismatch():
    db = FakeSession()
    with ExitStack() as stack:
        ReviewMocks(stack, _item(status="correct"))
        with pytest.raises(AuditConflict):
            review_item(db, ITEM_ID, {"action": "correct"}, user_id=USER_ID, expected_status="pending")


def test_review_correct_is_idempotent():
    db = FakeSession()
    with ExitStack() as stack:
        mocks = ReviewMocks(stack, _item(status="correct"))
        result = review_item(db, ITEM_ID, {"action": "correct"}, user_id=USER_ID)

    assert result["already_reviewed"] is True
    mocks.update_item.assert_not_called()
    assert not db.committed


def test_review_correct_marks_and_commits():
    db = FakeSession()
    with ExitStack() as stack:
        mocks = ReviewMocks(stack, _item())
        result = review_item(db, ITEM_ID, {"action": "correct"}, user_id=USER_ID)

    assert result["status"] == "correct"
    mocks.update_item.assert_called_once()
    mocks.deactivate.assert_not_called()
    mocks.bump.assert_not_called()
    mocks.refresh.assert_called_once()
    mocks.log.assert_called_once()
    assert db.committed


def test_review_reassign_rewrites_codes_as_audit_correction():
    db = FakeSession()
    item = _item()
    with ExitStack() as stack:
        mocks = ReviewMocks(stack, item)
        result = review_item(db, ITEM_ID, {"action": "reassign", "code_ids": [CODE_A]}, user_id=USER_ID)

    assert result["status"] == "reassigned"
    mocks.deactivate.assert_called_once_with(db, uuid.UUID(item["verbatim_id"]))
    mocks.assign.assert_called_once()
    assert mocks.assign.call_args[0][2] == [uuid.UUID(CODE_A)]
    mocks.set_coding.assert_called_once_with(db, uuid.UUID(item["verbatim_id"]), "manually_coded")
    mocks.bump.assert_called_once()
    assert db.committed


def test_review_reassign_to_new_code_creates_it():
    db = FakeSession()
    with ExitStack() as stack:
        mocks = ReviewMocks(stack, _item())
        result = review_item(
            db, ITEM_ID, {"action": "reassign", "code_ids": [], "new_code": {"label": "Nueva"}},
            user_id=USER_ID,
        )

    mocks.create_code.assert_called_once()
    assert result["new_code"]["is_new"] is True
    mocks.assign.assert_called_once()


def test_review_reassign_requires_codes():
    db = FakeSession()
    with ExitStack() as stack:
        ReviewMocks(stack, _item())
        with pytest.raises(ValueError):
            review_item(db, ITEM_ID, {"action": "reassign", "code_ids": []}, user_id=USER_ID)


def test_review_reassign_already_reassigned_does_not_double_count():
    db = FakeSession()
    with ExitStack() as stack:
        mocks = ReviewMocks(stack, _item(status="reassigned"))
        review_item(db, ITEM_ID, {"action": "reassign", "code_ids": [CODE_A]}, user_id=USER_ID)
    mocks.bump.assert_not_called()


def test_review_remove_leaves_verbatim_needing_review():
    db = FakeSession()
    item = _item()
    with ExitStack() as stack:
        mocks = ReviewMocks(stack, item)
        result = review_item(db, ITEM_ID, {"action": "remove"}, user_id=USER_ID)

    assert result["status"] == "reassigned"
    mocks.deactivate.assert_called_once()
    mocks.assign.assert_not_called()
    mocks.set_coding.assert_called_once_with(db, uuid.UUID(item["verbatim_id"]), "needs_review")
    mocks.bump.assert_called_once()


def test_review_invalid_action():
    db = FakeSession()
    with ExitStack() as stack:
        ReviewMocks(stack, _item())
        with pytest.raises(ValueError):
            review_item(db, ITEM_ID, {"action": "explode"}, user_id=USER_ID)


# ── update_item (PATCH) ──


def test_update_item_rejects_reassigned_status():
    db = FakeSession()
    with ExitStack() as stack:
        ReviewMocks(stack, _item())
        with pytest.raises(ValueError):
            update_item(db, ITEM_ID, user_id=USER_ID, status="reassigned")


def test_update_item_blocked_after_approval():
    db = FakeSession()
    with ExitStack() as stack:
        ReviewMocks(stack, _item(session_status="approved"))
        with pytest.raises(AuditConflict):
            update_item(db, ITEM_ID, user_id=USER_ID, comment="tarde")


def test_update_item_edits_comment():
    db = FakeSession()
    with ExitStack() as stack:
        mocks = ReviewMocks(stack, _item(status="correct"))
        result = update_item(db, ITEM_ID, user_id=USER_ID, comment="ojo con este")

    assert result["comment"] == "ojo con este"
    mocks.update_item.assert_called_once()
    assert db.committed


# ── approve_session ──


def _session(status="in_progress", total=10, reviewed=10):
    return {
        "id": SESSION_ID, "studio_id": str(STUDIO_ID), "processing_run_id": None,
        "target_percentage": 10.0, "total_items": total, "reviewed_items": reviewed,
        "target_met": reviewed >= total, "status": status,
        "approved_by": None, "approved_at": None, "created_at": None,
    }


class ApproveMocks:
    def __init__(self, stack: ExitStack, session):
        base = "app.pipeline.audit."
        stack.enter_context(patch(base + "get_audit_session", return_value=session))
        stack.enter_context(patch(base + "get_audit_summary", return_value={"status": "approved"}))
        self.finalize = stack.enter_context(patch(base + "finalize_audit_session"))
        self.set_status = stack.enter_context(patch(base + "set_studio_status"))
        self.log = stack.enter_context(patch(base + "log_action"))


def test_approve_without_session():
    db = FakeSession()
    with patch("app.pipeline.audit.get_audit_session", return_value=None):
        with pytest.raises(LookupError):
            approve_session(db, STUDIO_ID, user_id=USER_ID)


def test_approve_is_idempotent():
    db = FakeSession()
    with ExitStack() as stack:
        mocks = ApproveMocks(stack, _session(status="approved"))
        result = approve_session(db, STUDIO_ID, user_id=USER_ID)

    assert result["already_approved"] is True
    mocks.finalize.assert_not_called()
    assert not db.committed


def test_approve_requires_target_met():
    db = FakeSession()
    with ExitStack() as stack:
        ApproveMocks(stack, _session(total=10, reviewed=7))
        with pytest.raises(AuditPrecondition):
            approve_session(db, STUDIO_ID, user_id=USER_ID)


def test_approve_allows_empty_sample():
    # pct 0 / nada codificado: total 0 items, aprobar directo ("auditado (0%)").
    db = FakeSession()
    with ExitStack() as stack:
        mocks = ApproveMocks(stack, _session(total=0, reviewed=0))
        result = approve_session(db, STUDIO_ID, user_id=USER_ID)

    assert result["already_approved"] is False
    mocks.finalize.assert_called_once()
    mocks.set_status.assert_called_once_with(db, STUDIO_ID, "audit_approved")
    assert db.committed


def test_approve_finalizes_and_marks_studio():
    db = FakeSession()
    with ExitStack() as stack:
        mocks = ApproveMocks(stack, _session())
        approve_session(db, STUDIO_ID, user_id=USER_ID)

    mocks.finalize.assert_called_once_with(db, SESSION_ID, USER_ID)
    mocks.set_status.assert_called_once_with(db, STUDIO_ID, "audit_approved")
    mocks.log.assert_called_once()
    assert db.committed

"""Unit tests for resolve_group's orchestration (app/pipeline/resolution.py).

ponytail: patches the repository functions themselves (each covered by its own
integration path) — this only proves the orchestrator sequences/guards correctly,
same convention as test_process.py.
"""
import uuid
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from app.pipeline.resolution import BelowThresholdError, ResolutionConflict, resolve_group
from app.repositories import add_alias_from_group

ROUND_ID = uuid.uuid4()
SUBPROJECT_ID = uuid.uuid4()
GROUP_ID = uuid.uuid4()
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

    @property
    def rowcount(self):
        return 0


class FakeSession:
    """Answers the ad-hoc queries resolve_group runs itself: codebook_id/round_id
    of the subproject, discard code lookup, and REQ-08 single-code checks."""

    def __init__(self, threshold=3, discard_code_id=None, single_code=False):
        self.threshold = threshold
        self.discard_code_id = discard_code_id
        self.single_code = single_code
        self.committed = False

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).lower().split())
        params = params or {}
        if "codebook_id, round_id" in sql and "from subprojects" in sql:
            return FakeResult(mapping={
                "codebook_id": CODEBOOK_ID, "round_id": ROUND_ID,
                "coding_type": "brands",
            })
        if "code_number = :n" in sql:
            mapping = {"id": self.discard_code_id} if self.discard_code_id else None
            return FakeResult(mapping=mapping)
        if "single_code_per_response" in sql:
            return FakeResult(scalar=self.single_code)
        if "is_system from codes" in sql:
            ids = list(params.get("ids") or [])
            return FakeResult(mappings_list=[
                {"id": cid, "is_system": False} for cid in ids
            ])
        return FakeResult()

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


def _group(status="pending_review", frequency_count=10, subproject_id=SUBPROJECT_ID):
    return {
        "id": str(GROUP_ID), "subproject_id": str(subproject_id), "normalized_text": "alpina",
        "sample_text": "Alpina", "frequency_count": frequency_count, "status": status,
        "verbatims_count": frequency_count, "samples": ["Alpina"], "suggested_code": None,
    }


class Mocks:
    """Enters all repository-function patches for one resolve_group() call and
    exposes each Mock by name."""

    def __init__(self, stack: ExitStack, group: dict, existing_codes=None):
        self.get_group_detail = stack.enter_context(
            patch("app.pipeline.resolution.get_group_detail", return_value=group)
        )
        self.deactivate = stack.enter_context(patch("app.pipeline.resolution.deactivate_group_codes"))
        self.assign = stack.enter_context(
            patch("app.pipeline.resolution.assign_codes_to_group", return_value=group["verbatims_count"])
        )
        self.mark_resolved = stack.enter_context(patch("app.pipeline.resolution.mark_group_resolved"))
        self.log_action = stack.enter_context(patch("app.pipeline.resolution.log_action"))
        self.add_alias = stack.enter_context(patch("app.pipeline.resolution.add_alias_from_group"))
        self.add_negative_alias = stack.enter_context(
            patch("app.pipeline.resolution.add_negative_alias_from_group")
        )
        self.create_code = stack.enter_context(patch("app.pipeline.resolution.create_code"))
        stack.enter_context(patch("app.pipeline.resolution.list_codebook_codes", return_value=existing_codes or []))


def test_already_resolved_is_idempotent_and_untouched():
    group = _group(status="resolved")
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        result = resolve_group(
            FakeSession(), SUBPROJECT_ID, GROUP_ID, {"action": "approve", "code_ids": []}, user_id=USER_ID
        )

    assert result["already_resolved"] is True
    mocks.deactivate.assert_not_called()
    mocks.assign.assert_not_called()
    mocks.mark_resolved.assert_not_called()
    mocks.log_action.assert_not_called()


def test_concurrent_edit_raises_conflict_when_state_diverged():
    group = _group(status="anomaly")
    with ExitStack() as stack:
        Mocks(stack, group)
        with pytest.raises(ResolutionConflict):
            resolve_group(
                FakeSession(), SUBPROJECT_ID, GROUP_ID, {"action": "discard"},
                user_id=USER_ID, expected_status="pending_review",
            )


def test_new_code_below_min_mentions_threshold_fails():
    group = _group(frequency_count=2)  # threshold defaults to 3 in FakeSession
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        with pytest.raises(BelowThresholdError):
            resolve_group(
                FakeSession(threshold=3), SUBPROJECT_ID, GROUP_ID,
                {"action": "approve", "code_ids": [], "new_code": {"label": "Nueva marca"}},
                user_id=USER_ID,
            )
    mocks.create_code.assert_not_called()


def test_force_below_threshold_lets_human_create_code_under_minimum():
    """Bajo el mínimo el motor no crea el código solo, pero un humano SÍ puede
    forzarlo con confirmación explícita (crear 'Quesos artesanales' para agrupar
    menciones raras)."""
    group = _group(frequency_count=1)  # 1 < threshold 3
    new_id = uuid.uuid4()
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        mocks.create_code.return_value = {"id": str(new_id)}
        result = resolve_group(
            FakeSession(threshold=3), SUBPROJECT_ID, GROUP_ID,
            {
                "action": "approve", "code_ids": [],
                "new_code": {"label": "Quesos artesanales"},
                "force_below_threshold": True,
            },
            user_id=USER_ID,
        )

    mocks.create_code.assert_called_once()
    assert result["status"] == "resolved"


def test_multi_code_preserves_selection_order_for_output_index():
    group = _group()
    code_a, code_b = uuid.uuid4(), uuid.uuid4()
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        resolve_group(
            FakeSession(), SUBPROJECT_ID, GROUP_ID,
            {"action": "approve", "code_ids": [str(code_a), str(code_b)]},
            user_id=USER_ID,
        )

    assigned_code_ids = mocks.assign.call_args.args[2]
    assert assigned_code_ids == [code_a, code_b]


def test_reassignment_deactivates_before_reassigning():
    group = _group(status="auto_coded")
    call_order = []
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        mocks.deactivate.side_effect = lambda *a, **k: call_order.append("deactivate")
        mocks.assign.side_effect = lambda *a, **k: call_order.append("assign") or group["verbatims_count"]
        resolve_group(
            FakeSession(), SUBPROJECT_ID, GROUP_ID,
            {"action": "approve", "code_ids": [str(uuid.uuid4())]}, user_id=USER_ID,
        )

    assert call_order == ["deactivate", "assign"]


def test_rejecting_engine_suggestion_creates_approved_negative_memory():
    rejected_id, selected_id = uuid.uuid4(), uuid.uuid4()
    group = _group()
    group["suggested_code"] = {
        "id": str(rejected_id), "code_number": 1, "label": "Bonlé",
    }
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        resolve_group(
            FakeSession(), SUBPROJECT_ID, GROUP_ID,
            {"action": "approve", "code_ids": [str(selected_id)]},
            user_id=USER_ID,
        )

    args = mocks.add_negative_alias.call_args.args
    assert args[1:] == (CODEBOOK_ID, rejected_id, group, USER_ID)


def test_alias_contradiction_stops_assignment_and_persists_conflict():
    group = _group()
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        mocks.add_alias.return_value = False
        db = FakeSession()
        with pytest.raises(ResolutionConflict, match="conflicto"):
            resolve_group(
                db, SUBPROJECT_ID, GROUP_ID,
                {
                    "action": "approve",
                    "code_ids": [str(uuid.uuid4())],
                    "add_alias": True,
                },
                user_id=USER_ID,
            )

    assert db.committed is True
    mocks.deactivate.assert_not_called()
    mocks.assign.assert_not_called()


def test_alias_repository_materializes_both_sides_as_conflict():
    class ConflictSession:
        def __init__(self):
            self.executed = []

        def execute(self, stmt, params=None):
            sql = str(stmt)
            self.executed.append((sql, params))
            if sql.lstrip().startswith("select count(*) from code_aliases"):
                return FakeResult(scalar=0)
            if sql.lstrip().startswith("select code_id from code_aliases"):
                return FakeResult(scalar=uuid.uuid4())
            return FakeResult()

    db = ConflictSession()
    result = add_alias_from_group(
        db, CODEBOOK_ID, uuid.uuid4(), _group(),
    )

    assert result is False
    conflict_sql = "\n".join(sql for sql, _ in db.executed)
    assert "set status = 'conflict'" in conflict_sql
    assert "'positive', 'conflict'" in conflict_sql


def test_alias_repository_human_adjudication_revokes_other_conflict_targets():
    class AdjudicationSession:
        def __init__(self):
            self.executed = []

        def execute(self, stmt, params=None):
            sql = str(stmt)
            self.executed.append((sql, params))
            if sql.lstrip().startswith("select count(*) from code_aliases"):
                return FakeResult(scalar=2)
            return FakeResult(scalar=None)

    db = AdjudicationSession()
    assert add_alias_from_group(db, CODEBOOK_ID, uuid.uuid4(), _group()) is True

    sql = "\n".join(statement for statement, _ in db.executed)
    assert "then 'approved' else 'revoked'" in sql
    assert "on conflict (codebook_id, alias_normalized, code_id) do update" in sql


def test_discard_uses_configured_discard_code():
    group = _group()
    discard_id = uuid.uuid4()
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        resolve_group(
            FakeSession(discard_code_id=discard_id), SUBPROJECT_ID, GROUP_ID,
            {"action": "discard"}, user_id=USER_ID,
        )

    assert mocks.assign.call_args.args[2] == [discard_id]


def test_wrong_subproject_raises_lookup_error():
    group = _group(subproject_id=uuid.uuid4())
    with ExitStack() as stack:
        Mocks(stack, group)
        with pytest.raises(LookupError):
            resolve_group(FakeSession(), SUBPROJECT_ID, GROUP_ID, {"action": "discard"}, user_id=USER_ID)


def test_similar_groups_are_suggested_without_being_auto_resolved():
    """WRatio puede priorizar, pero nunca propaga una decisión sin confirmación."""
    from app.pipeline.resolution import _suggest_similar_pending_groups

    class FakeRowsResult:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeDb:
        def __init__(self, rows):
            self.rows = rows
            self.sql = ""

        def execute(self, stmt, params=None):
            self.sql = str(stmt)
            return FakeRowsResult(self.rows)

    pid = uuid.uuid4()
    rows = [
        {"id": pid, "normalized_text": "pia monte", "status": "below_threshold"},
        {"id": uuid.uuid4(), "normalized_text": "coca cola", "status": "pending_review"},
    ]
    with ExitStack() as stack:
        db = FakeDb(rows)
        result = _suggest_similar_pending_groups(
            db, SUBPROJECT_ID, {"normalized_text": "piamonte"}
        )

    assert "below_threshold" in db.sql
    assert result[0]["id"] == str(pid)
    assert result[0]["normalized_text"] == "pia monte"
    assert result[0]["status"] == "below_threshold"
    assert result[0]["score"] == pytest.approx(94.1176, rel=1e-4)

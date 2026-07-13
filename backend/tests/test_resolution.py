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

STUDIO_ID = uuid.uuid4()
GROUP_ID = uuid.uuid4()
CODEBOOK_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


class FakeResult:
    def __init__(self, scalar=None, mapping=None):
        self._scalar = scalar
        self._mapping = mapping

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def first(self):
        return self._mapping


class FakeSession:
    """Answers the two ad-hoc queries resolve_group runs itself: the studio's
    min_mentions_threshold, and the discard code lookup by code_number."""

    def __init__(self, threshold=3, discard_code_id=None):
        self.threshold = threshold
        self.discard_code_id = discard_code_id
        self.committed = False

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "min_mentions_threshold" in sql:
            return FakeResult(scalar=self.threshold)
        if "code_number = :n" in sql:
            mapping = {"id": self.discard_code_id} if self.discard_code_id else None
            return FakeResult(mapping=mapping)
        return FakeResult()

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


def _group(status="pending_review", frequency_count=10, studio_id=STUDIO_ID):
    return {
        "id": str(GROUP_ID), "studio_id": str(studio_id), "normalized_text": "alpina",
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
        stack.enter_context(patch("app.pipeline.resolution._current_codebook_id", return_value=CODEBOOK_ID))
        self.deactivate = stack.enter_context(patch("app.pipeline.resolution.deactivate_group_codes"))
        self.assign = stack.enter_context(
            patch("app.pipeline.resolution.assign_codes_to_group", return_value=group["verbatims_count"])
        )
        self.mark_resolved = stack.enter_context(patch("app.pipeline.resolution.mark_group_resolved"))
        self.log_action = stack.enter_context(patch("app.pipeline.resolution.log_action"))
        self.add_alias = stack.enter_context(patch("app.pipeline.resolution.add_alias_from_group"))
        self.create_code = stack.enter_context(patch("app.pipeline.resolution.create_code"))
        stack.enter_context(patch("app.pipeline.resolution.list_studio_codes", return_value=existing_codes or []))


def test_already_resolved_is_idempotent_and_untouched():
    group = _group(status="resolved")
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        result = resolve_group(
            FakeSession(), STUDIO_ID, GROUP_ID, {"action": "approve", "code_ids": []}, user_id=USER_ID
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
                FakeSession(), STUDIO_ID, GROUP_ID, {"action": "discard"},
                user_id=USER_ID, expected_status="pending_review",
            )


def test_new_code_below_min_mentions_threshold_fails():
    group = _group(frequency_count=2)  # threshold defaults to 3 in FakeSession
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        with pytest.raises(BelowThresholdError):
            resolve_group(
                FakeSession(threshold=3), STUDIO_ID, GROUP_ID,
                {"action": "approve", "code_ids": [], "new_code": {"label": "Nueva marca"}},
                user_id=USER_ID,
            )
    mocks.create_code.assert_not_called()


def test_multi_code_preserves_selection_order_for_output_index():
    group = _group()
    code_a, code_b = uuid.uuid4(), uuid.uuid4()
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        resolve_group(
            FakeSession(), STUDIO_ID, GROUP_ID,
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
            FakeSession(), STUDIO_ID, GROUP_ID,
            {"action": "approve", "code_ids": [str(uuid.uuid4())]}, user_id=USER_ID,
        )

    assert call_order == ["deactivate", "assign"]


def test_discard_uses_configured_discard_code():
    group = _group()
    discard_id = uuid.uuid4()
    with ExitStack() as stack:
        mocks = Mocks(stack, group)
        resolve_group(
            FakeSession(discard_code_id=discard_id), STUDIO_ID, GROUP_ID,
            {"action": "discard"}, user_id=USER_ID,
        )

    assert mocks.assign.call_args.args[2] == [discard_id]


def test_wrong_studio_raises_lookup_error():
    group = _group(studio_id=uuid.uuid4())
    with ExitStack() as stack:
        Mocks(stack, group)
        with pytest.raises(LookupError):
            resolve_group(FakeSession(), STUDIO_ID, GROUP_ID, {"action": "discard"}, user_id=USER_ID)


def test_auto_resolve_matches_below_threshold_and_returns_texts():
    """«pia monte» (below_threshold) se auto-clasifica al resolver «piamonte» manualmente,
    y la respuesta trae id + texto para el feedback del frontend."""
    from app.pipeline.resolution import _auto_resolve_similar_pending_groups

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
    code_id = uuid.uuid4()
    rows = [
        {"id": pid, "normalized_text": "pia monte", "status": "below_threshold"},
        {"id": uuid.uuid4(), "normalized_text": "coca cola", "status": "pending_review"},
    ]
    with ExitStack() as stack:
        stack.enter_context(patch("app.pipeline.resolution.deactivate_group_codes"))
        assign = stack.enter_context(patch("app.pipeline.resolution.assign_codes_to_group"))
        stack.enter_context(patch("app.pipeline.resolution.mark_group_resolved"))
        log = stack.enter_context(patch("app.pipeline.resolution.log_action"))
        db = FakeDb(rows)
        result = _auto_resolve_similar_pending_groups(
            db, STUDIO_ID, code_id, {"normalized_text": "piamonte"}, USER_ID
        )

    assert "below_threshold" in db.sql
    assert result == [{"id": str(pid), "normalized_text": "pia monte"}]
    assign.assert_called_once()
    assert log.call_args.kwargs["old_value"] == {"status": "below_threshold"}

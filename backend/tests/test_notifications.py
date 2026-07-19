"""Pruebas unitarias del dominio de notificaciones sin tocar una BD real."""
import uuid
from unittest.mock import Mock, patch

from app.services.notifications import emit


class Result:
    def __init__(self, *, rows=None, scalar=None, mapping=None, rowcount=0):
        self.rows = rows or []
        self._scalar = scalar
        self.mapping = mapping
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def one(self):
        return self.mapping

    def first(self):
        return self.mapping

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self


def test_emit_rejects_unknown_type_and_deduplicates_recipients():
    db = Mock()
    first, second, sender = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with patch("app.services.notifications.create_notifications", return_value=2) as create:
        emitted = emit(
            db, notification_type="project_assigned", title="Asignación", body="Nueva",
            related_entity_id=uuid.uuid4(), user_ids=[first, first, second], sender_id=sender,
        )
    assert emitted == 2
    assert set(create.call_args.args[1]) == {first, second}
    assert create.call_args.args[6] == sender


def test_emit_rejects_unknown_type():
    try:
        emit(Mock(), notification_type="unknown", title="", body="", related_entity_id=None, user_ids=[], sender_id=uuid.uuid4())
    except ValueError:
        pass
    else:
        raise AssertionError("Debe validar el catálogo de tipos")


def test_notification_stream_state_uses_one_query_and_returns_zero_signal():
    from app.repositories import notification_stream_state

    db = Mock()
    db.execute.return_value = Result(mapping={"unread_count": 0, "signal": 0})
    assert notification_stream_state(db, uuid.uuid4()) == (0, 0)
    assert db.execute.call_count == 1


def test_reminder_sweep_returns_only_rows_bumped_atomically():
    from app.repositories import sweep_reminders

    notification_id, user_id = uuid.uuid4(), uuid.uuid4()
    db = Mock()
    db.execute.return_value = Result(rows=[{"id": notification_id, "user_id": user_id}])
    assert sweep_reminders(db, max_reminders=3, window_seconds=14400) == [{"id": notification_id, "user_id": user_id}]
    sql = str(db.execute.call_args.args[0])
    assert "reminder_count <" in sql
    assert "last_reminded_at = now()" in sql


def test_mark_read_is_scoped_to_the_current_user():
    from app.repositories import mark_notification_read

    db = Mock()
    db.execute.return_value = Result(scalar=uuid.uuid4())
    user_id, notification_id = uuid.uuid4(), uuid.uuid4()
    assert mark_notification_read(db, user_id, notification_id) is True
    sql = str(db.execute.call_args.args[0])
    assert "user_id = :user_id" in sql


def test_admin_notify_emits_one_notification_per_new_project():
    from app.routers import admin

    db = Mock()
    target, actor = uuid.uuid4(), uuid.uuid4()
    first, second = uuid.uuid4(), uuid.uuid4()
    with patch.object(admin, "emit") as emit_mock:
        admin._notify_new_assignments(db, target, [first, second], actor)
    assert emit_mock.call_count == 2
    related = {call.kwargs["related_entity_id"] for call in emit_mock.call_args_list}
    assert related == {first, second}
    assert all(call.kwargs["notification_type"] == "project_assigned" for call in emit_mock.call_args_list)
    assert all(call.kwargs["user_ids"] == [target] for call in emit_mock.call_args_list)
    assert db.commit.call_count == 2


def test_admin_notify_skips_self_assignment():
    from app.routers import admin

    db = Mock()
    same = uuid.uuid4()
    with patch.object(admin, "emit") as emit_mock:
        admin._notify_new_assignments(db, same, [uuid.uuid4()], same)
    emit_mock.assert_not_called()


def test_replace_assignments_reports_only_newly_granted_projects():
    from app.routers import admin

    target, actor = uuid.uuid4(), uuid.uuid4()
    kept, added = uuid.uuid4(), uuid.uuid4()
    db = Mock()

    def execute(query, params=None):
        sql = str(query)
        if "select count(*) from projects" in sql:
            return Result(scalar=2)
        if "select project_id from assignments" in sql:
            result = Result()
            result.all = lambda: [kept]  # type: ignore[method-assign]
            return Mock(scalars=lambda: result)
        return Result()

    db.execute.side_effect = execute
    newly = admin._replace_assignments(db, target, [kept, added], actor)
    assert newly == [added]

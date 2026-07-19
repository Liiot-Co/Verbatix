"""Presencia declarada: cambios atómicos, no-ops y contratos de routers."""
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import uuid

import pytest
from fastapi import HTTPException

from app.repositories import set_user_presence
from app.routers import admin, auth, presence


class Result:
    def __init__(self, *, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows


def test_valid_presence_update_commits_and_returns_changed_at():
    db = Mock()
    user_id = uuid.uuid4()
    changed_at = datetime.now(timezone.utc)
    with patch.object(presence, "set_user_presence", return_value=changed_at):
        response = presence.update_my_presence(
            presence.PresenceIn(status="en_break"), db=db, user={"id": user_id},
        )
    assert response == {"status": "en_break", "changed_at": changed_at}
    db.commit.assert_called_once()


def test_invalid_presence_is_rejected_without_writing():
    db = Mock()
    with pytest.raises(HTTPException) as error:
        presence.update_my_presence(presence.PresenceIn(status="teletransportado"), db=db, user={"id": uuid.uuid4()})
    assert error.value.status_code == 422
    db.execute.assert_not_called()
    db.commit.assert_not_called()


def test_same_presence_is_a_noop():
    db = Mock()
    db.execute.return_value = Result(scalar="en_break")
    assert set_user_presence(db, uuid.uuid4(), "en_break") is None
    assert db.execute.call_count == 1


def test_change_closes_the_previous_event_and_opens_one_new_event():
    db = Mock()
    changed_at = datetime.now(timezone.utc)
    db.execute.side_effect = [
        Result(scalar="disponible"),
        Result(scalar=changed_at),
        Result(),
        Result(),
    ]
    assert set_user_presence(db, uuid.uuid4(), "almorzando") == changed_at
    statements = [str(call.args[0]) for call in db.execute.call_args_list]
    assert "update users" in statements[1].lower()
    assert "ended_at = now()" in statements[2]
    assert "insert into user_status_events" in statements[3].lower()


def test_login_resets_presence_before_issuing_the_session():
    db = Mock()
    user_id = uuid.uuid4()
    row = {"id": user_id, "email": "persona@example.com", "password_hash": "hash", "account_status": "active"}
    db.execute.return_value.mappings.return_value.first.return_value = row
    with patch.object(auth, "verify_password", return_value=True), \
         patch.object(auth, "reset_user_presence_on_login") as reset, \
         patch.object(auth, "_session_response", return_value={"access_token": "token"}):
        assert auth.login(auth.CredentialsIn(email="persona@example.com", password="secreto12"), db=db) == {"access_token": "token"}
    reset.assert_called_once_with(db, user_id)


def test_admin_users_response_includes_presence_fields():
    db = Mock()
    user_id = uuid.uuid4()
    changed_at = datetime.now(timezone.utc)
    db.execute.return_value.mappings.return_value.all.return_value = [{
        "id": user_id, "email": "persona@example.com", "name": "Persona", "account_status": "active",
        "presence_status": "en_reunion", "presence_changed_at": changed_at, "created_at": changed_at,
        "roles": ["admin"], "assignments_count": 0, "project_ids": [],
    }]
    with patch.object(admin, "require_admin"):
        result = admin.list_users(db=db, user={"id": uuid.uuid4()})
    assert result[0]["presence_status"] == "en_reunion"
    assert result[0]["presence_changed_at"] == changed_at

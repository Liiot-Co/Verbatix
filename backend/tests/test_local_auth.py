"""Primitivas críticas de autenticación local y matriz acumulable."""
from datetime import timezone

import pytest

from app.core.access import ALL_CAPABILITIES, CAPABILITIES_BY_ROLE
from app.core.security import hash_password, issue_session, normalize_email, sha256, verify_password


class FakeResult:
    pass


class FakeSession:
    def __init__(self):
        self.params = None

    def execute(self, _statement, params=None):
        self.params = params
        return FakeResult()


def test_email_normalization_is_case_insensitive_and_trimmed():
    assert normalize_email("  Persona@Example.COM ") == "persona@example.com"


def test_password_hash_is_argon2id_and_never_contains_plaintext():
    password = "Correct-Horse-92"
    password_hash = hash_password(password)
    assert password_hash.startswith("$argon2id$")
    assert password not in password_hash
    assert verify_password(password_hash, password)
    assert not verify_password(password_hash, "incorrecta")


def test_session_persists_only_sha256_and_is_opaque():
    db = FakeSession()
    token, expires_at = issue_session(db, "user-id")
    assert "." not in token  # no es JWT
    assert db.params["h"] == sha256(token)
    assert token != db.params["h"]
    assert expires_at.tzinfo == timezone.utc


@pytest.mark.parametrize(
    ("roles", "required", "forbidden"),
    [
        (["admin"], ALL_CAPABILITIES, set()),
        (["codificador"], {"resolution.edit", "audit.edit", "reports.export"}, {"audit.approve", "rounds.manage"}),
        (["supervisor"], {"audit.approve", "reports.export"}, {"resolution.view", "projects.manage"}),
        (["codificador", "supervisor"], {"resolution.edit", "audit.approve", "reports.export"}, {"projects.manage"}),
    ],
)
def test_role_capabilities_accumulate(roles, required, forbidden):
    capabilities = {cap for role in roles for cap in CAPABILITIES_BY_ROLE[role]}
    assert required <= capabilities
    assert not (forbidden & capabilities)

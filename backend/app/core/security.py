"""Primitivas de autenticación local: Argon2id, tokens opacos y recuperación."""
from __future__ import annotations

import hashlib
import secrets
import string
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings


password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_session(db: Session, user_id) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)
    db.execute(
        text("""
            insert into auth_sessions (user_id, token_hash, expires_at)
            values (:u, :h, :e)
        """),
        {"u": user_id, "h": sha256(token), "e": expires_at},
    )
    return token, expires_at


def new_recovery_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(20))
    return "-".join(raw[i:i + 5] for i in range(0, 20, 5))


def rotate_recovery_code(db: Session, user_id) -> str:
    code = new_recovery_code()
    db.execute(
        text("""
            update password_recovery_codes set revoked_at = now()
            where user_id = :u and used_at is null and revoked_at is null
        """),
        {"u": user_id},
    )
    db.execute(
        text("insert into password_recovery_codes (user_id, code_hash) values (:u, :h)"),
        {"u": user_id, "h": sha256(code)},
    )
    return code


def revoke_sessions(db: Session, user_id) -> None:
    db.execute(
        text("update auth_sessions set revoked_at = now() where user_id = :u and revoked_at is null"),
        {"u": user_id},
    )


def bootstrap_local_admin(db: Session) -> None:
    """Inicializa una única vez la contraseña de la cuenta admin preexistente."""
    email = normalize_email(settings.local_admin_email)
    row = db.execute(
        text("""
            select u.id, u.password_hash
            from users u
            join user_roles ur on ur.user_id = u.id and ur.role_code = 'admin'
            where u.id = :bootstrap_id or lower(btrim(u.email)) = :email
            order by (u.id = :bootstrap_id) desc
            limit 1
        """),
        {"bootstrap_id": settings.local_dev_user_id, "email": email},
    ).mappings().first()
    if not row:
        raise RuntimeError("No existe la cuenta administradora bootstrap local")
    if row["password_hash"]:
        return
    if not settings.local_admin_password:
        raise RuntimeError(
            "LOCAL_ADMIN_PASSWORD es obligatorio mientras la cuenta bootstrap no tenga contraseña"
        )
    if len(settings.local_admin_password) < 8:
        raise RuntimeError("LOCAL_ADMIN_PASSWORD debe tener al menos 8 caracteres")
    db.execute(
        text("""
            update users
            set email = :email, name = :name, password_hash = :password_hash,
                account_status = 'active', is_active = true,
                approved_at = coalesce(approved_at, now())
            where id = :id
        """),
        {
            "id": row["id"], "email": email, "name": settings.local_admin_name.strip(),
            "password_hash": hash_password(settings.local_admin_password),
        },
    )
    db.commit()

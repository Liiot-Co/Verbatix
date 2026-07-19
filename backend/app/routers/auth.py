"""Registro, login, sesiones y recuperación para PostgreSQL local."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.access import CAPABILITIES_BY_ROLE
from app.core.auth import CurrentUser, session_user
from app.core.database import get_db
from app.core.security import (
    hash_password,
    issue_session,
    normalize_email,
    revoke_sessions,
    rotate_recovery_code,
    sha256,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
ROLE_CODES = ("admin", "codificador", "supervisor")


class CredentialsIn(BaseModel):
    email: str
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        email = normalize_email(value)
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("Correo inválido")
        return email


class SignUpIn(CredentialsIn):
    name: str | None = Field(default=None, max_length=120)


class RecoverIn(CredentialsIn):
    recovery_code: str = Field(min_length=20, max_length=40)


def _roles_and_capabilities(db: Session, user_id) -> tuple[list[str], list[str]]:
    roles = list(db.execute(
        text("select role_code from user_roles where user_id = :id order by role_code"),
        {"id": user_id},
    ).scalars().all())
    capabilities = sorted({cap for role in roles for cap in CAPABILITIES_BY_ROLE.get(role, set())})
    return roles, capabilities


def _session_response(db: Session, row, *, recovery_code: str | None = None) -> dict:
    token, expires_at = issue_session(db, row["id"])
    db.commit()
    result = {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": {"id": str(row["id"]), "email": row["email"]},
    }
    if recovery_code is not None:
        result["recovery_code"] = recovery_code
    return result


@router.post("/signup", status_code=201)
def signup(payload: SignUpIn, db: Session = Depends(get_db)):
    user_id = uuid.uuid4()
    try:
        db.execute(
            text("""
                insert into users
                    (id, email, name, password_hash, account_status, is_active)
                values (:id, :email, :name, :password_hash, 'pending', true)
            """),
            {
                "id": user_id,
                "email": payload.email,
                "name": payload.name.strip() if payload.name and payload.name.strip() else payload.email.split("@")[0],
                "password_hash": hash_password(payload.password),
            },
        )
        recovery_code = rotate_recovery_code(db, user_id)
        row = {"id": user_id, "email": payload.email}
        return _session_response(db, row, recovery_code=recovery_code)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "No fue posible registrar la cuenta") from exc


@router.post("/login")
def login(payload: CredentialsIn, db: Session = Depends(get_db)):
    row = db.execute(
        text("""
            select id, email, password_hash, account_status
            from users where lower(btrim(email)) = :email
        """),
        {"email": payload.email},
    ).mappings().first()
    if not row or not verify_password(row["password_hash"], payload.password):
        raise HTTPException(401, "Correo o contraseña incorrectos")
    if row["account_status"] == "suspended":
        raise HTTPException(403, "Cuenta suspendida")
    return _session_response(db, row)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    user: CurrentUser = Depends(session_user),
    db: Session = Depends(get_db),
):
    db.execute(
        text("update auth_sessions set revoked_at = now() where id = :id"),
        {"id": user["session_id"]},
    )
    db.commit()
    return response


@router.get("/me")
def get_me(user: CurrentUser = Depends(session_user), db: Session = Depends(get_db)):
    row = db.execute(
        text("""
            select id, email, name, account_status, created_at
            from users where id = :id
        """),
        {"id": user["id"]},
    ).mappings().one()
    roles, capabilities = _roles_and_capabilities(db, user["id"])
    assignments_count = db.execute(
        text("select count(*) from assignments where user_id = :id and status = 'active' and revoked_at is null"),
        {"id": user["id"]},
    ).scalar_one()
    return {
        "id": str(row["id"]), "email": row["email"], "name": row["name"],
        "roles": roles, "capabilities": capabilities,
        "account_status": row["account_status"],
        "assignments_count": assignments_count,
        "created_at": row["created_at"],
    }


@router.post("/forgot-password")
def forgot_password():
    return {"message": "Usa el código personal de recuperación entregado al registrarte."}


@router.post("/recover")
def recover(payload: RecoverIn, db: Session = Depends(get_db)):
    row = db.execute(
        text("""
            select u.id, u.email, prc.id as recovery_id
            from users u
            join password_recovery_codes prc on prc.user_id = u.id
            where lower(btrim(u.email)) = :email and prc.code_hash = :code_hash
              and prc.used_at is null and prc.revoked_at is null
            order by prc.created_at desc limit 1
        """),
        {"email": payload.email, "code_hash": sha256(payload.recovery_code.strip().upper())},
    ).mappings().first()
    if not row:
        raise HTTPException(400, "No fue posible recuperar la cuenta con esos datos")
    db.execute(
        text("update users set password_hash = :h where id = :id"),
        {"h": hash_password(payload.password), "id": row["id"]},
    )
    db.execute(
        text("update password_recovery_codes set used_at = now() where id = :id"),
        {"id": row["recovery_id"]},
    )
    revoke_sessions(db, row["id"])
    recovery_code = rotate_recovery_code(db, row["id"])
    return _session_response(db, row, recovery_code=recovery_code)

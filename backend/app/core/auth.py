"""Autenticación local mediante sesiones opacas almacenadas como SHA-256."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import sha256


class CurrentUser(dict):
    """Usuario de sesión; incluye id, correo, estado y session_id."""


_bearer = HTTPBearer(auto_error=False)


def session_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if not cred or cred.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión requerida")
    row = db.execute(
        text("""
            select u.id, u.email, u.name, u.account_status, s.id as session_id
            from auth_sessions s
            join users u on u.id = s.user_id
            where s.token_hash = :h and s.revoked_at is null and s.expires_at > now()
        """),
        {"h": sha256(cred.credentials)},
    ).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
    return CurrentUser(dict(row))


def current_user(user: CurrentUser = Depends(session_user)) -> CurrentUser:
    if user["account_status"] == "pending":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cuenta pendiente de aprobación")
    if user["account_status"] == "suspended":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cuenta suspendida")
    return user

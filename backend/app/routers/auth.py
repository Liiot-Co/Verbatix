import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import require_admin
from app.core.auth import CurrentUser, current_user
from app.core.config import settings
from app.core.database import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

ROLE_CODES = ("admin", "codificador", "supervisor")


class LoginIn(BaseModel):
    email: str
    password: str


class SignUpIn(BaseModel):
    email: str
    password: str


@router.post("/signup")
def signup(payload: SignUpIn):
    """Crea cuenta via Supabase Auth. Devuelve JWT si auto-confirm está activo."""
    if settings.app_mode == "local":
        # No hay cuentas en local: cualquier email/password "funciona" y
        # entra como el dev user fijo (igual que /login).
        return {
            "id": settings.local_dev_user_id,
            "email": payload.email,
            "access_token": "local-dev-token",
            "token_type": "bearer",
        }
    r = httpx.post(
        f"{settings.supabase_url.rstrip('/')}/auth/v1/signup",
        headers={
            "apikey": settings.supabase_secret_key,
            "Content-Type": "application/json",
        },
        json={"email": payload.email, "password": payload.password},
        timeout=30,
    )
    if r.status_code != 200:
        detail = r.json().get("msg") or r.json().get("error_description") or r.text
        raise HTTPException(r.status_code, f"Registro falló: {detail}")
    data = r.json()
    return {
        "id": data.get("id"),
        "email": data.get("email"),
        "access_token": data.get("access_token"),
        "token_type": data.get("token_type", "bearer"),
    }


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(payload: LoginIn):
    """Obtiene un JWT de Supabase Auth."""
    if settings.app_mode == "local":
        # Sin Supabase Auth que consultar: cualquier email/password entra
        # como el dev user fijo (current_user() en app.core.auth ya lo
        # devuelve sin mirar el token; este solo alimenta la pantalla de
        # login para que el flujo normal del front funcione).
        return {
            "access_token": "local-dev-token",
            "refresh_token": None,
            "token_type": "bearer",
            "expires_in": None,
            "user": {"id": settings.local_dev_user_id, "email": payload.email or settings.local_dev_user_email},
        }
    r = httpx.post(
        f"{settings.supabase_url.rstrip('/')}/auth/v1/token?grant_type=password",
        headers={
            "apikey": settings.supabase_secret_key,
            "Content-Type": "application/json",
        },
        json={"email": payload.email, "password": payload.password},
        timeout=30,
    )
    if r.status_code != 200:
        raise HTTPException(401, f"Login falló: {r.text}")
    data = r.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "token_type": data.get("token_type", "bearer"),
        "expires_in": data.get("expires_in"),
        "user": {"id": data.get("user", {}).get("id"), "email": data.get("user", {}).get("email")},
    }


@router.get("/me")
def get_me(user: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    row = db.execute(
        text("select id, email, name, is_active, created_at from users where id = :id"),
        {"id": user["id"]},
    ).mappings().first()

    if not row:
        # Normalmente lo crea el trigger handle_new_user() al registrarse en
        # Supabase Auth (001_schema_v8.sql); esto es solo el respaldo si /me
        # se llama antes de que esa fila exista todavía.
        db.execute(
            text("""
                insert into users (id, email, name)
                values (:id, :email, :name)
                on conflict (id) do nothing
            """),
            {
                "id": user["id"],
                "email": user.get("email") or "",
                "name": (user.get("email") or "User").split("@")[0],
            },
        )
        db.execute(
            text("""
                insert into user_roles (id, user_id, role_code)
                values (gen_random_uuid(), :id, 'codificador')
                on conflict (user_id, role_code) do nothing
            """),
            {"id": user["id"]},
        )
        db.commit()
        row = db.execute(
            text("select id, email, name, is_active, created_at from users where id = :id"),
            {"id": user["id"]},
        ).mappings().first()

    roles = db.execute(
        text("select role_code from user_roles where user_id = :id"),
        {"id": user["id"]},
    ).scalars().all()

    return {
        "id": str(row["id"]),
        "email": row["email"],
        "name": row["name"],
        "roles": list(roles),
        "is_active": row["is_active"],
        "created_at": row["created_at"],
    }


class RoleIn(BaseModel):
    role_code: str


@router.post("/users/{user_id}/roles", status_code=201)
def assign_role(
    user_id: uuid.UUID,
    payload: RoleIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    if payload.role_code not in ROLE_CODES:
        raise HTTPException(400, f"role_code debe ser uno de {ROLE_CODES}")
    db.execute(
        text("""
            insert into user_roles (id, user_id, role_code)
            values (gen_random_uuid(), :uid, :role)
            on conflict (user_id, role_code) do nothing
        """),
        {"uid": user_id, "role": payload.role_code},
    )
    db.commit()
    return {"user_id": str(user_id), "role_code": payload.role_code}


@router.delete("/users/{user_id}/roles/{role_code}", status_code=204)
def revoke_role(
    user_id: uuid.UUID,
    role_code: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    db.execute(
        text("delete from user_roles where user_id = :uid and role_code = :role"),
        {"uid": user_id, "role": role_code},
    )
    db.commit()

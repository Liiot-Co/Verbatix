import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, current_user
from app.core.config import settings
from app.core.database import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
        text("select id, email, name, role, is_active, created_at from profiles where id = :id"),
        {"id": user["id"]},
    ).mappings().first()

    if not row:
        db.execute(
            text("""
                insert into profiles (id, email, name, role)
                values (:id, :email, :name, 'analyst')
                on conflict (id) do nothing
            """),
            {
                "id": user["id"],
                "email": user.get("email") or "",
                "name": (user.get("email") or "User").split("@")[0],
            },
        )
        db.commit()
        row = db.execute(
            text("select id, email, name, role, is_active, created_at from profiles where id = :id"),
            {"id": user["id"]},
        ).mappings().first()

    return {
        "id": str(row["id"]),
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "is_active": row["is_active"],
        "created_at": row["created_at"],
    }

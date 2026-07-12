import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, current_user
from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(payload: LoginIn):
    """Obtiene un JWT de Supabase Auth (para pegarlo en Authorize de /docs)."""
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
        "token_type": data.get("token_type", "bearer"),
        "expires_in": data.get("expires_in"),
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

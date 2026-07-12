from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, current_user
from app.database import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


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

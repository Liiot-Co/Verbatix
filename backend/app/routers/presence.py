"""Estado de presencia declarado por la persona usuaria."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.repositories import set_user_presence

router = APIRouter(prefix="/api/v1/presence", tags=["presence"])
PRESENCE_STATUSES = {"disponible", "almorzando", "en_el_bano", "en_break", "en_reunion"}


class PresenceIn(BaseModel):
    status: str


@router.put("/me")
def update_my_presence(
    payload: PresenceIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    if payload.status not in PRESENCE_STATUSES:
        raise HTTPException(422, "Estado de presencia inválido")
    changed_at = set_user_presence(db, user["id"], payload.status)
    if changed_at is None:
        changed_at = db.execute(
            text("select presence_changed_at from users where id = :id"),
            {"id": user["id"]},
        ).scalar()
    db.commit()
    return {"status": payload.status, "changed_at": changed_at}

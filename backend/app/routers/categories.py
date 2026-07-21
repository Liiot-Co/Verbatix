"""CRUD de Categoría: nivel OPCIONAL entre Estudio y Ronda (sección 1 del
documento v8) — si el Estudio no la usa, no se crea ninguna."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import require_capability, require_project
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db

router = APIRouter(prefix="/api/v1/projects/{study_id}/categories", tags=["categories"])


class CategoryIn(BaseModel):
    name: str


@router.post("", status_code=201)
def create_category(
    study_id: uuid.UUID,
    payload: CategoryIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_project(db, study_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    cid = uuid.uuid4()
    db.execute(
        text("insert into categories (id, study_id, name) values (:id, :study_id, :name)"),
        {"id": cid, "study_id": study_id, "name": payload.name},
    )
    db.commit()
    return {"id": str(cid), "study_id": str(study_id), "name": payload.name}


@router.get("")
def list_categories(
    study_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_project(db, study_id, user["id"])
    rows = db.execute(
        text("select id, name from categories where study_id = :id order by name"),
        {"id": study_id},
    ).mappings().all()
    return [{"id": str(r["id"]), "name": r["name"]} for r in rows]


@router.delete("/{category_id}", status_code=204)
def delete_category(
    study_id: uuid.UUID,
    category_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_project(db, study_id, user["id"])
    require_capability(db, user["id"], "rounds.manage")
    deleted = db.execute(
        text("delete from categories where id = :id and study_id = :study_id returning id"),
        {"id": category_id, "study_id": study_id},
    ).scalar()
    if not deleted:
        raise HTTPException(404, "Categoría no encontrada")
    db.commit()

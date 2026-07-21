"""CRUD de Proyecto (`proyectos`): nivel jerárquico superior que agrupa uno o
varios Estudios (`projects`, sección 1/2.2 del documento v8)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import require_admin
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db

router = APIRouter(prefix="/api/v1/proyectos", tags=["proyectos"])


class ProyectoIn(BaseModel):
    name: str


@router.post("", status_code=201)
def create_proyecto(
    payload: ProyectoIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    pid = uuid.uuid4()
    db.execute(
        text("insert into projects (id, name, created_by) values (:id, :name, :u)"),
        {"id": pid, "name": payload.name, "u": user["id"]},
    )
    db.commit()
    return {"id": str(pid), "name": payload.name}


@router.get("")
def list_proyectos(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    rows = db.execute(
        text("""
            select p.id, p.name, p.created_at, count(pr.id) as projects_count
            from projects p
            left join studios pr on pr.proyecto_id = p.id
            group by p.id
            order by p.created_at desc
        """),
        {},
    ).mappings().all()
    return [
        {"id": str(r["id"]), "name": r["name"], "projects_count": r["projects_count"], "created_at": r["created_at"]}
        for r in rows
    ]


@router.get("/{proyecto_id}")
def get_proyecto(
    proyecto_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    proyecto = db.execute(
        text("select id, name, created_at from projects where id = :id"),
        {"id": proyecto_id},
    ).mappings().first()
    if not proyecto:
        raise HTTPException(404, "Proyecto no encontrado")
    return {"id": str(proyecto["id"]), "name": proyecto["name"], "created_at": proyecto["created_at"]}


@router.get("/{proyecto_id}/projects")
def list_proyecto_projects(
    proyecto_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Los Estudios (`projects`) que cuelgan de este Proyecto."""
    require_admin(db, user["id"])
    rows = db.execute(
        text("""
            select p.id, p.external_code, p.name, p.created_at
            from studios p
            join projects pr on pr.id = p.proyecto_id
            where p.proyecto_id = :id
            order by p.created_at desc
        """),
        {"id": proyecto_id},
    ).mappings().all()
    return [
        {"id": str(r["id"]), "external_code": r["external_code"], "name": r["name"], "created_at": r["created_at"]}
        for r in rows
    ]


@router.patch("/{proyecto_id}")
def update_proyecto(
    proyecto_id: uuid.UUID,
    payload: ProyectoIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    updated = db.execute(
        text("update projects set name = :name where id = :id returning id"),
        {"name": payload.name, "id": proyecto_id},
    ).scalar()
    if not updated:
        raise HTTPException(404, "Proyecto no encontrado")
    db.commit()
    return {"id": str(proyecto_id), "name": payload.name}


@router.delete("/{proyecto_id}", status_code=204)
def delete_proyecto(
    proyecto_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    deleted = db.execute(
        text("delete from projects where id = :id returning id"),
        {"id": proyecto_id},
    ).scalar()
    if not deleted:
        raise HTTPException(404, "Proyecto no encontrado")
    db.commit()

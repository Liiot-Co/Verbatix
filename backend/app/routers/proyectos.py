"""CRUD de Proyecto (`proyectos`): nivel jerárquico superior que agrupa uno o
varios Estudios (`projects`, sección 1/2.2 del documento v8)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import require_active_account, require_admin, visible_study_ids
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
    require_active_account(db, user["id"])
    pid = uuid.uuid4()
    db.execute(
        text("insert into projects (id, name, created_by) values (:id, :name, :u)"),
        {"id": pid, "name": payload.name, "u": user["id"]},
    )
    db.commit()
    return {"id": str(pid), "name": payload.name}


@router.get("")
def list_proyectos(
    q: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_active_account(db, user["id"])
    study_ids = visible_study_ids(db, user["id"])
    
    rows = db.execute(
        text("""
            select p.id, p.name, p.created_at, count(pr.id) as projects_count
            from projects p
            left join studies pr on pr.project_id = p.id
            where (:q is null or p.name ilike '%' || :q || '%')
              and (:study_ids is null or p.created_by = :u or exists (
                  select 1 from studies pr2
                  where pr2.project_id = p.id and pr2.id = any(:study_ids)
              ))
            group by p.id
            order by p.created_at desc
        """),
        {"q": q, "study_ids": study_ids, "u": user["id"]},
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
    require_active_account(db, user["id"])
    proyecto = db.execute(
        text("select id, name, created_at from projects where id = :id"),
        {"id": proyecto_id},
    ).mappings().first()

    if not proyecto:
        raise HTTPException(404, "Proyecto no encontrado")

    rows = db.execute(
        text("""
            select p.id, p.external_code, p.name, p.created_at, p.project_id,
                   count(distinct r.id) as rounds_count,
                   coalesce(
                     case
                       when count(distinct sp.coding_type) = 2 then 'both'
                       when max(sp.coding_type) = 'brands' then 'brands'
                       when max(sp.coding_type) = 'reasons' then 'reasons'
                     end,
                     'none'
                   ) as analytic_target
            from studies p
            left join rounds r on r.study_id = p.id
            left join subprojects sp on sp.round_id = r.id
            where p.project_id = :id
            group by p.id
            order by p.created_at desc
        """),
        {"id": proyecto_id},
    ).mappings().all()

    return {
        "kind": "proyecto",
        "id": str(proyecto["id"]),
        "name": proyecto["name"],
        "created_at": proyecto["created_at"],
        "studies": [
            {
                "id": str(r["id"]),
                "external_code": r["external_code"],
                "name": r["name"],
                "created_at": r["created_at"],
                "project_id": str(proyecto_id),
                "rounds_count": r["rounds_count"],
                "analytic_target": r["analytic_target"],
            }
            for r in rows
        ],
    }





@router.patch("/{project_id}")
def update_proyecto(
    project_id: uuid.UUID,
    payload: ProyectoIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    updated = db.execute(
        text("update projects set name = :name where id = :id returning id"),
        {"name": payload.name, "id": project_id},
    ).scalar()
    if not updated:
        raise HTTPException(404, "Proyecto no encontrado")
    db.commit()
    return {"id": str(project_id), "name": payload.name}


@router.delete("/{project_id}", status_code=204)
def delete_proyecto(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    deleted = db.execute(
        text("delete from projects where id = :id returning id"),
        {"id": project_id},
    ).scalar()
    if not deleted:
        raise HTTPException(404, "Proyecto no encontrado")
    db.commit()

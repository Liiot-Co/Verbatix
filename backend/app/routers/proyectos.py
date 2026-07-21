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
    q: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    rows = db.execute(
        text("""
            select p.id, p.name, p.created_at, count(pr.id) as projects_count
            from projects p
            left join studies pr on pr.project_id = p.id
            where (:q is null or p.name ilike '%' || :q || '%')
            group by p.id
            order by p.created_at desc
        """),
        {"q": q},
    ).mappings().all()
    return [
        {"id": str(r["id"]), "name": r["name"], "projects_count": r["projects_count"], "created_at": r["created_at"]}
        for r in rows
    ]


@router.get("/{project_id}")
def get_proyecto(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    proyecto = db.execute(
        text("select id, name, created_at from projects where id = :id"),
        {"id": project_id},
    ).mappings().first()
    if not proyecto:
        raise HTTPException(404, "Proyecto no encontrado")
    return {"id": str(proyecto["id"]), "name": proyecto["name"], "created_at": proyecto["created_at"]}


@router.get("/{project_id}/projects")
def list_proyecto_projects(
    project_id: uuid.UUID,
    q: str | None = None,
    analytic_target: str | None = None,
    assigned_user_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Los Estudios (`projects`) que cuelgan de este Proyecto, con objetivo
    analítico (brands, reasons, both) y resumen de rondas. Filtros: q (nombre),
    analytic_target, assigned_user_id."""
    require_admin(db, user["id"])
    having_clause = ""
    params: dict = {"id": project_id, "q": q, "assigned_user": assigned_user_id}
    if analytic_target:
        if analytic_target == "both":
            having_clause = "having count(distinct sp.coding_type) = 2"
            params["at"] = ""
        elif analytic_target in ("brands", "reasons"):
            having_clause = "having max(sp.coding_type) = :at and count(distinct sp.coding_type) = 1"
            params["at"] = analytic_target
        elif analytic_target == "none":
            having_clause = "having count(sp.id) = 0"
    rows = db.execute(
        text(f"""
            select p.id, p.external_code, p.name, p.created_at,
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
              and (:q is null or (p.name ilike '%' || :q || '%' or p.external_code ilike '%' || :q || '%'))
              and (:assigned_user is null or exists (
                    select 1 from assignments a
                    where a.study_id = p.id and a.user_id = :assigned_user
                    and a.status = 'active' and a.revoked_at is null))
            group by p.id
            {having_clause}
            order by p.created_at desc
        """),
        params,
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "external_code": r["external_code"],
            "name": r["name"],
            "created_at": r["created_at"],
            "rounds_count": r["rounds_count"],
            "analytic_target": r["analytic_target"],
        }
        for r in rows
    ]


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

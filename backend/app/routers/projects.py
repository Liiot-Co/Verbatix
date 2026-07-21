import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.access import require_capability, require_project, visible_project_ids
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.repositories import round_setup_incomplete

router = APIRouter(prefix="/api/v1", tags=["projects"])


class ProjectIn(BaseModel):
    external_code: str | None = None
    name: str
    proyecto_id: uuid.UUID | None = None


@router.post("/projects", status_code=201)
def create_project(
    payload: ProjectIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_capability(db, user["id"], "projects.manage")
    pid = uuid.uuid4()
    try:
        db.execute(
            text("""
                insert into studios (id, external_code, name, proyecto_id, created_by)
                values (:id, :code, :name, :proyecto, :u)
            """),
            {
                "id": pid,
                "code": payload.external_code,
                "name": payload.name,
                "proyecto": payload.proyecto_id,
                "u": user["id"],
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409, f"Ya existe un proyecto con el código '{payload.external_code}'"
        ) from exc
    return {
        "id": str(pid),
        "external_code": payload.external_code,
        "name": payload.name,
        "proyecto_id": str(payload.proyecto_id) if payload.proyecto_id else None,
    }


@router.get("/projects")
def list_projects(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Admin ve todos los Estudios; codificador/supervisor solo los que tienen
    asignados vía `assignments` (sección 2.1 del documento v8)."""
    project_ids = visible_project_ids(db, user["id"])
    rows = db.execute(
        text("""
            select p.id, p.external_code, p.name, p.created_at,
                   count(distinct r.id) as rounds_count,
                   (select count(*) from assignments a
                    where a.project_id = p.id and a.status = 'active' and a.revoked_at is null)
                     as assigned_users_count,
                   coalesce((
                     select jsonb_agg(jsonb_build_object(
                       'id', preview.id, 'name', preview.name, 'email', preview.email,
                       'initials', preview.initials, 'roles', preview.roles
                     )) from (
                       select u.id, u.name, u.email,
                              upper(left(coalesce(nullif(u.name, ''), u.email), 1)) initials,
                              array(select role_code from user_roles where user_id = u.id order by role_code) roles
                       from assignments a join users u on u.id = a.user_id
                       where a.project_id = p.id and a.status = 'active' and a.revoked_at is null
                       order by coalesce(u.name, u.email) limit 3
                     ) preview
                   ), '[]'::jsonb) assigned_users_preview
            from studios p
            left join rounds r on r.project_id = p.id
            where :ids is null or p.id = any(:ids)
            group by p.id
            order by p.created_at desc
        """),
        {"ids": project_ids},
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "external_code": r["external_code"],
            "name": r["name"],
            "studies_count": 1,
            "rounds_count": r["rounds_count"],
            "created_at": r["created_at"],
            "assigned_users_count": r["assigned_users_count"],
            "assigned_users_preview": r["assigned_users_preview"],
        }
        for r in rows
    ]


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_capability(db, user["id"], "projects.manage")
    # El proyecto posee tanto questions como rounds; verbatims referencia a
    # ambos árboles. Borrar las rondas primero elimina verbatims por cascade y
    # evita que PostgreSQL intente borrar questions aún referenciadas.
    db.execute(text("delete from rounds where project_id = :id"), {"id": project_id})
    deleted = db.execute(
        text("delete from studios where id = :id returning id"),
        {"id": project_id},
    ).scalar()
    if not deleted:
        raise HTTPException(404, "Proyecto no encontrado")
    db.commit()


@router.get("/projects/{project_id}")
def get_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_project(db, project_id, user["id"])
    project = db.execute(
        text("select id, external_code, name, proyecto_id, created_at from studios where id = :id"),
        {"id": project_id},
    ).mappings().first()

    categories = db.execute(
        text("select id, name from categories where project_id = :id order by name"),
        {"id": project_id},
    ).mappings().all()

    rounds = db.execute(
        text("""
            select r.id, r.category_id, r.name, r.round_number, r.status,
                   sp.id as subproject_id, sp.coding_type,
                   (select count(*) from verbatims v where v.subproject_id = sp.id) as verbatims_total,
                   (select count(*) from verbatims v where v.subproject_id = sp.id and v.coding_status = 'auto_coded') as auto_coded
            from rounds r
            left join subprojects sp on sp.round_id = r.id
            where r.project_id = :id
            order by r.round_number, sp.coding_type
        """),
        {"id": project_id},
    ).mappings().all()

    rounds_by_id: dict[str, dict] = {}
    for r in rounds:
        rid = str(r["id"])
        if rid not in rounds_by_id:
            rounds_by_id[rid] = {
                "id": rid,
                "category_id": str(r["category_id"]) if r["category_id"] else None,
                "name": r["name"],
                "round_number": r["round_number"],
                "status": r["status"],
                "subprojects": [],
            }
        if r["subproject_id"]:
            rounds_by_id[rid]["subprojects"].append({
                "id": str(r["subproject_id"]),
                "coding_type": r["coding_type"],
                "verbatims_total": r["verbatims_total"],
                "auto_coded": r["auto_coded"],
            })

    # round-sequence-and-homologation (Task 7): calculado con el mismo
    # criterio centralizado que bloquea el motor (round_setup_incomplete),
    # para que el frontend pinte el chip sin llamadas extra por ronda.
    for rid, round_data in rounds_by_id.items():
        round_data["setup_incomplete"] = round_setup_incomplete(db, uuid.UUID(rid))

    return {
        "id": str(project["id"]),
        "external_code": project["external_code"],
        "name": project["name"],
        "proyecto_id": str(project["proyecto_id"]) if project["proyecto_id"] else None,
        "created_at": project["created_at"],
        "categories": [{"id": str(c["id"]), "name": c["name"]} for c in categories],
        "rounds": list(rounds_by_id.values()),
    }

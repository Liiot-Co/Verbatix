import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.access import require_capability, require_project, visible_study_ids
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.repositories import round_setup_incomplete

router = APIRouter(prefix="/api/v1", tags=["projects"])


class ProjectIn(BaseModel):
    external_code: str | None = None
    name: str
    project_id: uuid.UUID | None = None


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
                insert into studies (id, external_code, name, project_id, created_by)
                values (:id, :code, :name, :project, :u)
            """),
            {
                "id": pid,
                "code": payload.external_code,
                "name": payload.name,
                "project": payload.project_id,
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
        "project_id": str(payload.project_id) if payload.project_id else None,
    }


@router.get("/projects")
def list_projects(
    q: str | None = None,
    analytic_target: str | None = None,
    project_id: uuid.UUID | None = None,
    assigned_user_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Admin ve todos los Estudios; codificador/supervisor solo los que tienen
    asignados vía `assignments`. Filtros: q (nombre/código), analytic_target,
    project_id, assigned_user_id."""
    study_ids = visible_study_ids(db, user["id"])
    having_clause = ""
    params: dict = {"ids": study_ids, "q": q, "project": project_id, "assigned_user": assigned_user_id}
    if analytic_target:
        if analytic_target == "both":
            having_clause = "having count(distinct sp.coding_type) = 2"
        elif analytic_target in ("brands", "reasons"):
            having_clause = "having max(sp.coding_type) = :at and count(distinct sp.coding_type) = 1"
            params["at"] = analytic_target
        elif analytic_target == "none":
            having_clause = "having count(sp.id) = 0"
    rows = db.execute(
        text(f"""
            select p.id, p.external_code, p.name, p.created_at, p.project_id,
                   count(distinct r.id) as rounds_count,
                   coalesce(
                     case
                       when count(distinct sp.coding_type) = 2 then 'both'
                       when max(sp.coding_type) = 'brands' then 'brands'
                       when max(sp.coding_type) = 'reasons' then 'reasons'
                     end,
                     'none'
                   ) as analytic_target,
                   (select count(*) from assignments a
                    where a.study_id = p.id and a.status = 'active' and a.revoked_at is null)
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
                       where a.study_id = p.id and a.status = 'active' and a.revoked_at is null
                       order by coalesce(u.name, u.email) limit 3
                     ) preview
                   ), '[]'::jsonb) assigned_users_preview
            from studies p
            left join rounds r on r.study_id = p.id
            left join subprojects sp on sp.round_id = r.id
            where (:ids is null or p.id = any(:ids))
              and (:q is null or (p.name ilike '%' || :q || '%' or p.external_code ilike '%' || :q || '%'))
              and (:project is null or p.project_id = :project)
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
            "studies_count": 1,
            "rounds_count": r["rounds_count"],
            "analytic_target": r.get("analytic_target", "none"),
            "created_at": r["created_at"],
            "project_id": str(r["project_id"]) if r.get("project_id") else None,
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
    db.execute(text("delete from rounds where study_id = :id"), {"id": project_id})
    deleted = db.execute(
        text("delete from studies where id = :id returning id"),
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
        text("""
            select p.id, p.external_code, p.name, p.project_id, p.created_at, proj.name as project_name
            from studies p
            left join projects proj on proj.id = p.project_id
            where p.id = :id
        """),
        {"id": project_id},
    ).mappings().first()

    categories = db.execute(
        text("select id, name from categories where study_id = :id order by name"),
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
            where r.study_id = :id
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

    for rid, round_data in rounds_by_id.items():
        round_data["setup_incomplete"] = round_setup_incomplete(db, uuid.UUID(rid))

    return {
        "kind": "studio",
        "id": str(project["id"]),
        "external_code": project["external_code"],
        "name": project["name"],
        "project_id": str(project["project_id"]) if project["project_id"] else None,
        "project_name": project["project_name"],
        "created_at": project["created_at"],
        "categories": [{"id": str(c["id"]), "name": c["name"]} for c in categories],
        "rounds": list(rounds_by_id.values()),
    }

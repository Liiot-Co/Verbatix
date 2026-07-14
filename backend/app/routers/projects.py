import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import require_project
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db

router = APIRouter(prefix="/api/v1", tags=["projects"])


class ProjectIn(BaseModel):
    external_code: str | None = None
    name: str


@router.post("/projects", status_code=201)
def create_project(
    payload: ProjectIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    pid = uuid.uuid4()
    db.execute(
        text("""
            insert into projects (id, external_code, name, created_by)
            values (:id, :code, :name, :u)
        """),
        {
            "id": pid,
            "code": payload.external_code,
            "name": payload.name,
            "u": user["id"],
        },
    )
    db.commit()
    return {
        "id": str(pid),
        "external_code": payload.external_code,
        "name": payload.name,
    }


@router.get("/projects")
def list_projects(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    rows = db.execute(
        text("""
            select p.id, p.external_code, p.name, p.created_at,
                   count(distinct s.id) as studies_count,
                   count(distinct r.id) as rounds_count
            from projects p
            left join studio s on s.project_id = p.id
            left join rounds r on r.studio_id = s.id
            where p.created_by = :u
            group by p.id
            order by p.created_at desc
        """),
        {"u": user["id"]},
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "external_code": r["external_code"],
            "name": r["name"],
            "studies_count": r["studies_count"],
            "rounds_count": r["rounds_count"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    deleted = db.execute(
        text("delete from projects where id = :id and created_by = :u returning id"),
        {"id": project_id, "u": user["id"]},
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
        text("select id, external_code, name, created_at from projects where id = :id"),
        {"id": project_id},
    ).mappings().first()

    studies = db.execute(
        text("""
            select id, name, coding_type, survey_question
            from studio where project_id = :id
            order by created_at
        """),
        {"id": project_id},
    ).mappings().all()

    rounds = db.execute(
        text("""
            select r.id, r.studio_id, r.name, r.round_number, r.status,
                   (select count(*) from verbatims v where v.round_id = r.id) as verbatims_total,
                   (select count(*) from verbatims v where v.round_id = r.id and v.coding_status = 'auto_coded') as auto_coded
            from rounds r
            join studio s on s.id = r.studio_id
            where s.project_id = :id
            order by r.round_number
        """),
        {"id": project_id},
    ).mappings().all()
    rounds_by_study: dict[str, list[dict]] = {}
    for r in rounds:
        rounds_by_study.setdefault(str(r["studio_id"]), []).append({
            "id": str(r["id"]),
            "name": r["name"],
            "round_number": r["round_number"],
            "status": r["status"],
            "verbatims_total": r["verbatims_total"],
            "auto_coded": r["auto_coded"],
        })

    return {
        "id": str(project["id"]),
        "external_code": project["external_code"],
        "name": project["name"],
        "created_at": project["created_at"],
        "studies": [
            {
                "id": str(s["id"]),
                "name": s["name"],
                "coding_type": s["coding_type"],
                "survey_question": s["survey_question"],
                "rounds": rounds_by_study.get(str(s["id"]), []),
            }
            for s in studies
        ],
    }

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
                   count(r.id) as rounds_count
            from projects p
            left join rounds r on r.project_id = p.id
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

    rounds = db.execute(
        text("""
            select id, name, round_number, status
            from rounds where project_id = :id
            order by round_number
        """),
        {"id": project_id},
    ).mappings().all()

    studios = db.execute(
        text("""
            select s.id, s.round_id, s.name, s.coding_type, s.status,
                   (select count(*) from verbatims v where v.studio_id = s.id) as verbatims_total,
                   (select count(*) from verbatims v where v.studio_id = s.id and v.coding_status = 'auto_coded') as auto_coded
            from studio s
            join rounds r on r.id = s.round_id
            where r.project_id = :id
        """),
        {"id": project_id},
    ).mappings().all()
    studios_by_round: dict[str, list[dict]] = {}
    for s in studios:
        studios_by_round.setdefault(str(s["round_id"]), []).append({
            "id": str(s["id"]),
            "name": s["name"],
            "coding_type": s["coding_type"],
            "status": s["status"],
            "verbatims_total": s["verbatims_total"],
            "auto_coded": s["auto_coded"],
        })

    return {
        "id": str(project["id"]),
        "external_code": project["external_code"],
        "name": project["name"],
        "created_at": project["created_at"],
        "rounds": [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "round_number": r["round_number"],
                "status": r["status"],
                "studios": studios_by_round.get(str(r["id"]), []),
            }
            for r in rounds
        ],
    }

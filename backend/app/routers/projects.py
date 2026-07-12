import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, current_user
from app.core.database import get_db

router = APIRouter(prefix="/api/v1", tags=["projects"])


class ProjectIn(BaseModel):
    external_code: str | None = None
    name: str
    client_name: str | None = None


@router.post("/projects", status_code=201)
def create_project(
    payload: ProjectIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    pid = uuid.uuid4()
    db.execute(
        text("""
            insert into projects (id, external_code, name, client_name, created_by)
            values (:id, :code, :name, :client, :u)
        """),
        {
            "id": pid,
            "code": payload.external_code,
            "name": payload.name,
            "client": payload.client_name,
            "u": user["id"],
        },
    )
    db.commit()
    return {
        "id": str(pid),
        "external_code": payload.external_code,
        "name": payload.name,
        "client_name": payload.client_name,
    }


@router.get("/projects")
def list_projects(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    rows = db.execute(
        text("""
            select id, external_code, name, client_name, created_at
            from projects
            order by created_at desc
        """)
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "external_code": r["external_code"],
            "name": r["name"],
            "client_name": r["client_name"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]

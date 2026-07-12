import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, Study
from app.seed import DEMO_USER_ID
from app.serializers import study_summary

router = APIRouter(prefix="/api/v1", tags=["projects"])


class ProjectCreate(BaseModel):
    external_code: str
    name: str
    client_name: str | None = None


def _project_dashboard_item(db: Session, project: Project) -> dict:
    studies = db.query(Study).filter_by(project_id=project.id).order_by(Study.created_at.desc()).all()
    return {
        "id": str(project.id),
        "external_code": project.external_code,
        "name": project.name,
        "client_name": project.client_name,
        "studies_count": len(studies),
        "last_study": study_summary(db, studies[0]) if studies else None,
        "updated_at": project.created_at.isoformat() + "Z",
    }


def _project_detail(db: Session, project: Project) -> dict:
    studies = db.query(Study).filter_by(project_id=project.id).order_by(Study.created_at.desc()).all()
    return {
        "id": str(project.id),
        "external_code": project.external_code,
        "name": project.name,
        "client_name": project.client_name,
        "studies_count": len(studies),
        "studies": [study_summary(db, s) for s in studies],
        "created_at": project.created_at.isoformat() + "Z",
    }


@router.get("/projects")
def list_projects(page: int = 1, page_size: int = 50, db: Session = Depends(get_db)):
    query = db.query(Project).order_by(Project.created_at.desc())
    total = query.count()
    projects = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [_project_dashboard_item(db, p) for p in projects],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    existing = db.query(Project).filter_by(external_code=body.external_code).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"code": "CONFLICT", "message": "Ya existe un proyecto con ese external_code", "details": {}},
        )

    project = Project(
        external_code=body.external_code,
        name=body.name,
        client_name=body.client_name,
        created_by=DEMO_USER_ID,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return {
        "id": str(project.id),
        "external_code": project.external_code,
        "name": project.name,
        "client_name": project.client_name,
        "created_at": project.created_at.isoformat() + "Z",
    }


@router.get("/projects/{project_id}")
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": "Proyecto no encontrado", "details": {}}
        )
    return _project_detail(db, project)

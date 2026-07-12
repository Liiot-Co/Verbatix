import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, Study
from app.seed import DEMO_USER_ID

router = APIRouter(prefix="/api/v1", tags=["studies"])


class StudyCreate(BaseModel):
    name: str
    coding_type: str
    survey_question: str | None = None


@router.post("/projects/{project_id}/studies", status_code=201)
def create_study(project_id: uuid.UUID, body: StudyCreate, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": "Proyecto no encontrado", "details": {}}
        )

    study = Study(
        project_id=project_id,
        name=body.name,
        coding_type=body.coding_type,
        survey_question=body.survey_question,
        created_by=DEMO_USER_ID,
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    return {
        "id": str(study.id),
        "project_id": str(study.project_id),
        "name": study.name,
        "coding_type": study.coding_type,
        "survey_question": study.survey_question,
        "rounds": [],
    }

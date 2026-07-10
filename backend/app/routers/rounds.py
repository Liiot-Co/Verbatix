from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Round, SurveyResponse
from app.routers.resolve import _to_item

router = APIRouter(prefix="/api", tags=["rounds"])


class RoundCreate(BaseModel):
    name: str
    study_id: int | None = None


class RoundResponse(BaseModel):
    id: int
    name: str
    study_id: int | None = None
    total: int = 0
    auto_approved: int = 0
    requires_human: int = 0
    generic: int = 0


@router.post("/rounds", response_model=RoundResponse)
def create_round(body: RoundCreate, db: Session = Depends(get_db)):
    existing = db.query(Round).filter_by(name=body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Round name already exists")

    rnd = Round(name=body.name, study_id=body.study_id)
    db.add(rnd)
    db.commit()
    db.refresh(rnd)
    return RoundResponse(id=rnd.id, name=rnd.name, study_id=rnd.study_id)


@router.get("/rounds", response_model=list[RoundResponse])
def list_rounds(db: Session = Depends(get_db)):
    rounds = db.query(Round).order_by(Round.created_at.desc()).all()
    result = []
    for rnd in rounds:
        counts = (
            db.query(
                func.count(SurveyResponse.id).label("total"),
                func.count(SurveyResponse.id).filter(
                    SurveyResponse.status == "auto_approved"
                ).label("auto_approved"),
                func.count(SurveyResponse.id).filter(
                    SurveyResponse.status == "requires_human"
                ).label("requires_human"),
                func.count(SurveyResponse.id).filter(
                    SurveyResponse.status == "generic"
                ).label("generic"),
            )
            .filter(SurveyResponse.round_id == rnd.id)
            .one()
        )
        result.append(RoundResponse(
            id=rnd.id,
            name=rnd.name,
            study_id=rnd.study_id,
            total=counts.total,
            auto_approved=counts.auto_approved,
            requires_human=counts.requires_human,
            generic=counts.generic,
        ))
    return result


@router.get("/rounds/{round_id}/responses")
def get_round_responses(round_id: int, status: str | None = None, db: Session = Depends(get_db)):
    if not db.get(Round, round_id):
        raise HTTPException(status_code=404, detail="Round not found")

    query = db.query(SurveyResponse).filter(SurveyResponse.round_id == round_id)
    if status:
        query = query.filter(SurveyResponse.status == status)
    items = query.order_by(SurveyResponse.id).all()
    return [_to_item(r, db) for r in items]


@router.delete("/rounds/{round_id}")
def delete_round(round_id: int, db: Session = Depends(get_db)):
    rnd = db.get(Round, round_id)
    if not rnd:
        raise HTTPException(status_code=404, detail="Round not found")
    db.delete(rnd)
    db.commit()
    return {"status": "ok"}

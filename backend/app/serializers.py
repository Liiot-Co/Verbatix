from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Round, Study, Verbatim


def round_progress(db: Session, rnd: Round) -> dict:
    total, coded = (
        db.query(
            func.count(Verbatim.id),
            func.count(Verbatim.id).filter(Verbatim.coding_status != "pending"),
        )
        .filter(Verbatim.round_id == rnd.id)
        .one()
    )
    return {"coded": coded, "total": total, "audit_reviewed": 0, "audit_total": 0}


def round_summary(db: Session, rnd: Round) -> dict:
    return {
        "id": str(rnd.id),
        "name": rnd.name,
        "round_number": rnd.round_number,
        "status": rnd.status,
        "progress": round_progress(db, rnd),
    }


def study_summary(db: Session, study: Study) -> dict:
    rounds = db.query(Round).filter_by(study_id=study.id).order_by(Round.round_number).all()
    return {
        "id": str(study.id),
        "name": study.name,
        "coding_type": study.coding_type,
        "rounds": [round_summary(db, r) for r in rounds],
    }

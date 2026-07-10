from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OfficialBrand, SurveyResponse

router = APIRouter(prefix="/api", tags=["metrics"])


def _compute(items: list, db: Session) -> dict:
    total   = len(items)
    auto    = sum(1 for i in items if i.status == "auto_approved")
    human   = sum(1 for i in items if i.status == "requires_human")
    generic = sum(1 for i in items if i.status == "generic")
    manual  = sum(1 for i in items if i.status == "manual_resolved")

    brand_ids = [i.official_brand_id for i in items if i.official_brand_id]
    brand_map: dict[int, str] = {}
    if brand_ids:
        rows = db.query(OfficialBrand.id, OfficialBrand.name).filter(
            OfficialBrand.id.in_(brand_ids)
        ).all()
        brand_map = {r.id: r.name for r in rows}

    counts: dict[str, int] = {}
    for i in items:
        if i.official_brand_id and i.official_brand_id in brand_map:
            name = brand_map[i.official_brand_id]
            counts[name] = counts.get(name, 0) + 1

    top = sorted(counts.items(), key=lambda x: -x[1])
    return {
        "total": total,
        "auto_approved": auto,
        "requires_human": human,
        "generic": generic,
        "manual_resolved": manual,
        "top_brands": [{"brand": b, "count": c} for b, c in top],
    }


@router.get("/metrics/{round_id}")
def get_metrics_by_round(round_id: int, db: Session = Depends(get_db)):
    items = db.query(SurveyResponse).filter(
        SurveyResponse.round_id == round_id
    ).all()
    return _compute(items, db)


@router.get("/metrics")
def get_metrics_all(db: Session = Depends(get_db)):
    items = db.query(SurveyResponse).all()
    return _compute(items, db)

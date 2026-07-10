from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import OfficialBrand, BrandVariation, SurveyResponse
from app.services.pipeline import classify_text

router = APIRouter(prefix="/api", tags=["classify"])


class Decision(BaseModel):
    item_id: int
    action: str
    resolved_brand: Optional[str] = None


class ClassifyRequest(BaseModel):
    decisions: list[Decision]


@router.post("/classify")
def classify_decisions(payload: ClassifyRequest, db: Session = Depends(get_db)):
    for dec in payload.decisions:
        resp = db.query(SurveyResponse).get(dec.item_id)
        if not resp:
            continue

        if dec.action in ("approve", "edit") and dec.resolved_brand:
            brand = db.query(OfficialBrand).filter_by(name=dec.resolved_brand).first()
            if not brand:
                brand = OfficialBrand(name=dec.resolved_brand)
                db.add(brand)
                db.flush()

            if resp.extracted_term:
                existing_var = (
                    db.query(BrandVariation)
                    .filter_by(variation_text=resp.extracted_term.lower())
                    .first()
                )
                if not existing_var:
                    db.add(BrandVariation(
                        variation_text=resp.extracted_term.lower(),
                        official_brand_id=brand.id,
                    ))

            resp.status = "auto_approved"
            resp.official_brand_id = brand.id

        elif dec.action == "reject":
            resp.status = "rejected"

    db.commit()

    requires_human = (
        db.query(SurveyResponse)
        .filter_by(status="requires_human")
        .all()
    )

    for resp in requires_human:
        result = classify_text(resp.original_text, db)
        if result["status"] == "auto_approved" and result["confidence"] >= 0.85:
            resp.status = "auto_approved"
            resp.official_brand_id = result["official_brand_id"]
            resp.confidence = result["confidence"]

    db.commit()

    all_items = db.query(SurveyResponse).order_by(SurveyResponse.id).all()

    items = []
    for r in all_items:
        brand_name = None
        if r.official_brand_id:
            brand = db.query(OfficialBrand).get(r.official_brand_id)
            brand_name = brand.name if brand else None
        items.append({
            "id": r.id,
            "original_text": r.original_text,
            "extracted_term": r.extracted_term,
            "suggested_brand": brand_name,
            "official_brand_id": r.official_brand_id,
            "confidence": r.confidence,
            "status": r.status,
        })

    auto = sum(1 for i in items if i["status"] == "auto_approved")
    human = sum(1 for i in items if i["status"] == "requires_human")
    generic = sum(1 for i in items if i["status"] == "generic")
    manual = sum(1 for i in items if i["status"] == "manual_resolved")

    brand_counts: dict[str, int] = {}
    for i in items:
        if i["suggested_brand"]:
            brand_counts[i["suggested_brand"]] = brand_counts.get(i["suggested_brand"], 0) + 1
    top_brands = sorted(brand_counts.items(), key=lambda x: -x[1])

    return {
        "status": "ok",
        "items": items,
        "metrics": {
            "total": len(items),
            "auto_approved": auto,
            "requires_human": human,
            "generic": generic,
            "manual_resolved": manual,
            "top_brands": [{"brand": b, "count": c} for b, c in top_brands],
        },
    }

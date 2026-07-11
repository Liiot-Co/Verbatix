from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from rapidfuzz import fuzz

from app.database import get_db
from app.models import (
    BrandVariation,
    Code,
    OfficialBrand,
    ResponseCode,
    SurveyResponse,
)

router = APIRouter(prefix="/api", tags=["resolve"])


class ResolveRequest(BaseModel):
    response_id: int
    resolved_brand: str


class ResponseItem(BaseModel):
    id: int
    original_text: str
    extracted_term: str | None
    suggested_brand: str | None
    confidence: float
    status: str


@router.post("/resolve-anomaly")
def resolve_anomaly(body: ResolveRequest, db: Session = Depends(get_db)):
    resp = db.query(SurveyResponse).get(body.response_id)
    if not resp:
        raise HTTPException(status_code=404, detail="Response not found")

    brand = db.query(OfficialBrand).filter_by(name=body.resolved_brand).first()
    if not brand:
        brand = OfficialBrand(name=body.resolved_brand)
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

    resp.status = "manual_resolved"
    resp.official_brand_id = brand.id
    db.commit()

    cascade_resolved = []
    if resp.extracted_term:
        same_round = (
            db.query(SurveyResponse)
            .filter(
                SurveyResponse.round_id == resp.round_id,
                SurveyResponse.status == "requires_human",
                SurveyResponse.id != resp.id,
            )
            .all()
        )
        for candidate in same_round:
            score = fuzz.WRatio(resp.extracted_term, candidate.extracted_term or "")
            if score >= 85:
                candidate.status = "auto_approved"
                candidate.official_brand_id = brand.id
                candidate.confidence = round(score / 100.0, 3)
                cascade_resolved.append(candidate)

        db.commit()

    return {
        "resolved": _to_item(resp, db),
        "cascade_resolved": [_to_item(r, db) for r in cascade_resolved],
    }


def _to_item(resp: SurveyResponse, db: Session) -> dict:
    brand_name = None
    if resp.official_brand_id:
        brand = db.query(OfficialBrand).get(resp.official_brand_id)
        brand_name = brand.name if brand else None
    return {
        "id": resp.id,
        "original_text": resp.original_text,
        "extracted_term": resp.extracted_term,
        "suggested_brand": brand_name,
        "confidence": resp.confidence,
        "status": resp.status,
        "codes": [
            {"code_id": rc.code_id, "name": rc.code.name, "confidence": rc.confidence, "origin": rc.origin}
            for rc in resp.codes
        ],
    }


@router.post("/responses/{response_id}/reopen")
def reopen_response(response_id: int, db: Session = Depends(get_db)):
    """Undo a resolve/save — puts the item back in the pending queue.
    ponytail: doesn't revert cascade-resolved siblings or clear the brand/codes
    already set; the user just gets another pass at this item. Full undo of
    the cascade would need per-action snapshots, add if this bites someone.
    """
    resp = db.get(SurveyResponse, response_id)
    if not resp:
        raise HTTPException(status_code=404, detail="Response not found")
    resp.status = "requires_human"
    db.commit()
    db.refresh(resp)
    return _to_item(resp, db)


class SetCodesRequest(BaseModel):
    code_ids: list[int]


@router.put("/responses/{response_id}/codes")
def set_response_codes(response_id: int, body: SetCodesRequest, db: Session = Depends(get_db)):
    resp = db.get(SurveyResponse, response_id)
    if not resp:
        raise HTTPException(status_code=404, detail="Response not found")

    study_id = resp.round.study_id if resp.round else None
    if body.code_ids:
        found = db.query(Code).filter(Code.id.in_(body.code_ids), Code.study_id == study_id).all()
        if len(found) != len(set(body.code_ids)):
            raise HTTPException(status_code=400, detail="One or more code_ids do not exist in this study")

    db.query(ResponseCode).filter(ResponseCode.response_id == response_id).delete()
    for code_id in body.code_ids:
        db.add(ResponseCode(response_id=response_id, code_id=code_id, confidence=0.0, origin="manual"))

    if resp.status == "requires_human":
        resp.status = "manual_resolved"

    db.commit()
    db.refresh(resp)
    return _to_item(resp, db)

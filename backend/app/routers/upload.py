import tempfile
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ResponseCode, Round, SurveyResponse
from app.services.pipeline import classify_codes, classify_text

router = APIRouter(prefix="/api", tags=["upload"])


class UploadResponse(BaseModel):
    status: str
    round_id: int
    total: int
    auto_approved: int
    requires_human: int
    generic: int
    items: list[dict]


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    answer_column: str = Form(...),
    round_id: int = Form(...),
    db: Session = Depends(get_db),
):
    rnd = db.query(Round).get(round_id)
    if not rnd:
        raise HTTPException(status_code=404, detail="Round not found")

    suffix = Path(file.filename or "upload.xlsx").suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        file_content = await file.read()
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        df = pd.read_excel(tmp_path, engine="openpyxl")
        if answer_column not in df.columns:
            raise HTTPException(
                status_code=400,
                detail=f"Column '{answer_column}' not found",
            )

        items: list[dict] = []
        for row_index, row in df.iterrows():
            text = str(row[answer_column]).strip()
            if not text or text.lower() in ("nan", "none", ""):
                continue

            result = classify_text(text, db)

            sr = SurveyResponse(
                round_id=round_id,
                original_text=text,
                extracted_term=result["extracted_term"],
                confidence=result["confidence"],
                status=result["status"],
                official_brand_id=result["official_brand_id"],
                external_row_id=str(row_index),
            )
            db.add(sr)
            db.flush()

            code_matches = classify_codes(text, rnd.study_id, db)
            for m in code_matches:
                db.add(ResponseCode(
                    response_id=sr.id,
                    code_id=m["code_id"],
                    confidence=m["confidence"],
                    origin="auto",
                ))

            items.append({
                "id": sr.id,
                "original_text": sr.original_text,
                "extracted_term": sr.extracted_term,
                "suggested_brand": result["suggested_brand"],
                "official_brand_id": result["official_brand_id"],
                "confidence": sr.confidence,
                "status": sr.status,
                "codes": code_matches,
            })

        db.commit()

        auto = sum(1 for i in items if i["status"] == "auto_approved")
        human = sum(1 for i in items if i["status"] == "requires_human")
        generic = sum(1 for i in items if i["status"] == "generic")

        return UploadResponse(
            status="ok",
            round_id=round_id,
            total=len(items),
            auto_approved=auto,
            requires_human=human,
            generic=generic,
            items=items,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

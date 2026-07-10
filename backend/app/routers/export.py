import io

import openpyxl
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Round, SurveyResponse

router = APIRouter(prefix="/api", tags=["export"])

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/export/{round_id}")
def export_round(round_id: int, db: Session = Depends(get_db)):
    rnd = db.query(Round).get(round_id)
    if not rnd:
        raise HTTPException(status_code=404, detail="Round not found")

    rows = (
        db.query(SurveyResponse)
        .options(joinedload(SurveyResponse.brand))
        .filter(SurveyResponse.round_id == round_id)
        .order_by(SurveyResponse.id)
        .all()
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = rnd.name[:31]  # Excel sheet name limit
    ws.append(["original_text", "extracted_term", "official_brand", "confidence", "status"])

    for resp in rows:
        ws.append([
            resp.original_text,
            resp.extracted_term or "",
            resp.brand.name if resp.brand else "",
            resp.confidence,
            resp.status,
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    safe_name = rnd.name.replace(" ", "_").replace("/", "-")
    return StreamingResponse(
        buf,
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="clasificacion_{safe_name}.xlsx"'
        },
    )

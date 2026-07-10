import io
import re

import openpyxl
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Round, SurveyResponse

router = APIRouter(prefix="/api", tags=["export"])

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _sanitize_column(name: str) -> str:
    clean = re.sub(r"[^\w]+", "_", name.strip())
    return clean.strip("_") or "col"


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

    # Collect the study's unique codes/nets actually assigned in this round,
    # to build the dummy 0/1 matrix columns (SPSS-style).
    code_names: list[str] = []
    net_names: list[str] = []
    seen_codes: set[str] = set()
    seen_nets: set[str] = set()
    for resp in rows:
        for rc in resp.codes:
            if rc.code.name not in seen_codes:
                seen_codes.add(rc.code.name)
                code_names.append(rc.code.name)
            if rc.code.net and rc.code.net.name not in seen_nets:
                seen_nets.add(rc.code.net.name)
                net_names.append(rc.code.net.name)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = rnd.name[:31]  # Excel sheet name limit

    header = ["external_row_id", "original_text", "extracted_term", "official_brand", "confidence", "status"]
    header += [f"Codigo_{_sanitize_column(n)}" for n in code_names]
    header += [f"Neto_{_sanitize_column(n)}" for n in net_names]
    ws.append(header)

    for resp in rows:
        assigned_codes = {rc.code.name for rc in resp.codes}
        assigned_nets = {rc.code.net.name for rc in resp.codes if rc.code.net}
        row = [
            resp.external_row_id or "",
            resp.original_text,
            resp.extracted_term or "",
            resp.brand.name if resp.brand else "",
            resp.confidence,
            resp.status,
        ]
        row += [1 if n in assigned_codes else 0 for n in code_names]
        row += [1 if n in assigned_nets else 0 for n in net_names]
        ws.append(row)

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

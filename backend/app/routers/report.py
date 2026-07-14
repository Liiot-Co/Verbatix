import io
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import require_round
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.pipeline.export import build_export_zip
from app.repositories import get_round_export_data, get_round_report

router = APIRouter(prefix="/api/v1", tags=["report"])


@router.get("/rounds/{round_id}/report")
def round_report(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    return get_round_report(db, round_id)


@router.get("/rounds/{round_id}/report/export")
def export_codebook(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    nav = db.execute(
        text("""
            select p.external_code, r.round_number
            from rounds r
            join studio s on s.id = r.studio_id
            join projects p on p.id = s.project_id
            where r.id = :id
        """),
        {"id": round_id},
    ).mappings().first()

    export_data = get_round_export_data(db, round_id)
    if not export_data:
        raise HTTPException(404, "Ronda sin datos de exportación")

    zip_bytes = build_export_zip(export_data)

    ext = (nav["external_code"] if nav else None) or "STUDIO"
    round_num = nav["round_number"] if nav else 1
    filename = f"LC_{ext}_R{round_num}.zip"

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

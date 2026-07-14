import io
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import require_studio
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.pipeline.export import build_export_zip
from app.repositories import get_codebook_export_data, get_studio_report

router = APIRouter(prefix="/api/v1", tags=["report"])


@router.get("/studios/{studio_id}/report")
def studio_report(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_studio(db, studio_id, user["id"])
    return get_studio_report(db, studio_id)


@router.get("/studios/{studio_id}/report/export")
def export_codebook(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_studio(db, studio_id, user["id"])
    nav = db.execute(
        text("""
            select p.external_code, r.round_number
            from studio s
            join rounds r on r.id = s.round_id
            join projects p on p.id = r.project_id
            where s.id = :id
        """),
        {"id": studio_id},
    ).mappings().first()

    export_data = get_codebook_export_data(db, studio_id)
    if not export_data:
        raise HTTPException(404, "Estudio sin datos de exportación")

    zip_bytes = build_export_zip(export_data)

    ext = (nav["external_code"] if nav else None) or "STUDIO"
    round_num = nav["round_number"] if nav else 1
    filename = f"LC_{ext}_R{round_num}.zip"

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

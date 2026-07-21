import io
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import is_admin, require_capability, require_round
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.pipeline.export import build_export_zip
from app.pipeline.export.zip import VALID_FORMATS
from app.repositories import get_round_export_data, get_round_report, round_export_blockers

router = APIRouter(prefix="/api/v1", tags=["report"])

_DEFAULT_FORMATS = {"excel", "sql", "onenextcase"}  # mdd pending Task 11


def _parse_export_formats(formats: str | None) -> set[str]:
    """`formats=excel,sql` -> {"excel", "sql"}; None -> the backward-compatible
    default (all formats except mdd, still pending Task 11)."""
    if formats is None:
        return _DEFAULT_FORMATS
    selected = {f.strip() for f in formats.split(",") if f.strip()}
    unknown = selected - VALID_FORMATS
    if unknown:
        raise HTTPException(400, f"Formato(s) de exportación desconocido(s): {', '.join(sorted(unknown))}")
    return selected


def _require_final_for_member(db: Session, round_id: uuid.UUID, user_id) -> None:
    if is_admin(db, user_id):
        return
    pending = db.execute(text("""
        select 1 from subprojects sp where sp.round_id = :round_id
          and not exists (
            select 1 from audit_sessions ases
            where ases.subproject_id = sp.id and ases.status = 'approved'
          ) limit 1
    """), {"round_id": round_id}).scalar()
    if pending:
        raise HTTPException(403, "El reporte estará disponible al aprobar toda la auditoría")


@router.get("/rounds/{round_id}/report")
def round_report(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "reports.view")
    _require_final_for_member(db, round_id, user["id"])
    return get_round_report(db, round_id)


@router.get("/rounds/{round_id}/report/export")
def export_codebook(
    round_id: uuid.UUID,
    formats: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "reports.export")
    _require_final_for_member(db, round_id, user["id"])
    selected = _parse_export_formats(formats)

    blockers = round_export_blockers(db, round_id)
    if blockers:
        raise HTTPException(422, "Exportación bloqueada: " + "; ".join(blockers))

    nav = db.execute(
        text("""
            select p.external_code, r.round_number
            from rounds r
            join projects p on p.id = r.project_id
            where r.id = :id
        """),
        {"id": round_id},
    ).mappings().first()

    export_data = get_round_export_data(db, round_id)
    if not export_data:
        raise HTTPException(404, "Ronda sin datos de exportación")

    zip_bytes = build_export_zip(export_data, selected)

    ext = (nav["external_code"] if nav else None) or "STUDIO"
    round_num = nav["round_number"] if nav else 1
    filename = f"LC_{ext}_R{round_num}.zip"

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

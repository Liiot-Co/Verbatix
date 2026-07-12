import hashlib
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, current_user
from app.database import get_db
from app.repositories import build_mention_groups, insert_codebook_from_excel, insert_verbatims
from app.services import excel, storage

router = APIRouter(prefix="/api/v1", tags=["files"])


@router.post("/studios/{studio_id}/files", status_code=201)
async def upload_file(
    studio_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Paso 1: sube el Excel a Storage y detecta hojas. No importa aún."""
    exists = db.execute(
        text("select 1 from studio where id = :id"),
        {"id": studio_id},
    ).scalar()
    if not exists:
        raise HTTPException(404, "Estudio no encontrado")

    content = await file.read()
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Solo .xlsx o .xlsm")

    checksum = hashlib.sha256(content).hexdigest()
    dup = db.execute(
        text("""
            select id from imported_files
            where studio_id = :studio and checksum = :cs
        """),
        {"studio": studio_id, "cs": checksum},
    ).scalar()
    if dup:
        raise HTTPException(409, f"Este archivo ya fue subido (id: {dup})")

    file_id = uuid.uuid4()
    path = f"{studio_id}/{file_id}.xlsx"
    storage_path = storage.upload("uploads", path, content)
    sheets = excel.detect_sheets(content)

    db.execute(
        text("""
            insert into imported_files (id, studio_id, file_type, original_filename,
                                        storage_path, checksum, status, uploaded_by)
            values (:id, :studio, 'combined_xlsx', :fn, :sp, :cs, 'uploaded', :u)
        """),
        {
            "id": file_id,
            "studio": studio_id,
            "fn": file.filename,
            "sp": storage_path,
            "cs": checksum,
            "u": user["id"],
        },
    )
    db.commit()

    return {
        "file_id": str(file_id),
        "original_filename": file.filename,
        "detected_sheets": sheets,
        "status": "uploaded",
    }


class ImportIn(BaseModel):
    verbatims_sheet: str
    codebook_sheet: str | None = None


@router.post("/studios/{studio_id}/files/{file_id}/import")
def import_file(
    studio_id: uuid.UUID,
    file_id: uuid.UUID,
    payload: ImportIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Paso 2: importa verbatims (y opcionalmente LC) tras confirmar hojas."""
    row = db.execute(
        text("""
            select storage_path from imported_files
            where id = :id and studio_id = :studio
        """),
        {"id": file_id, "studio": studio_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Archivo no encontrado")

    bucket, path = row["storage_path"].split("/", 1)
    content = storage.download(bucket, path)

    cb_id = db.execute(
        text("select id from codebooks where studio_id = :studio order by version desc limit 1"),
        {"studio": studio_id},
    ).scalar()
    if not cb_id:
        raise HTTPException(500, "El estudio no tiene libro de códigos")

    imported = {"codes": 0, "aliases": 0, "nets": 0}
    if payload.codebook_sheet:
        parsed = excel.parse_codebook(content, payload.codebook_sheet)
        imported = insert_codebook_from_excel(db, cb_id, parsed)

    rows = excel.parse_verbatims(content, payload.verbatims_sheet)
    n_verbatims = insert_verbatims(db, studio_id, file_id, rows)
    n_groups = build_mention_groups(db, studio_id)

    db.execute(
        text("update imported_files set status = 'validated', total_rows = :n where id = :id"),
        {"n": n_verbatims, "id": file_id},
    )
    db.execute(
        text("update studio set status = 'files_uploaded' where id = :id"),
        {"id": studio_id},
    )
    db.commit()

    return {
        "imported": {"verbatims": n_verbatims, "mention_groups": n_groups, **imported},
        "studio_status": "files_uploaded",
    }

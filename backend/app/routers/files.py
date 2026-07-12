import hashlib
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, current_user
from app.database import get_db
from app.repositories import insert_codebook_from_excel
from app.services import excel, storage
from app.services.normalize_pipeline import (
    normalization_stats,
    preview_rows,
    rows_to_normalized_df,
    save_normalized_df,
)

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
    """Normaliza verbatims del Excel → DataFrame → Parquet en Storage. Sin insert en BD."""
    row = db.execute(
        text("""
            select storage_path from imported_files
            where id = :id and studio_id = :studio
        """),
        {"id": file_id, "studio": studio_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Archivo no encontrado")

    studio = db.execute(
        text("select coding_type from studio where id = :id"),
        {"id": studio_id},
    ).mappings().first()
    if not studio:
        raise HTTPException(404, "Estudio no encontrado")

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
    coding_type = studio["coding_type"]
    df = rows_to_normalized_df(rows, coding_type)
    stats = normalization_stats(df, source_rows=len(rows), coding_type=coding_type)
    parquet_path = save_normalized_df(studio_id, file_id, df)

    db.execute(
        text("update imported_files set status = 'validated', total_rows = :n where id = :id"),
        {"n": stats["parsed_rows"], "id": file_id},
    )
    db.execute(
        text("update studio set status = 'files_uploaded' where id = :id"),
        {"id": studio_id},
    )
    db.commit()

    return {
        "normalized_parquet": parquet_path,
        "coding_type": coding_type,
        "imported": {**stats, **imported},
        "preview": preview_rows(df),
        "studio_status": "files_uploaded",
    }

import hashlib
import uuid

<<<<<<< Updated upstream
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
=======
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
>>>>>>> Stashed changes
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

<<<<<<< Updated upstream
from app.auth import CurrentUser, current_user
from app.database import get_db
from app.repositories import build_mention_groups, insert_codebook_from_excel, insert_verbatims
from app.services import excel, storage
=======
from app.classification import classify_verbatims
from app.database import SessionLocal, get_db
from app.models import Code, CodeAlias, Codebook, ImportedFile, Round, Study, Verbatim
from app.seed import DEMO_USER_ID
from app.utils.text import normalize_text
>>>>>>> Stashed changes

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


<<<<<<< Updated upstream
class ImportIn(BaseModel):
    verbatims_sheet: str
    codebook_sheet: str | None = None
=======
def _classify_round_in_background(round_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        classify_verbatims(db, round_id)
    finally:
        db.close()


@router.post("/rounds/{round_id}/files/{file_id}/import")
def import_file(
    round_id: uuid.UUID,
    file_id: uuid.UUID,
    body: ImportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    round_ = _get_round(db, round_id)
    imported_file = db.query(ImportedFile).filter_by(id=file_id, round_id=round_id).first()
    if not imported_file:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": "Archivo no encontrado", "details": {}}
        )
    if imported_file.status != "uploaded":
        raise HTTPException(
            status_code=409,
            detail={"code": "CONFLICT", "message": "Este archivo ya fue importado", "details": {}},
        )

    sheets = pd.read_excel(imported_file.storage_path, sheet_name=None, engine="openpyxl")
    verbatims_df = sheets.get(body.verbatims_sheet)
    if verbatims_df is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "VALIDATION_ERROR",
                "message": f"La hoja '{body.verbatims_sheet}' no existe en el archivo",
                "details": {"sheet": body.verbatims_sheet},
            },
        )

    columns = [str(c) for c in verbatims_df.columns]
    verbatim_col = body.column_map.get("verbatim")
    respondent_col = body.column_map.get("respondent_id")
    question_col = body.column_map.get("question_key")
    input_code_col = body.column_map.get("input_code")

    verbatims_created = 0
    skipped_rows = 0
    for _, row in verbatims_df.iterrows():
        raw_text = row.get(verbatim_col) if verbatim_col else None
        if raw_text is None or pd.isna(raw_text) or not str(raw_text).strip():
            skipped_rows += 1
            continue
        text = str(raw_text).strip()

        db.add(Verbatim(
            round_id=round_id,
            respondent_external_id=str(row.get(respondent_col)).strip() if respondent_col else None,
            question_key=str(row.get(question_col)).strip() if question_col else None,
            original_text=text,
            normalized_text=normalize_text(text),
            input_code_number=_extract_input_code(row, input_code_col, columns),
            coding_status="pending",
            imported_file_id=imported_file.id,
        ))
        verbatims_created += 1

    codes_created = 0
    aliases_created = 0
    if body.codebook_sheet:
        codebook_df = sheets.get(body.codebook_sheet)
        if codebook_df is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "VALIDATION_ERROR",
                    "message": f"La hoja '{body.codebook_sheet}' no existe en el archivo",
                    "details": {"sheet": body.codebook_sheet},
                },
            )
        codebook = db.query(Codebook).filter_by(round_id=round_id).first()
        existing_numbers = {c.code_number for c in db.query(Code).filter_by(codebook_id=codebook.id).all()}

        for _, row in codebook_df.iterrows():
            code_number = _coerce_code_number(row.get("CÓDIGO"))
            label = row.get("MENCIÓN PRINCIPAL")
            if code_number is None or label is None or pd.isna(label):
                continue
            label = str(label).strip()
            if not label or label.upper().startswith("NETO") or code_number in existing_numbers:
                continue

            code = Code(
                codebook_id=codebook.id,
                code_number=code_number,
                label=label,
                origin="imported_xlsx",
                created_by=DEMO_USER_ID,
            )
            db.add(code)
            db.flush()
            existing_numbers.add(code_number)
            codes_created += 1

            content = row.get("CONTENIDO")
            if content is not None and not pd.isna(content) and str(content).strip():
                occurrences = _coerce_code_number(row.get("FRECUENCIA")) or 1
                db.add(CodeAlias(
                    codebook_id=codebook.id,
                    code_id=code.id,
                    alias_normalized=normalize_text(str(content)),
                    alias_sample=str(content).strip(),
                    occurrences=occurrences,
                    origin="imported_xlsx",
                ))
                aliases_created += 1

    imported_file.status = "validated"
    round_.status = "files_uploaded"
    db.commit()

    study = db.query(Study).join(Round, Round.study_id == Study.id).filter(Round.id == round_id).first()
    if study.coding_type == "reasons":
        background_tasks.add_task(_classify_round_in_background, round_id)

    warnings = []
    if skipped_rows:
        warnings.append(f"{skipped_rows} filas sin texto de verbatim fueron omitidas")

    return {
        "imported": {
            "verbatims": verbatims_created,
            "codes": codes_created,
            "aliases": aliases_created,
            "skipped_rows": skipped_rows,
        },
        "warnings": warnings,
        "round_status": round_.status,
    }
>>>>>>> Stashed changes


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

import hashlib
import uuid
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Code, CodeAlias, Codebook, ImportedFile, Round, Verbatim
from app.seed import DEMO_USER_ID
from app.utils.text import normalize_text

router = APIRouter(prefix="/api/v1", tags=["files"])

UPLOAD_DIR = Path("data/uploads")

VERBATIM_HINT_COLS = {"respondent id", "verbatim", "question id", "study id"}
CODEBOOK_HINT_COLS = {"código", "codigo", "mención principal", "mencion principal", "contenido", "frecuencia"}


def _guess_sheet_type(columns: list[str]) -> str:
    lowered = {str(c).strip().lower() for c in columns}
    if len(lowered & CODEBOOK_HINT_COLS) >= 2:
        return "codebook"
    if lowered & VERBATIM_HINT_COLS:
        return "verbatims"
    return "unknown"


def _coerce_code_number(value) -> int | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return int(f)


def _extract_input_code(row, input_code_col: str | None, columns: list[str]) -> int | None:
    if not input_code_col:
        return None
    code = _coerce_code_number(row.get(input_code_col))
    if code is not None:
        return code
    # ponytail: known quirk — system codes 95-99 sometimes land one column over
    # in real client files. Only a one-column fallback, not a general realigner.
    if input_code_col in columns:
        idx = columns.index(input_code_col)
        if idx + 1 < len(columns):
            return _coerce_code_number(row.get(columns[idx + 1]))
    return None


class ImportRequest(BaseModel):
    verbatims_sheet: str
    codebook_sheet: str | None = None
    column_map: dict[str, str]


def _get_round(db: Session, round_id: uuid.UUID) -> Round:
    round_ = db.get(Round, round_id)
    if not round_:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": "Ronda no encontrada", "details": {}}
        )
    return round_


@router.post("/rounds/{round_id}/files", status_code=201)
async def upload_file(round_id: uuid.UUID, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _get_round(db, round_id)

    content = await file.read()
    checksum = hashlib.sha256(content).hexdigest()

    existing = db.query(ImportedFile).filter_by(round_id=round_id, checksum=checksum).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"code": "CONFLICT", "message": "Este archivo ya fue subido para esta ronda", "details": {}},
        )

    dest_dir = UPLOAD_DIR / str(round_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4()
    dest_path = dest_dir / f"{file_id}_{file.filename}"
    dest_path.write_bytes(content)

    try:
        sheets = pd.read_excel(dest_path, sheet_name=None, engine="openpyxl")
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "VALIDATION_ERROR", "message": f"No se pudo leer el Excel: {exc}", "details": {}},
        )

    detected_sheets = []
    total_rows = 0
    guessed_types: set[str] = set()
    for sheet_name, df in sheets.items():
        columns = [str(c) for c in df.columns]
        guessed_as = _guess_sheet_type(columns)
        guessed_types.add(guessed_as)
        total_rows += len(df)
        detected_sheets.append({
            "name": sheet_name,
            "rows": len(df),
            "guessed_as": guessed_as,
            "columns": columns,
        })

    if guessed_types == {"verbatims"}:
        file_type = "verbatims_xlsx"
    elif guessed_types == {"codebook"}:
        file_type = "codebook_xlsx"
    elif "verbatims" in guessed_types and "codebook" in guessed_types:
        file_type = "combined_xlsx"
    else:
        file_type = "unknown"

    imported_file = ImportedFile(
        id=file_id,
        round_id=round_id,
        file_type=file_type,
        original_filename=file.filename or "upload.xlsx",
        storage_path=str(dest_path),
        checksum=checksum,
        total_rows=total_rows,
        status="uploaded",
        uploaded_by=DEMO_USER_ID,
    )
    db.add(imported_file)
    db.commit()

    return {
        "file_id": str(file_id),
        "original_filename": imported_file.original_filename,
        "total_rows": total_rows,
        "detected_sheets": detected_sheets,
        "status": "uploaded",
    }


@router.post("/rounds/{round_id}/files/{file_id}/import")
def import_file(round_id: uuid.UUID, file_id: uuid.UUID, body: ImportRequest, db: Session = Depends(get_db)):
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


@router.get("/rounds/{round_id}/verbatims")
def list_verbatims(
    round_id: uuid.UUID,
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    _get_round(db, round_id)

    query = db.query(Verbatim).filter_by(round_id=round_id)
    if status:
        query = query.filter(Verbatim.coding_status == status)
    total = query.count()
    items = query.order_by(Verbatim.created_at).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "items": [
            {
                "id": str(v.id),
                "respondent_external_id": v.respondent_external_id,
                "question_key": v.question_key,
                "original_text": v.original_text,
                "coding_status": v.coding_status,
                "codes": [],
            }
            for v in items
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }

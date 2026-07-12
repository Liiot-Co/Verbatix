import hashlib
import re
import tempfile
import unicodedata
import uuid
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Studio, ImportedFile, Verbatim, MentionGroup

router = APIRouter(prefix="/api", tags=["upload"])


class UploadSummary(BaseModel):
    status: str
    imported_file_id: str
    studio_id: str
    total_rows: int
    unique_mentions: int
    file_name: str


def clean_text(text: str) -> str:
    """Normaliza el texto: minúsculas, remueve tildes, puntuación y espacios extras."""
    if not text or pd.isna(text):
        return ""
    text = str(text).lower().strip()
    # Remover tildes
    nfkd_form = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in nfkd_form if not unicodedata.combining(c))
    # Cambiar puntuación por espacios
    text = re.sub(r"[^\w\s]", " ", text)
    # Colapsar espacios múltiples
    return re.sub(r"\s+", " ", text).strip()


@router.post("/upload", response_model=UploadSummary)
async def upload_file(
    file: UploadFile = File(...),
    answer_column: str = Form(...),
    studio_id: str = Form(...),
    sheet_name: str = Form("Hoja1"),
    db: Session = Depends(get_db),
):
    # 1. Validar que el studio_id sea un UUID válido y exista
    try:
        studio_uuid = uuid.UUID(studio_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El studio_id proporcionado no es un UUID válido",
        )

    studio = db.query(Studio).filter(Studio.id == studio_uuid).first()
    if not studio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Estudio con ID {studio_id} no encontrado",
        )

    # 2. Leer archivo y calcular checksum
    file_content = await file.read()
    checksum = hashlib.sha256(file_content).hexdigest()

    # Comprobar si ya existe un archivo importado con el mismo checksum en este estudio
    existing_file = (
        db.query(ImportedFile)
        .filter(ImportedFile.studio_id == studio_uuid, ImportedFile.checksum == checksum)
        .first()
    )
    if existing_file:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Este archivo ya fue importado en este estudio (ID archivo: {existing_file.id})",
        )

    # Guardar en archivo temporal para que pandas pueda leerlo
    suffix = Path(file.filename or "upload.xlsx").suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        # 3. Leer Excel con pandas
        try:
            df = pd.read_excel(tmp_path, sheet_name=sheet_name, engine="openpyxl")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error al leer la hoja '{sheet_name}' del Excel: {e}",
            )

        if answer_column not in df.columns:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La columna de respuestas '{answer_column}' no se encuentra en el archivo. Columnas disponibles: {list(df.columns)}",
            )

        # 4. Crear registro en imported_files con estado validating
        imported_file = ImportedFile(
            studio_id=studio_uuid,
            file_type="verbatims_xlsx",
            sheet_name=sheet_name,
            original_filename=file.filename or "upload.xlsx",
            checksum=checksum,
            status="validating",
        )
        db.add(imported_file)
        db.flush()

        # Determinar columna de ID de encuestado si existe
        id_col = None
        for col in df.columns:
            if str(col).lower() in ("id", "respondentid", "respondent_id", "folio", "caseid", "case_id", "respondent external id"):
                id_col = col
                break

        # 5. Iterar filas y procesar verbatims y grupos de menciones
        total_rows = 0
        mention_cache = {}  # Cache de normalized_text -> MentionGroup para este upload

        for idx, row in df.iterrows():
            raw_text = row[answer_column]
            if pd.isna(raw_text):
                continue
            
            raw_text_str = str(raw_text).strip()
            if not raw_text_str:
                continue

            cleaned = clean_text(raw_text_str)
            # Siempre se conserva respuesta_original y respuesta_limpia
            original_text = raw_text_str
            normalized_text = cleaned

            # Obtener ID de encuestado o usar el índice de fila
            resp_id = str(row[id_col]).strip() if (id_col is not None and not pd.isna(row[id_col])) else f"row_{idx}"

            # Controlar que no dupliquemos verbatims de la misma persona para la misma pregunta en este estudio
            existing_verbatim = (
                db.query(Verbatim)
                .filter(
                    Verbatim.studio_id == studio_uuid,
                    Verbatim.respondent_external_id == resp_id,
                    Verbatim.question_key == answer_column,
                )
                .first()
            )
            if existing_verbatim:
                continue

            # Buscar o crear el grupo de mención
            if normalized_text in mention_cache:
                m_group = mention_cache[normalized_text]
                m_group.frequency_count += 1
            else:
                m_group = (
                    db.query(MentionGroup)
                    .filter(
                        MentionGroup.studio_id == studio_uuid,
                        MentionGroup.normalized_text == normalized_text,
                    )
                    .first()
                )
                if m_group:
                    m_group.frequency_count += 1
                else:
                    m_group = MentionGroup(
                        studio_id=studio_uuid,
                        normalized_text=normalized_text,
                        sample_text=original_text[:200],  # Recorte para muestra
                        frequency_count=1,
                        status="pending_review",
                    )
                    db.add(m_group)
                    db.flush()
                mention_cache[normalized_text] = m_group

            # Crear Verbatim
            verbatim = Verbatim(
                studio_id=studio_uuid,
                mention_group_id=m_group.id,
                imported_file_id=imported_file.id,
                respondent_external_id=resp_id,
                question_key=answer_column,
                original_text=original_text,
                normalized_text=normalized_text,
                coding_status="pending",
            )
            db.add(verbatim)
            total_rows += 1

        # 6. Actualizar el estado del archivo importado
        imported_file.total_rows = total_rows
        imported_file.status = "validated"
        
        # 7. Actualizar el estado del estudio
        studio.status = "files_uploaded"

        db.commit()

        # Contar total de grupos de menciones en el estudio
        unique_mentions = db.query(MentionGroup).filter(MentionGroup.studio_id == studio_uuid).count()

        return UploadSummary(
            status="ok",
            imported_file_id=str(imported_file.id),
            studio_id=str(studio_uuid),
            total_rows=total_rows,
            unique_mentions=unique_mentions,
            file_name=imported_file.original_filename,
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno durante la importación del archivo: {e}",
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

"""Un solo endpoint: archivo ya en Supabase → normalize → fuzzy → CSV."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import CurrentUser, current_user
from app.database import get_db
from app.services.classify_pipeline import classify_file_to_csv
from app.services.pipelineProcess.models import SCORE_THRESHOLD

router = APIRouter(prefix="/api/v1", tags=["classify"])


@router.post("/files/{file_id}/classify")
def classify_file(
    file_id: uuid.UUID,
    verbatims_sheet: str | None = Query(
        default=None,
        description="Hoja de verbatims. Si se omite, se auto-detecta.",
    ),
    threshold: float = Query(default=SCORE_THRESHOLD, ge=0, le=100),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """
    Trae el Excel de Supabase por `file_id` (imported_files),
    normaliza, clasifica con fuzzy y devuelve CSV.
    No persiste clasificaciones.
    """
    try:
        csv_bytes, metrics = classify_file_to_csv(
            db,
            file_id,
            verbatims_sheet=verbatims_sheet,
            threshold=threshold,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Error al procesar archivo: {exc}") from exc

    filename = f"classifications_{file_id}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Classified-Count": str(metrics["classified"]),
            "X-Unmatched-Count": str(metrics["unmatched"]),
            "X-Input-Rows": str(metrics["input_rows"]),
            "X-Coding-Type": str(metrics["coding_type"]),
        },
    )

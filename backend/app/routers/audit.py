import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.access import require_audit_code_review, require_audit_item, require_subproject
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.pipeline.audit import (
    AuditConflict,
    AuditPrecondition,
    approve_code_review,
    approve_session,
    review_item,
    start_audit_session,
    update_item,
)
from app.repositories import (
    get_audit_session,
    get_audit_summary,
    list_audit_code_reviews,
    list_audit_items,
)

router = APIRouter(prefix="/api/v1", tags=["audit"])


class StartAuditIn(BaseModel):
    # resample solo tiene efecto si la sesión quedó desactualizada por un
    # reproceso del motor: crea una sesión nueva sin borrar la vieja.
    resample: bool = False


@router.post("/subprojects/{subproject_id}/audit/session", status_code=201)
def create_or_resume_audit_session(
    subproject_id: uuid.UUID,
    payload: StartAuditIn | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_subproject(db, subproject_id, user["id"])
    try:
        return start_audit_session(
            db, subproject_id, user_id=user["id"], resample=bool(payload and payload.resample)
        )
    except AuditPrecondition as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc


@router.get("/subprojects/{subproject_id}/audit/session")
def audit_session_summary(
    subproject_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_subproject(db, subproject_id, user["id"])
    summary = get_audit_summary(db, subproject_id)
    if not summary:
        raise HTTPException(404, "El subproyecto no tiene sesión de auditoría")
    return summary


@router.get("/subprojects/{subproject_id}/audit/codes")
def audit_code_reviews(
    subproject_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_subproject(db, subproject_id, user["id"])
    session = get_audit_session(db, subproject_id)
    if not session:
        raise HTTPException(404, "El subproyecto no tiene sesión de auditoría")
    return list_audit_code_reviews(db, session["id"])


@router.get("/audit-code-reviews/{review_id}/items")
def audit_items(
    review_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_audit_code_review(db, review_id, user["id"])
    items, total = list_audit_items(db, review_id, limit, offset)
    return {"total": total, "items": items}


@router.post("/audit-code-reviews/{review_id}/approve")
def approve_audit_section(
    review_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    # La unidad de revisión es la sección: da por correctos los items sin
    # corregir y cierra el code review (approved / with_corrections).
    require_audit_code_review(db, review_id, user["id"])
    try:
        return approve_code_review(db, review_id, user_id=user["id"])
    except AuditConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc


class NewCodeIn(BaseModel):
    label: str
    net_id: uuid.UUID | None = None


class ReviewDecision(BaseModel):
    action: str  # "reassign" | "remove" — lo "correcto" se da por sección, no por item
    code_ids: list[uuid.UUID] = []
    new_code: NewCodeIn | None = None
    comment: str | None = None
    expected_status: str | None = None


@router.post("/audit-items/{item_id}/review")
def review_audit_item(
    item_id: uuid.UUID,
    payload: ReviewDecision,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_audit_item(db, item_id, user["id"])
    decision = payload.model_dump(mode="json", exclude={"expected_status"})
    try:
        return review_item(
            db, item_id, decision, user_id=user["id"], expected_status=payload.expected_status
        )
    except AuditConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


class PatchItemIn(BaseModel):
    comment: str | None = None


@router.patch("/audit-items/{item_id}")
def patch_audit_item(
    item_id: uuid.UUID,
    payload: PatchItemIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_audit_item(db, item_id, user["id"])
    try:
        return update_item(db, item_id, user_id=user["id"], comment=payload.comment)
    except AuditConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.delete("/audit-items/{item_id}")
def delete_audit_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    # "Eliminar" audita: desactiva las asignaciones del verbatim (queda
    # 'needs_review', visible como "sin código") — no borra el item muestreado.
    require_audit_item(db, item_id, user["id"])
    try:
        return review_item(db, item_id, {"action": "remove"}, user_id=user["id"])
    except AuditConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc


@router.post("/subprojects/{subproject_id}/audit/approve")
def approve_audit(
    subproject_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_subproject(db, subproject_id, user["id"])
    try:
        return approve_session(db, subproject_id, user_id=user["id"])
    except AuditPrecondition as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc

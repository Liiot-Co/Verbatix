import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.pipeline.audit import (
    AuditConflict,
    AuditPrecondition,
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


@router.post("/studios/{studio_id}/audit/session", status_code=201)
def create_or_resume_audit_session(
    studio_id: uuid.UUID,
    payload: StartAuditIn | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    try:
        return start_audit_session(
            db, studio_id, user_id=user["id"], resample=bool(payload and payload.resample)
        )
    except AuditPrecondition as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc


@router.get("/studios/{studio_id}/audit/session")
def audit_session_summary(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    summary = get_audit_summary(db, studio_id)
    if not summary:
        raise HTTPException(404, "El estudio no tiene sesión de auditoría")
    return summary


@router.get("/studios/{studio_id}/audit/codes")
def audit_code_reviews(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    session = get_audit_session(db, studio_id)
    if not session:
        raise HTTPException(404, "El estudio no tiene sesión de auditoría")
    return list_audit_code_reviews(db, session["id"])


@router.get("/audit-code-reviews/{review_id}/items")
def audit_items(
    review_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    items, total = list_audit_items(db, review_id, limit, offset)
    return {"total": total, "items": items}


class NewCodeIn(BaseModel):
    label: str
    net_id: uuid.UUID | None = None


class ReviewDecision(BaseModel):
    action: str  # "correct" | "reassign" | "remove"
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
    status: str | None = None  # solo "pending" | "correct"


@router.patch("/audit-items/{item_id}")
def patch_audit_item(
    item_id: uuid.UUID,
    payload: PatchItemIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    try:
        return update_item(
            db, item_id, user_id=user["id"], comment=payload.comment, status=payload.status
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


@router.delete("/audit-items/{item_id}")
def delete_audit_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    # "Eliminar" audita: desactiva las asignaciones del verbatim (queda
    # 'needs_review', visible como "sin código") — no borra el item muestreado.
    try:
        return review_item(db, item_id, {"action": "remove"}, user_id=user["id"])
    except AuditConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc


@router.post("/studios/{studio_id}/audit/approve")
def approve_audit(
    studio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    try:
        return approve_session(db, studio_id, user_id=user["id"])
    except AuditPrecondition as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc

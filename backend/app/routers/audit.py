import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import (
    is_admin, require_audit_code_review, require_audit_item, require_capability,
    require_editable_audit, require_round, require_subproject,
)
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
    list_audit_population_codes,
    list_audit_population_items,
)

router = APIRouter(prefix="/api/v1", tags=["audit"])


class StartAuditIn(BaseModel):
    # resample solo tiene efecto si la sesión quedó desactualizada por un
    # reproceso del motor: crea una sesión nueva sin borrar la vieja.
    resample: bool = False


AUDITABLE_ROUND_STATUSES = {
    "preliminary_ready", "manual_coding", "audit_pending", "audit_approved",
    "nets_review", "ready_to_export", "completed",
}


def _round_audit_readiness(
    db: Session,
    round_id: uuid.UUID,
    round_status: str | None = None,
) -> dict:
    rows = db.execute(text("""
        select sp.id, sp.coding_type,
               count(mg.id) as total,
               count(mg.id) filter (
                 where mg.status not in ('auto_coded', 'resolved')
               ) as pending,
               count(mg.id) filter (where mg.status = 'auto_coded') as auto_coded,
               count(mg.id) filter (where mg.status = 'resolved') as resolved
        from subprojects sp
        left join mention_groups mg on mg.subproject_id = sp.id
        where sp.round_id = :round
        group by sp.id, sp.coding_type
        order by sp.coding_type
    """), {"round": round_id}).mappings().all()
    subprojects = []
    for row in rows:
        total = int(row["total"] or 0)
        pending = int(row["pending"] or 0)
        subprojects.append({
            "id": str(row["id"]),
            "coding_type": row["coding_type"],
            "total": total,
            "pending": pending,
            "auto_coded": int(row["auto_coded"] or 0),
            "resolved": int(row["resolved"] or 0),
            "progress_pct": round((total - pending) / total * 100, 1) if total else 100.0,
            "ready": pending == 0,
        })
    pending_total = sum(item["pending"] for item in subprojects)
    phase_ready = round_status in AUDITABLE_ROUND_STATUSES if round_status is not None else True
    return {
        "ready": bool(subprojects) and phase_ready and pending_total == 0,
        "pending": pending_total,
        "round_status": round_status,
        "subprojects": subprojects,
    }


@router.get("/rounds/{round_id}/audit/readiness")
def audit_readiness(
    round_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    resource = require_round(db, round_id, user["id"])
    require_capability(db, user["id"], "audit.view")
    return _round_audit_readiness(db, round_id, resource["status"])


@router.post("/subprojects/{subproject_id}/audit/session", status_code=201)
def create_or_resume_audit_session(
    subproject_id: uuid.UUID,
    payload: StartAuditIn | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    resource = require_subproject(db, subproject_id, user["id"])
    require_capability(db, user["id"], "audit.view")
    readiness = _round_audit_readiness(db, resource["round_id"], resource["round_status"])
    if not readiness["ready"]:
        raise HTTPException(
            422,
            f"Hay {readiness['pending']} grupos sin resolver antes de iniciar la auditoría",
        )
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
    require_capability(db, user["id"], "audit.view")
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
    require_capability(db, user["id"], "audit.view")
    session = get_audit_session(db, subproject_id)
    if not session:
        raise HTTPException(404, "El subproyecto no tiene sesión de auditoría")
    return list_audit_code_reviews(db, session["id"])


@router.get("/subprojects/{subproject_id}/audit/population/codes")
def audit_population_codes(
    subproject_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Vista «Ver todo»: 100% de lo codificado, agrupado por código primario."""
    require_subproject(db, subproject_id, user["id"])
    require_capability(db, user["id"], "audit.view")
    codes, total = list_audit_population_codes(db, subproject_id)
    return {"total": total, "codes": codes}


@router.get("/subprojects/{subproject_id}/audit/population/codes/{code_id}/items")
def audit_population_items(
    subproject_id: uuid.UUID,
    code_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_subproject(db, subproject_id, user["id"])
    require_capability(db, user["id"], "audit.view")
    items, total = list_audit_population_items(
        db, subproject_id, code_id, max(1, min(limit, 500)), max(0, offset)
    )
    return {"total": total, "items": items}


@router.get("/audit-code-reviews/{review_id}/items")
def audit_items(
    review_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_audit_code_review(db, review_id, user["id"])
    require_capability(db, user["id"], "audit.view")
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
    resource = require_audit_code_review(db, review_id, user["id"])
    require_capability(db, user["id"], "audit.approve")
    require_editable_audit(resource)
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
    resource = require_audit_item(db, item_id, user["id"])
    require_capability(db, user["id"], "audit.edit")
    require_editable_audit(resource)
    decision = payload.model_dump(mode="json", exclude={"expected_status", "comment"})
    try:
        result = review_item(
            db, item_id, decision, user_id=user["id"], expected_status=payload.expected_status
        )
        if payload.comment and payload.comment.strip():
            db.execute(text("""
                insert into audit_comments (audit_item_id, author_id, content)
                values (:item, :author, :content)
            """), {"item": item_id, "author": user["id"], "content": payload.comment.strip()})
            db.commit()
        return result
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
    resource = require_audit_item(db, item_id, user["id"])
    require_capability(db, user["id"], "audit.edit")
    require_editable_audit(resource)
    try:
        if not payload.comment or not payload.comment.strip():
            raise ValueError("El comentario no puede estar vacío")
        comment_id = db.execute(text("""
            insert into audit_comments (audit_item_id, author_id, content)
            values (:item, :author, :content) returning id
        """), {"item": item_id, "author": user["id"], "content": payload.comment.strip()}).scalar_one()
        db.commit()
        return {"id": str(comment_id), "content": payload.comment.strip()}
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
    resource = require_audit_item(db, item_id, user["id"])
    require_capability(db, user["id"], "audit.edit")
    require_editable_audit(resource)
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
    require_capability(db, user["id"], "audit.approve")
    try:
        return approve_session(db, subproject_id, user_id=user["id"])
    except AuditPrecondition as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc


class CommentIn(BaseModel):
    content: str


@router.get("/audit-items/{item_id}/comments")
def list_comments(item_id: uuid.UUID, db: Session = Depends(get_db),
                  user: CurrentUser = Depends(current_user)):
    require_audit_item(db, item_id, user["id"])
    require_capability(db, user["id"], "audit.view")
    rows = db.execute(text("""
        select ac.id, ac.content, ac.created_at, ac.updated_at, ac.author_id,
               u.name author_name, u.email author_email,
               coalesce(array_agg(distinct ur.role_code) filter (where ur.role_code is not null), '{}') roles
        from audit_comments ac left join users u on u.id = ac.author_id
        left join user_roles ur on ur.user_id = u.id
        where ac.audit_item_id = :item and ac.deleted_at is null
        group by ac.id, u.name, u.email order by ac.created_at
    """), {"item": item_id}).mappings().all()
    return [{**dict(row), "id": str(row["id"]),
             "author_id": str(row["author_id"]) if row["author_id"] else None,
             "roles": list(row["roles"])} for row in rows]


@router.post("/audit-items/{item_id}/comments", status_code=201)
def create_comment(item_id: uuid.UUID, payload: CommentIn, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(current_user)):
    resource = require_audit_item(db, item_id, user["id"])
    require_capability(db, user["id"], "audit.edit")
    require_editable_audit(resource)
    content = payload.content.strip()
    if not content:
        raise HTTPException(400, "El comentario no puede estar vacío")
    comment_id = db.execute(text("""
        insert into audit_comments (audit_item_id, author_id, content)
        values (:item, :author, :content) returning id
    """), {"item": item_id, "author": user["id"], "content": content}).scalar_one()
    db.commit()
    return {"id": str(comment_id), "content": content}


@router.patch("/audit-comments/{comment_id}")
def edit_comment(comment_id: uuid.UUID, payload: CommentIn, db: Session = Depends(get_db),
                 user: CurrentUser = Depends(current_user)):
    row = db.execute(text("""
        select ac.author_id, ac.audit_item_id from audit_comments ac
        where ac.id = :id and ac.deleted_at is null
    """), {"id": comment_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Comentario no encontrado")
    resource = require_audit_item(db, row["audit_item_id"], user["id"])
    require_capability(db, user["id"], "audit.edit")
    require_editable_audit(resource)
    if row["author_id"] != user["id"] and not is_admin(db, user["id"]):
        raise HTTPException(403, "Solo puedes editar tus comentarios")
    content = payload.content.strip()
    if not content:
        raise HTTPException(400, "El comentario no puede estar vacío")
    db.execute(text("update audit_comments set content = :content where id = :id"),
               {"content": content, "id": comment_id})
    db.commit()
    return {"id": str(comment_id), "content": content}


@router.delete("/audit-comments/{comment_id}", status_code=204)
def delete_comment(comment_id: uuid.UUID, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(current_user)):
    row = db.execute(text("""
        select author_id, audit_item_id from audit_comments where id = :id and deleted_at is null
    """), {"id": comment_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Comentario no encontrado")
    resource = require_audit_item(db, row["audit_item_id"], user["id"])
    require_capability(db, user["id"], "audit.edit")
    require_editable_audit(resource)
    if row["author_id"] != user["id"] and not is_admin(db, user["id"]):
        raise HTTPException(403, "Solo puedes eliminar tus comentarios")
    db.execute(text("update audit_comments set deleted_at = now() where id = :id"), {"id": comment_id})
    db.commit()

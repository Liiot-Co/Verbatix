import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import require_mention_group, require_subproject
from app.core.auth import CurrentUser, current_user
from app.core.config import settings
from app.core.database import get_db
from app.pipeline.resolution import BelowThresholdError, ResolutionConflict, resolve_group
from app.repositories import (
    _current_codebook_id,
    create_code,
    get_group_detail,
    get_resolution_queue,
    get_resolution_summary,
    list_codebook_codes,
    log_action,
    unresolve_group,
)

router = APIRouter(prefix="/api/v1", tags=["resolution"])

DEFAULT_STATUSES = ["anomaly", "below_threshold", "pending_review"]


def _default_statuses() -> list[str]:
    return [*DEFAULT_STATUSES, "auto_coded"] if settings.resolution_include_auto_coded else list(DEFAULT_STATUSES)


def _round_id_for_subproject(db: Session, subproject_id: uuid.UUID) -> uuid.UUID:
    """audit_logs.round_id no bajó de nivel en la migración v8, así que loggear
    una acción sobre un grupo necesita resolver el round_id de su subproyecto."""
    return db.execute(
        text("select round_id from subprojects where id = :id"), {"id": subproject_id}
    ).scalar()


@router.get("/subprojects/{subproject_id}/resolution/queue")
def resolution_queue(
    subproject_id: uuid.UUID,
    statuses: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_subproject(db, subproject_id, user["id"])
    status_list = statuses.split(",") if statuses else _default_statuses()
    items, total = get_resolution_queue(db, subproject_id, status_list, limit, offset)
    return {"total": total, "items": items}


@router.get("/subprojects/{subproject_id}/resolution/summary")
def resolution_summary(
    subproject_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_subproject(db, subproject_id, user["id"])
    return get_resolution_summary(db, subproject_id)


@router.get("/subprojects/{subproject_id}/codes")
def subproject_codes(
    subproject_id: uuid.UUID,
    include_system: bool = False,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    sp = require_subproject(db, subproject_id, user["id"])
    return list_codebook_codes(db, sp["codebook_id"], include_system)


class NewCodeIn(BaseModel):
    label: str
    net_id: uuid.UUID | None = None


@router.post("/subprojects/{subproject_id}/codes", status_code=201)
def create_subproject_code(
    subproject_id: uuid.UUID,
    payload: NewCodeIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    sp = require_subproject(db, subproject_id, user["id"])
    cb_id = sp["codebook_id"]
    if not cb_id:
        raise HTTPException(404, "Subproyecto no tiene codebook")
    result = create_code(db, cb_id, payload.label, payload.net_id, user["id"])
    db.commit()
    return result


@router.get("/mention-groups/{group_id}")
def mention_group_detail(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_mention_group(db, group_id, user["id"])
    detail = get_group_detail(db, group_id)
    if not detail:
        raise HTTPException(404, "Grupo no encontrado")
    return detail


class ResolveDecision(BaseModel):
    action: str  # "approve" | "discard"
    code_ids: list[uuid.UUID] = []
    new_code: NewCodeIn | None = None
    add_alias: bool = False
    expected_status: str | None = None


@router.post("/mention-groups/{group_id}/resolve")
def resolve_mention_group(
    group_id: uuid.UUID,
    payload: ResolveDecision,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_mention_group(db, group_id, user["id"])
    detail = get_group_detail(db, group_id)
    if not detail:
        raise HTTPException(404, "Grupo no encontrado")

    decision = payload.model_dump(mode="json", exclude={"expected_status"})
    try:
        return resolve_group(
            db, uuid.UUID(detail["subproject_id"]), group_id, decision,
            user_id=user["id"], expected_status=payload.expected_status,
        )
    except ResolutionConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except BelowThresholdError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


class BulkResolveIn(BaseModel):
    group_ids: list[uuid.UUID]
    decision: ResolveDecision


@router.post("/subprojects/{subproject_id}/resolution/bulk")
def bulk_resolve(
    subproject_id: uuid.UUID,
    payload: BulkResolveIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_subproject(db, subproject_id, user["id"])
    decision = payload.decision.model_dump(mode="json", exclude={"expected_status"})
    resolved, failed = [], []
    for gid in payload.group_ids:
        try:
            result = resolve_group(db, subproject_id, gid, decision, user_id=user["id"])
            resolved.append(result)
        except (ResolutionConflict, BelowThresholdError, LookupError, ValueError) as exc:
            db.rollback()
            failed.append({"group_id": str(gid), "error": str(exc)})
    return {"resolved": resolved, "failed": failed}


@router.post("/mention-groups/{group_id}/unresolve")
def unresolve_mention_group(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    """Deshace la última resolución de un grupo (atajo Ctrl/Cmd+Z en el sidebar)."""
    require_mention_group(db, group_id, user["id"])
    detail = get_group_detail(db, group_id)
    if not detail:
        raise HTTPException(404, "Grupo no encontrado")

    unresolve_group(db, group_id, user["id"])
    round_id = _round_id_for_subproject(db, uuid.UUID(detail["subproject_id"]))
    log_action(
        db, user["id"], round_id, "mention_group", group_id,
        "unresolve",
        old_value={"status": "resolved"},
        new_value={"status": "pending_review"},
    )
    db.commit()
    return {"group_id": str(group_id), "status": "pending_review"}

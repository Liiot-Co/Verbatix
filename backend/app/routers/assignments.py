"""Asignación de usuarios a un Estudio completo (`assignments`) — única fuente
de la visibilidad por rol (sección 2.1/2.9 del documento v8): cubre
automáticamente todas las categorías/rondas/subproyectos presentes y futuros
de ese Estudio, sin reasignar por ronda. Solo un admin puede asignar/revocar."""
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import require_admin, require_project
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.services.notifications import emit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects/{study_id}/assignments", tags=["assignments"])


class AssignmentIn(BaseModel):
    user_id: uuid.UUID
    role_context: str | None = None  # legado: las capacidades vienen de user_roles


@router.post("", status_code=201)
def create_assignment(
    study_id: uuid.UUID,
    payload: AssignmentIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    if payload.role_context not in (None, "codificador", "supervisor"):
        raise HTTPException(400, "role_context debe ser 'codificador' o 'supervisor'")

    aid = uuid.uuid4()
    db.execute(
        text("""
            insert into assignments (id, study_id, user_id, role_context, status, assigned_by)
            values (:id, :study_id, :u, :ctx, 'active', :by)
            on conflict (study_id, user_id) do update set
              role_context = excluded.role_context, status = 'active', assigned_by = excluded.assigned_by,
              revoked_at = null, assigned_at = now()
        """),
        {"id": aid, "study_id": study_id, "u": payload.user_id, "ctx": payload.role_context, "by": user["id"]},
    )
    db.commit()
    if payload.user_id != user["id"]:
        try:
            emit(
                db,
                notification_type="project_assigned",
                title="Nuevo proyecto asignado",
                body="Te asignaron a un proyecto. Ya puedes revisar su trabajo pendiente.",
                related_entity_id=study_id,
                user_ids=[payload.user_id],
                sender_id=user["id"],
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("No se pudo emitir la notificación de asignación")
    return {"study_id": str(study_id), "user_id": str(payload.user_id), "role_context": payload.role_context}


@router.get("")
def list_assignments(
    study_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_project(db, study_id, user["id"])
    rows = db.execute(
        text("""
            select a.id, a.user_id, u.email, u.name, u.account_status,
                   a.status, a.assigned_at,
                   coalesce(array_agg(distinct ur.role_code) filter (where ur.role_code is not null), '{}') roles
            from assignments a
            join users u on u.id = a.user_id
            left join user_roles ur on ur.user_id = u.id
            where a.study_id = :study_id and a.status = 'active' and a.revoked_at is null
            group by a.id, u.email, u.name, u.account_status
            order by a.assigned_at desc
        """),
        {"study_id": study_id},
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "user_id": str(r["user_id"]),
            "email": r["email"],
            "name": r["name"],
            "initials": (r["name"] or r["email"] or "?")[0].upper(),
            "roles": list(r["roles"]),
            "account_status": r["account_status"],
            "status": r["status"],
            "assigned_at": r["assigned_at"],
        }
        for r in rows
    ]


@router.delete("/{user_id}", status_code=204)
def revoke_assignment(
    study_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    updated = db.execute(
        text("""
            update assignments set status = 'reassigned', revoked_at = now()
            where study_id = :study_id and user_id = :uid and status = 'active'
            returning id
        """),
        {"study_id": study_id, "uid": user_id},
    ).scalar()
    if not updated:
        raise HTTPException(404, "Asignación no encontrada")
    db.commit()

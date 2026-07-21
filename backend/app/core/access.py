"""Autorización centralizada por cuenta, capacidades acumulables y membresía."""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


ALL_CAPABILITIES = {
    "users.manage", "assignments.manage", "projects.manage", "rounds.manage",
    "resolution.view", "resolution.edit", "audit.view", "audit.edit",
    "audit.approve", "reports.view", "reports.export",
}
CAPABILITIES_BY_ROLE: dict[str, set[str]] = {
    "admin": ALL_CAPABILITIES,
    "codificador": {
        "resolution.view", "resolution.edit", "audit.view", "audit.edit",
        "reports.view", "reports.export",
    },
    "supervisor": {
        "audit.view", "audit.edit", "audit.approve", "reports.view", "reports.export",
    },
}


def user_roles(db: Session, user_id) -> set[str]:
    return set(db.execute(
        text("select role_code from user_roles where user_id = :u"), {"u": user_id}
    ).scalars().all())


def is_admin(db: Session, user_id) -> bool:
    return bool(db.execute(
        text("select 1 from user_roles where user_id = :u and role_code = 'admin'"),
        {"u": user_id},
    ).scalar())


def require_active_account(db: Session, user_id) -> None:
    status_value = db.execute(
        text("select account_status from users where id = :u"), {"u": user_id}
    ).scalar()
    if status_value != "active":
        raise HTTPException(403, "Cuenta sin acceso activo")


def has_capability(db: Session, user_id, capability: str) -> bool:
    return any(capability in CAPABILITIES_BY_ROLE.get(role, set()) for role in user_roles(db, user_id))


def require_capability(db: Session, user_id, capability: str) -> None:
    require_active_account(db, user_id)
    if not has_capability(db, user_id, capability):
        raise HTTPException(403, {"code": "capability_required", "capability": capability})


def visible_project_ids(db: Session, user_id) -> list[uuid.UUID] | None:
    # El dependency current_user ya garantiza cuenta activa en los endpoints.
    # Mantener esta función enfocada en visibilidad también facilita su uso aislado.
    if is_admin(db, user_id):
        return None
    return list(db.execute(
        text("""
            select project_id from assignments
            where user_id = :u and status = 'active' and revoked_at is null
        """), {"u": user_id}
    ).scalars().all())


def require_admin(db: Session, user_id) -> None:
    require_capability(db, user_id, "users.manage")


def require_project_membership(db: Session, project_id: uuid.UUID, user_id) -> None:
    require_active_account(db, user_id)
    if is_admin(db, user_id):
        exists = db.execute(text("select 1 from studios where id = :id"), {"id": project_id}).scalar()
    else:
        exists = db.execute(text("""
            select 1 from studios p
            join assignments a on a.project_id = p.id
            where p.id = :id and a.user_id = :u and a.status = 'active' and a.revoked_at is null
        """), {"id": project_id, "u": user_id}).scalar()
    if not exists:
        raise HTTPException(404, "Proyecto no encontrado")


def require_project(db: Session, project_id: uuid.UUID, user_id) -> None:
    require_project_membership(db, project_id, user_id)


def _resource(db: Session, sql: str, resource_id, user_id, not_found: str) -> dict:
    require_active_account(db, user_id)
    row = db.execute(text(sql), {"id": resource_id}).mappings().first()
    if not row:
        raise HTTPException(404, not_found)
    require_project_membership(db, row["project_id"], user_id)
    return dict(row)


def require_round(db: Session, round_id: uuid.UUID, user_id) -> dict:
    return _resource(db, """
        select r.*, r.project_id from rounds r where r.id = :id
    """, round_id, user_id, "Ronda no existe")


def require_subproject(db: Session, subproject_id: uuid.UUID, user_id) -> dict:
    return _resource(db, """
        select sp.*, r.project_id, r.status as round_status
        from subprojects sp join rounds r on r.id = sp.round_id where sp.id = :id
    """, subproject_id, user_id, "Subproyecto no existe")


def require_mention_group(db: Session, group_id: uuid.UUID, user_id) -> dict:
    return _resource(db, """
        select g.id, g.subproject_id, r.project_id, r.status as round_status
        from mention_groups g join subprojects sp on sp.id = g.subproject_id
        join rounds r on r.id = sp.round_id where g.id = :id
    """, group_id, user_id, "Grupo no encontrado")


def require_audit_code_review(db: Session, review_id: uuid.UUID, user_id) -> dict:
    return _resource(db, """
        select acr.id, ases.subproject_id, ases.status as audit_status, r.project_id
        from audit_code_reviews acr join audit_sessions ases on ases.id = acr.audit_session_id
        join subprojects sp on sp.id = ases.subproject_id join rounds r on r.id = sp.round_id
        where acr.id = :id
    """, review_id, user_id, "Sección de auditoría no encontrada")


def require_audit_item(db: Session, item_id: uuid.UUID, user_id) -> dict:
    return _resource(db, """
        select i.id, ases.subproject_id, ases.status as audit_status, r.project_id
        from audit_items i join audit_code_reviews acr on acr.id = i.audit_code_review_id
        join audit_sessions ases on ases.id = acr.audit_session_id
        join subprojects sp on sp.id = ases.subproject_id join rounds r on r.id = sp.round_id
        where i.id = :id
    """, item_id, user_id, "Item de auditoría no encontrado")


def require_resolution_phase(resource: dict) -> None:
    if resource.get("round_status") not in {
        "preliminary_ready", "manual_coding", "audit_pending", "audit_approved",
        "nets_review", "ready_to_export", "completed",
    }:
        raise HTTPException(403, {"code": "processing_required"})


def require_editable_audit(resource: dict) -> None:
    if resource.get("audit_status") == "approved":
        raise HTTPException(409, "La auditoría aprobada es de solo lectura")

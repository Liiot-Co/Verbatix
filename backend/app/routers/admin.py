"""Administración transaccional de cuentas, roles y asignaciones."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.access import require_admin
from app.core.auth import CurrentUser, current_user
from app.core.database import get_db
from app.core.security import revoke_sessions, rotate_recovery_code

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
VALID_ROLES = {"admin", "codificador", "supervisor"}


class StatusIn(BaseModel):
    account_status: Literal["active", "suspended"]


class RolesIn(BaseModel):
    roles: list[str]


class AssignmentSetIn(BaseModel):
    project_ids: list[uuid.UUID]


class ApproveAssignIn(RolesIn, AssignmentSetIn):
    pass


def _ensure_roles(roles: list[str]) -> list[str]:
    normalized = sorted(set(roles))
    invalid = set(normalized) - VALID_ROLES
    if invalid:
        raise HTTPException(400, f"Roles inválidos: {', '.join(sorted(invalid))}")
    return normalized


def _last_active_admin(db: Session, target_id, replacement_roles: list[str] | None = None,
                       replacement_status: str | None = None) -> bool:
    target_is_admin = db.execute(text("""
        select 1 from user_roles ur join users u on u.id = ur.user_id
        where ur.user_id = :u and ur.role_code = 'admin' and u.account_status = 'active'
    """), {"u": target_id}).scalar()
    if not target_is_admin:
        return False
    remains_admin = replacement_roles is None or "admin" in replacement_roles
    remains_active = replacement_status is None or replacement_status == "active"
    if remains_admin and remains_active:
        return False
    count = db.execute(text("""
        select count(distinct u.id) from users u
        join user_roles ur on ur.user_id = u.id and ur.role_code = 'admin'
        where u.account_status = 'active'
    """)).scalar_one()
    return count <= 1


def _log(db: Session, actor_id, target_id, action: str, old_value=None, new_value=None) -> None:
    db.execute(text("""
        insert into audit_logs (user_id, entity_name, entity_id, action, old_value, new_value)
        values (:actor, 'user', :target, :action, cast(:old as jsonb), cast(:new as jsonb))
    """), {
        "actor": actor_id, "target": target_id, "action": action,
        "old": __import__("json").dumps(old_value) if old_value is not None else None,
        "new": __import__("json").dumps(new_value) if new_value is not None else None,
    })


@router.get("/users")
def list_users(
    q: str | None = None,
    account_status: str | None = Query(default=None),
    db: Session = Depends(get_db), user: CurrentUser = Depends(current_user),
):
    require_admin(db, user["id"])
    rows = db.execute(text("""
        select u.id, u.email, u.name, u.account_status, u.presence_status, u.presence_changed_at, u.created_at,
               coalesce(array_agg(distinct ur.role_code) filter (where ur.role_code is not null), '{}') roles,
               count(distinct a.project_id) filter (where a.status = 'active' and a.revoked_at is null) assignments_count,
               coalesce(array_agg(distinct a.project_id) filter (
                 where a.status = 'active' and a.revoked_at is null
               ), '{}') project_ids
        from users u left join user_roles ur on ur.user_id = u.id
        left join assignments a on a.user_id = u.id
        where (:status is null or u.account_status = :status)
          and (:q is null or u.email ilike '%' || :q || '%' or coalesce(u.name, '') ilike '%' || :q || '%')
        group by u.id order by (u.account_status = 'pending') desc, u.created_at desc
    """), {"q": q.strip() if q else None, "status": account_status}).mappings().all()
    return [{
        **dict(r), "id": str(r["id"]), "roles": list(r["roles"]),
        "project_ids": [str(project_id) for project_id in r["project_ids"]],
    } for r in rows]


@router.patch("/users/{user_id}/status")
def set_status(user_id: uuid.UUID, payload: StatusIn, db: Session = Depends(get_db),
               user: CurrentUser = Depends(current_user)):
    require_admin(db, user["id"])
    if _last_active_admin(db, user_id, replacement_status=payload.account_status):
        raise HTTPException(409, "No se puede suspender al último administrador activo")
    old = db.execute(text("select account_status from users where id = :u"), {"u": user_id}).scalar()
    if old is None:
        raise HTTPException(404, "Usuario no encontrado")
    db.execute(text("""
        update users set account_status = :status, is_active = (:status = 'active'),
          approved_by = case when :status = 'active' then :actor else approved_by end,
          approved_at = case when :status = 'active' then coalesce(approved_at, now()) else approved_at end
        where id = :u
    """), {"status": payload.account_status, "actor": user["id"], "u": user_id})
    if payload.account_status == "suspended":
        revoke_sessions(db, user_id)
    _log(db, user["id"], user_id, "account_status", {"status": old}, {"status": payload.account_status})
    db.commit()
    return {"id": str(user_id), "account_status": payload.account_status}


@router.put("/users/{user_id}/roles")
def replace_roles(user_id: uuid.UUID, payload: RolesIn, db: Session = Depends(get_db),
                  user: CurrentUser = Depends(current_user)):
    require_admin(db, user["id"])
    roles = _ensure_roles(payload.roles)
    if _last_active_admin(db, user_id, replacement_roles=roles):
        raise HTTPException(409, "No se puede degradar al último administrador activo")
    old = list(db.execute(text("select role_code from user_roles where user_id = :u"), {"u": user_id}).scalars())
    if db.execute(text("select 1 from users where id = :u"), {"u": user_id}).scalar() is None:
        raise HTTPException(404, "Usuario no encontrado")
    db.execute(text("delete from user_roles where user_id = :u"), {"u": user_id})
    for role in roles:
        db.execute(text("insert into user_roles (user_id, role_code) values (:u, :r)"), {"u": user_id, "r": role})
    _log(db, user["id"], user_id, "roles.replace", {"roles": old}, {"roles": roles})
    db.commit()
    return {"id": str(user_id), "roles": roles}


def _replace_assignments(db: Session, target_id, project_ids: list[uuid.UUID], actor_id) -> None:
    unique_ids = list(dict.fromkeys(project_ids))
    existing_count = db.execute(text("select count(*) from projects where id = any(:ids)"), {"ids": unique_ids}).scalar() if unique_ids else 0
    if existing_count != len(unique_ids):
        raise HTTPException(400, "Uno o más proyectos no existen")
    if unique_ids:
        db.execute(text("""
            update assignments set status = 'reassigned', revoked_at = now()
            where user_id = :u and status = 'active' and revoked_at is null
              and not (project_id = any(:ids))
        """), {"u": target_id, "ids": unique_ids})
    else:
        db.execute(text("""
            update assignments set status = 'reassigned', revoked_at = now()
            where user_id = :u and status = 'active' and revoked_at is null
        """), {"u": target_id})
    for project_id in unique_ids:
        db.execute(text("""
            insert into assignments (project_id, user_id, role_context, status, assigned_by)
            values (:p, :u, null, 'active', :actor)
            on conflict (project_id, user_id) do update
            set status = 'active', revoked_at = null, assigned_by = excluded.assigned_by,
                assigned_at = now(), role_context = null
        """), {"p": project_id, "u": target_id, "actor": actor_id})


@router.put("/users/{user_id}/assignments")
def replace_assignments(user_id: uuid.UUID, payload: AssignmentSetIn, db: Session = Depends(get_db),
                        user: CurrentUser = Depends(current_user)):
    require_admin(db, user["id"])
    _replace_assignments(db, user_id, payload.project_ids, user["id"])
    _log(db, user["id"], user_id, "assignments.replace", new_value={"project_ids": [str(v) for v in payload.project_ids]})
    db.commit()
    return {"id": str(user_id), "project_ids": [str(v) for v in payload.project_ids]}


@router.post("/users/{user_id}/approve-and-assign")
def approve_and_assign(user_id: uuid.UUID, payload: ApproveAssignIn, db: Session = Depends(get_db),
                       user: CurrentUser = Depends(current_user)):
    require_admin(db, user["id"])
    roles = _ensure_roles(payload.roles)
    if not roles:
        raise HTTPException(400, "Selecciona al menos un rol")
    if db.execute(text("select 1 from users where id = :u"), {"u": user_id}).scalar() is None:
        raise HTTPException(404, "Usuario no encontrado")
    db.execute(text("delete from user_roles where user_id = :u"), {"u": user_id})
    for role in roles:
        db.execute(text("insert into user_roles (user_id, role_code) values (:u, :r)"), {"u": user_id, "r": role})
    _replace_assignments(db, user_id, payload.project_ids, user["id"])
    db.execute(text("""
        update users set account_status = 'active', is_active = true,
          approved_by = :actor, approved_at = now() where id = :u
    """), {"actor": user["id"], "u": user_id})
    _log(db, user["id"], user_id, "approve_and_assign", new_value={
        "roles": roles, "project_ids": [str(v) for v in payload.project_ids],
    })
    db.commit()
    return {"id": str(user_id), "account_status": "active", "roles": roles,
            "project_ids": [str(v) for v in payload.project_ids]}


@router.get("/assignments")
def all_assignments(db: Session = Depends(get_db), user: CurrentUser = Depends(current_user)):
    require_admin(db, user["id"])
    rows = db.execute(text("""
        select a.id, a.project_id, p.name project_name, a.user_id, u.email, u.name,
               u.account_status, a.assigned_at,
               coalesce(array_agg(distinct ur.role_code) filter (where ur.role_code is not null), '{}') roles
        from assignments a join projects p on p.id = a.project_id join users u on u.id = a.user_id
        left join user_roles ur on ur.user_id = u.id
        where a.status = 'active' and a.revoked_at is null
        group by a.id, p.name, u.email, u.name, u.account_status order by p.name, u.name, u.email
    """)).mappings().all()
    return [{**dict(r), "id": str(r["id"]), "project_id": str(r["project_id"]),
             "user_id": str(r["user_id"]), "roles": list(r["roles"])} for r in rows]


@router.post("/users/{user_id}/recovery-code")
def regenerate_recovery(user_id: uuid.UUID, db: Session = Depends(get_db),
                        user: CurrentUser = Depends(current_user)):
    require_admin(db, user["id"])
    if db.execute(text("select 1 from users where id = :u"), {"u": user_id}).scalar() is None:
        raise HTTPException(404, "Usuario no encontrado")
    code = rotate_recovery_code(db, user_id)
    _log(db, user["id"], user_id, "recovery_code.rotate")
    db.commit()
    return {"recovery_code": code}

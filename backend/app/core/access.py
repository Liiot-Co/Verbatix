"""Comprueba que un recurso pertenece al usuario autenticado (projects.created_by)."""
import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


def is_admin(db: Session, user_id) -> bool:
    return bool(db.execute(
        text("select 1 from user_roles where user_id = :u and role_code = 'admin'"),
        {"u": user_id},
    ).scalar())


def visible_project_ids(db: Session, user_id) -> list[uuid.UUID] | None:
    """None = sin filtro (admin, ve todo). Lista = solo estos (sección 2.1)."""
    if is_admin(db, user_id):
        return None
    return list(db.execute(
        text("select project_id from assignments where user_id = :u and status = 'active'"),
        {"u": user_id},
    ).scalars().all())


def require_project(db: Session, project_id: uuid.UUID, user_id) -> None:
    if not db.execute(
        text("select 1 from projects where id = :id and created_by = :u"),
        {"id": project_id, "u": user_id},
    ).scalar():
        raise HTTPException(404, "Proyecto no encontrado")


def require_round(db: Session, round_id: uuid.UUID, user_id) -> dict:
    """La Ronda: ola de datos de un estudio, cuelga directo de projects (v8)."""
    row = db.execute(
        text("""
            select r.*
            from rounds r
            join projects p on p.id = r.project_id
            where r.id = :id and p.created_by = :u
        """),
        {"id": round_id, "u": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Ronda no existe")
    return dict(row)


def require_subproject(db: Session, subproject_id: uuid.UUID, user_id) -> dict:
    """El Subproyecto (Marcas / Razones): unidad de procesamiento por ronda (v8)."""
    row = db.execute(
        text("""
            select sp.*
            from subprojects sp
            join rounds r on r.id = sp.round_id
            join projects p on p.id = r.project_id
            where sp.id = :id and p.created_by = :u
        """),
        {"id": subproject_id, "u": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Subproyecto no existe")
    return dict(row)


def require_mention_group(db: Session, group_id: uuid.UUID, user_id) -> dict:
    row = db.execute(
        text("""
            select g.id, g.subproject_id
            from mention_groups g
            join subprojects sp on sp.id = g.subproject_id
            join rounds r on r.id = sp.round_id
            join projects p on p.id = r.project_id
            where g.id = :id and p.created_by = :u
        """),
        {"id": group_id, "u": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Grupo no encontrado")
    return dict(row)


def require_audit_code_review(db: Session, review_id: uuid.UUID, user_id) -> dict:
    row = db.execute(
        text("""
            select acr.id, ases.subproject_id
            from audit_code_reviews acr
            join audit_sessions ases on ases.id = acr.audit_session_id
            join subprojects sp on sp.id = ases.subproject_id
            join rounds r on r.id = sp.round_id
            join projects p on p.id = r.project_id
            where acr.id = :id and p.created_by = :u
        """),
        {"id": review_id, "u": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Sección de auditoría no encontrada")
    return dict(row)


def require_audit_item(db: Session, item_id: uuid.UUID, user_id) -> dict:
    row = db.execute(
        text("""
            select i.id, ases.subproject_id
            from audit_items i
            join audit_code_reviews acr on acr.id = i.audit_code_review_id
            join audit_sessions ases on ases.id = acr.audit_session_id
            join subprojects sp on sp.id = ases.subproject_id
            join rounds r on r.id = sp.round_id
            join projects p on p.id = r.project_id
            where i.id = :id and p.created_by = :u
        """),
        {"id": item_id, "u": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Item de auditoría no encontrado")
    return dict(row)

"""Comprueba que un recurso pertenece al usuario autenticado (projects.created_by)."""
import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


def require_project(db: Session, project_id: uuid.UUID, user_id) -> None:
    if not db.execute(
        text("select 1 from projects where id = :id and created_by = :u"),
        {"id": project_id, "u": user_id},
    ).scalar():
        raise HTTPException(404, "Proyecto no encontrado")


def require_round(db: Session, round_id: uuid.UUID, user_id) -> None:
    if not db.execute(
        text("""
            select 1 from rounds r
            join projects p on p.id = r.project_id
            where r.id = :id and p.created_by = :u
        """),
        {"id": round_id, "u": user_id},
    ).scalar():
        raise HTTPException(404, "Ronda no encontrada")


def require_studio(db: Session, studio_id: uuid.UUID, user_id) -> dict:
    row = db.execute(
        text("""
            select s.*
            from studio s
            join rounds r on r.id = s.round_id
            join projects p on p.id = r.project_id
            where s.id = :id and p.created_by = :u
        """),
        {"id": studio_id, "u": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Estudio no existe")
    return dict(row)


def require_mention_group(db: Session, group_id: uuid.UUID, user_id) -> dict:
    row = db.execute(
        text("""
            select g.id, g.studio_id
            from mention_groups g
            join studio s on s.id = g.studio_id
            join rounds r on r.id = s.round_id
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
            select acr.id, ases.studio_id
            from audit_code_reviews acr
            join audit_sessions ases on ases.id = acr.audit_session_id
            join studio s on s.id = ases.studio_id
            join rounds r on r.id = s.round_id
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
            select i.id, ases.studio_id
            from audit_items i
            join audit_code_reviews acr on acr.id = i.audit_code_review_id
            join audit_sessions ases on ases.id = acr.audit_session_id
            join studio s on s.id = ases.studio_id
            join rounds r on r.id = s.round_id
            join projects p on p.id = r.project_id
            where i.id = :id and p.created_by = :u
        """),
        {"id": item_id, "u": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Item de auditoría no encontrado")
    return dict(row)

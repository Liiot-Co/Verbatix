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

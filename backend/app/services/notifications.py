"""Emisión no crítica de notificaciones in-app."""
from typing import Literal
import uuid

from sqlalchemy.orm import Session

from app.repositories import create_notifications

NotificationType = Literal["project_assigned", "ready_for_audit", "audit_approved"]
NOTIFICATION_TYPES: set[str] = {"project_assigned", "ready_for_audit", "audit_approved"}


def emit(
    db: Session,
    *,
    notification_type: NotificationType,
    title: str,
    body: str,
    related_entity_id: uuid.UUID | None,
    user_ids: list[uuid.UUID],
    sender_id: uuid.UUID,
) -> int:
    if notification_type not in NOTIFICATION_TYPES:
        raise ValueError(f"Tipo de notificación inválido: {notification_type}")
    return create_notifications(
        db, list(set(user_ids)), notification_type, title, body, related_entity_id, sender_id
    )

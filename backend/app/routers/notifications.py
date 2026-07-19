"""Bandeja y long polling de notificaciones in-app."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, current_user
from app.core.database import SessionLocal, get_db
from app.repositories import (
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    notification_preview,
    notification_stream_state,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
STREAM_TIMEOUT_SECONDS = 25
STREAM_CHECK_SECONDS = 1


def _stream_snapshot(user_id: uuid.UUID) -> dict:
    """Cada chequeo toma y libera su propia Session para no agotar el pool."""
    with SessionLocal() as db:
        unread_count, signal = notification_stream_state(db, user_id)
        preview = notification_preview(db, user_id) if unread_count else None
        return {"unread_count": unread_count, "signal": signal, "preview": preview}


@router.get("/stream")
async def stream_notifications(
    since_signal: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(current_user),
):
    deadline = asyncio.get_running_loop().time() + STREAM_TIMEOUT_SECONDS
    latest: dict = {"unread_count": 0, "signal": 0, "preview": None}
    while True:
        latest = await run_in_threadpool(_stream_snapshot, user["id"])
        if latest["signal"] > since_signal or asyncio.get_running_loop().time() >= deadline:
            return latest
        await asyncio.sleep(STREAM_CHECK_SECONDS)


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), user: CurrentUser = Depends(current_user)):
    count, signal = notification_stream_state(db, user["id"])
    return {"unread_count": count, "signal": signal}


@router.get("")
def get_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    only_unread: bool = False,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    items, total = list_notifications(db, user["id"], limit, offset, only_unread)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/read-all")
def read_all_notifications(db: Session = Depends(get_db), user: CurrentUser = Depends(current_user)):
    updated = mark_all_notifications_read(db, user["id"])
    db.commit()
    return {"updated": updated}


@router.post("/{notification_id}/read")
def read_notification(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
):
    updated = mark_notification_read(db, user["id"], notification_id)
    db.commit()
    return {"updated": updated}

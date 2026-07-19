"""Barrido periódico e idempotente de recordatorios de notificaciones."""
import logging
import threading

from app.core.config import settings
from app.core.database import SessionLocal
from app.repositories import sweep_reminders

logger = logging.getLogger(__name__)
_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _run() -> None:
    while not _stop_event.wait(settings.notification_reminder_interval_seconds):
        with SessionLocal() as db:
            try:
                bumped = sweep_reminders(
                    db, settings.notification_max_reminders, settings.notification_reminder_window_seconds
                )
                db.commit()
                if bumped:
                    logger.info("Recordatorios enviados: %s", len(bumped))
            except Exception:
                db.rollback()
                logger.exception("Falló el barrido de recordatorios")


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_run, name="notification-reminders", daemon=True)
    _thread.start()


def stop() -> None:
    global _thread
    _stop_event.set()
    if _thread:
        _thread.join(timeout=5)
    _thread = None

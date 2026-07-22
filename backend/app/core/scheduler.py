"""In-process round scheduler.

Rounds are independent I/O-bound units of work (HTTP calls to the LLM), so a
small fixed pool of worker threads is enough to run several in parallel
without adding a message broker. Each worker owns its own DB session — same
pattern classify.py already uses for parallel LLM batches within a round.
"""
import logging
import queue
import threading
import uuid

from app.core.config import settings
from app.core.database import SessionLocal
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_queue: "queue.Queue[uuid.UUID | None]" = queue.Queue()
_workers: list[threading.Thread] = []

# Segunda barrera contra procesar la misma ronda dos veces en paralelo (la
# primera es el UPDATE ... WHERE status <> 'processing' en el router) — cubre
# el caso de dos worker threads sacando el mismo round_id de la cola antes de
# que el router alcance a marcarlo 'processing'. Sin esto, dos corridas
# concurrentes del mismo round_id lanzan cada una su propio set de threads
# por subproyecto y chocan en el mismo UPDATE mention_groups ... where id =
# any(:ids), produciendo deadlocks de Postgres.
_running: set[uuid.UUID] = set()
_running_lock = threading.Lock()


def _mark_round_failed(db: Session, round_id: uuid.UUID, message: str) -> None:
    """Deja la ronda y cualquier run colgado en un estado terminal 'failed'.

    Sin esto, una excepción en el worker dejaba la ronda en 'files_uploaded'
    y el run en 'running' para siempre — el frontend hace polling infinito.
    """
    try:
        db.execute(
            text("""
                update processing_runs pr
                set status = 'failed', finished_at = now(), error_message = :msg
                from subprojects sp
                where pr.subproject_id = sp.id and sp.round_id = :id and pr.status = 'running'
            """),
            {"id": round_id, "msg": message[:2000]},
        )
        db.execute(
            text("update rounds set status = 'failed', updated_at = now() where id = :id"),
            {"id": round_id},
        )
        db.commit()
    except Exception:
        db.rollback()


def _run_round(round_id: uuid.UUID) -> None:
    from app.pipeline import process_round
    from app.repositories import round_processing_blockers

    with _running_lock:
        if round_id in _running:
            logger.warning(
                "Ronda %s ya se está procesando en otro worker — se descarta este intento duplicado.",
                round_id,
            )
            return
        _running.add(round_id)

    db = SessionLocal()
    try:
        blockers = round_processing_blockers(db, round_id)
        if blockers:
            logger.warning(
                "Ronda %s no se procesa: %s", round_id, "; ".join(blockers)
            )
            return
        process_round(db, round_id)
    except Exception as exc:
        logger.exception("process_round falló para ronda %s", round_id)
        db.rollback()
        _mark_round_failed(db, round_id, str(exc))
    finally:
        db.close()
        with _running_lock:
            _running.discard(round_id)


def _worker_loop() -> None:
    while True:
        round_id = _queue.get()
        if round_id is None:
            _queue.task_done()
            return
        try:
            _run_round(round_id)
        finally:
            _queue.task_done()


def start() -> None:
    for _ in range(settings.round_parallel_workers):
        t = threading.Thread(target=_worker_loop, daemon=True)
        t.start()
        _workers.append(t)


def stop() -> None:
    for _ in _workers:
        _queue.put(None)
    for t in _workers:
        t.join(timeout=5)
    _workers.clear()


def submit(round_id: uuid.UUID) -> None:
    _queue.put(round_id)

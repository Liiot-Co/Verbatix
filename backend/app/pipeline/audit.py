"""Fase 5 — Auditoría. Orquesta la auditoría de un estudio en transacciones:
materializa una muestra global reproducible de lo codificado, registra las
revisiones del analista (correcto / reasignar / eliminar) y aprueba el cierre.

Molde: pipeline/resolution.py — misma convención de errores, locking optimista
con expected_status e idempotencia ante doble-submit.
"""
from __future__ import annotations

import hashlib
import math
import random
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories import (
    _current_codebook_id,
    assign_codes_to_verbatim,
    create_audit_code_review,
    create_audit_item,
    create_audit_session,
    create_code,
    deactivate_verbatim_codes,
    finalize_audit_session,
    get_audit_item,
    get_audit_session,
    get_audit_summary,
    get_coded_population,
    get_latest_processing_run,
    get_resolution_summary,
    get_round_audit_percentage,
    increment_review_corrections,
    log_action,
    refresh_audit_session_progress,
    set_run_random_seed,
    set_studio_status,
    set_verbatim_coding_status,
    update_audit_item_review,
)


class AuditConflict(Exception):
    """El item/sesión cambió de estado mientras se revisaba (last-write-wins con aviso)."""


class AuditPrecondition(Exception):
    """Falta una precondición de negocio: resolución incompleta o target no alcanzado."""


def select_sample(population: list[dict], pct: float, seed: int) -> list[dict]:
    """Muestra GLOBAL sobre toda la población codificada: n = ceil(total * pct/100).

    Determinista: ordena por sha256(verbatim_id:seed) — no por hash() de Python,
    que va salteado por proceso y rompería la reproducibilidad entre reinicios.
    Con pct==0 la muestra es vacía (auditoría trivialmente satisfecha); no se
    aplica "mínimo 1 por código": un código chico puede no salir sorteado y eso
    es el comportamiento correcto de un muestreo global.
    """
    if not population or pct <= 0:
        return []
    n = min(len(population), math.ceil(len(population) * pct / 100))

    def sample_key(item: dict) -> str:
        return hashlib.sha256(f"{item['verbatim_id']}:{seed}".encode()).hexdigest()

    return sorted(population, key=sample_key)[:n]


def start_audit_session(db: Session, studio_id: uuid.UUID, *, user_id, resample: bool = False) -> dict:
    """Crea o reanuda (idempotente) la sesión de auditoría del estudio.

    Reabrir no re-muestrea ni pierde progreso. Con resample=True y una sesión
    desactualizada (hubo un run del motor posterior al muestreo) se crea una
    sesión NUEVA anclada al último run — la vieja queda como constancia, nunca
    se borra en silencio.
    """
    exists = db.execute(
        text("select 1 from studio where id = :id"), {"id": studio_id}
    ).scalar()
    if not exists:
        raise LookupError("Estudio no existe")

    existing = get_audit_summary(db, studio_id)
    if existing and not (resample and existing["is_stale"] and existing["status"] != "approved"):
        return existing

    summary = get_resolution_summary(db, studio_id)
    if not summary["can_close"]:
        raise AuditPrecondition(
            f"Hay {summary['pending']} grupos sin resolver en el Centro de Resolución"
        )

    pct = get_round_audit_percentage(db, studio_id)
    if pct is None:
        raise LookupError("El estudio no tiene ronda con % de auditoría")

    # Semilla reproducible: la del último run; si el motor no la persistió, se
    # genera una acá y se guarda para que re-muestrear dé siempre lo mismo.
    run = get_latest_processing_run(db, studio_id)
    seed = run["random_seed"] if run else None
    if seed is None:
        seed = random.randint(1, 2**31 - 1)
        if run:
            set_run_random_seed(db, uuid.UUID(run["id"]), seed)

    population = get_coded_population(db, studio_id)
    sample = select_sample(population, pct, seed)

    session_id = create_audit_session(
        db, studio_id, run["id"] if run else None, pct, len(sample)
    )

    # La muestra es global; los audit_code_reviews son la capa de agrupación para
    # la UI. Cada verbatim muestreado se cuelga de su código PRIMARIO
    # (output_index=1) — colgarlo de todos duplicaría items y rompería
    # total_items == tamaño de la muestra. El snapshot igual guarda todos.
    by_code: dict[str, list[dict]] = {}
    for item in sample:
        primary = item["codes"][0]["code_id"]
        by_code.setdefault(str(primary), []).append(item)

    for code_id, items in by_code.items():
        review_id = create_audit_code_review(db, session_id, code_id, len(items))
        for item in items:
            create_audit_item(db, review_id, item["verbatim_id"], item["codes"])

    set_studio_status(db, studio_id, "audit_pending")
    log_action(
        db, user_id, studio_id, "audit_session", uuid.UUID(session_id), "audit:start",
        new_value={
            "target_percentage": pct, "total_items": len(sample),
            "population": len(population), "random_seed": seed,
            "processing_run_id": run["id"] if run else None,
        },
    )
    db.commit()
    return get_audit_summary(db, studio_id)


def review_item(
    db: Session,
    item_id: uuid.UUID,
    decision: dict,
    *,
    user_id,
    expected_status: str | None = None,
) -> dict:
    """Aplica una revisión sobre un item muestreado:

      correct  -> confirma lo que hizo el motor/resolución, no toca códigos
      reassign -> reemplaza los códigos activos del verbatim (source='audit_correction')
      remove   -> desactiva todas las asignaciones; el verbatim queda 'needs_review'
    """
    item = get_audit_item(db, item_id)
    if not item:
        raise LookupError("Item de auditoría no encontrado")
    if item["session_status"] == "approved":
        raise AuditConflict("La auditoría ya fue aprobada; no admite más revisiones")
    if expected_status is not None and item["status"] != expected_status:
        raise AuditConflict(
            f"El item cambió de estado ('{item['status']}') mientras se revisaba"
        )

    action = decision.get("action")
    comment = decision.get("comment")
    new_code_result = None

    if action == "correct":
        if item["status"] == "correct":
            # Doble-submit: no-op, no re-loguea ni re-cuenta.
            return {"item_id": item["id"], "status": "correct", "already_reviewed": True,
                    "new_code": None, "summary": get_audit_summary(db, item["studio_id"])}
        update_audit_item_review(db, item_id, "correct", comment, user_id)
        new_status = "correct"

    elif action == "reassign":
        code_ids = [uuid.UUID(c) for c in (decision.get("code_ids") or [])]
        new_code = decision.get("new_code")
        if new_code:
            cb_id = _current_codebook_id(db, uuid.UUID(item["studio_id"]))
            if not cb_id:
                raise LookupError("Estudio no tiene codebook")
            new_code_result = create_code(db, cb_id, new_code["label"], new_code.get("net_id"), user_id)
            code_ids.append(uuid.UUID(new_code_result["id"]))
        if not code_ids:
            raise ValueError("Reasignar requiere al menos un código (code_ids o new_code)")
        deactivate_verbatim_codes(db, uuid.UUID(item["verbatim_id"]))
        assign_codes_to_verbatim(db, uuid.UUID(item["verbatim_id"]), code_ids, user_id)
        set_verbatim_coding_status(db, uuid.UUID(item["verbatim_id"]), "manually_coded")
        update_audit_item_review(db, item_id, "reassigned", comment, user_id)
        # Una corrección por transición: re-revisar un item ya corregido no re-cuenta.
        if item["status"] != "reassigned":
            increment_review_corrections(db, item["review_id"])
        new_status = "reassigned"

    elif action == "remove":
        deactivate_verbatim_codes(db, uuid.UUID(item["verbatim_id"]))
        set_verbatim_coding_status(db, uuid.UUID(item["verbatim_id"]), "needs_review")
        update_audit_item_review(
            db, item_id, "reassigned",
            comment or "Asignación eliminada en auditoría", user_id,
        )
        if item["status"] != "reassigned":
            increment_review_corrections(db, item["review_id"])
        new_status = "reassigned"

    else:
        raise ValueError(f"Acción inválida: {action!r}")

    progress = refresh_audit_session_progress(db, item["session_id"])
    log_action(
        db, user_id, uuid.UUID(item["studio_id"]), "audit_item", item_id, f"audit:{action}",
        old_value={"status": item["status"], "codes_snapshot": item["codes_snapshot"]},
        new_value={
            "status": new_status,
            "code_ids": decision.get("code_ids") or [],
            "new_code": new_code_result,
            "comment": comment,
        },
    )
    db.commit()

    return {
        "item_id": item["id"],
        "status": new_status,
        "already_reviewed": False,
        "new_code": new_code_result,
        "summary": {**get_audit_summary(db, item["studio_id"]), **progress},
    }


def update_item(
    db: Session,
    item_id: uuid.UUID,
    *,
    user_id,
    comment: str | None = None,
    status: str | None = None,
) -> dict:
    """Edita comentario y/o estado (pending/correct) sin tocar códigos — para
    'reassigned' está review_item, que sí muta verbatim_codes."""
    item = get_audit_item(db, item_id)
    if not item:
        raise LookupError("Item de auditoría no encontrado")
    if item["session_status"] == "approved":
        raise AuditConflict("La auditoría ya fue aprobada; no admite más cambios")
    if status is not None and status not in ("pending", "correct"):
        raise ValueError("status solo admite 'pending' o 'correct' — usá review para reasignar")

    update_audit_item_review(db, item_id, status or item["status"], comment, user_id)
    refresh_audit_session_progress(db, item["session_id"])
    log_action(
        db, user_id, uuid.UUID(item["studio_id"]), "audit_item", item_id, "audit:edit",
        old_value={"status": item["status"], "comment": item["comment"]},
        new_value={"status": status or item["status"], "comment": comment},
    )
    db.commit()
    return {"item_id": item["id"], "status": status or item["status"], "comment": comment}


def approve_session(db: Session, studio_id: uuid.UUID, *, user_id) -> dict:
    """Cierra la auditoría: exige target_met (o muestra vacía) y deja el estudio
    en 'audit_approved' — el estado que el dashboard futuro leerá como "Auditado"."""
    session = get_audit_session(db, studio_id)
    if not session:
        raise LookupError("El estudio no tiene sesión de auditoría")
    if session["status"] == "approved":
        return {**get_audit_summary(db, studio_id), "already_approved": True}

    if session["reviewed_items"] < session["total_items"]:
        raise AuditPrecondition(
            f"Faltan {session['total_items'] - session['reviewed_items']} items por revisar "
            f"({session['reviewed_items']}/{session['total_items']})"
        )

    finalize_audit_session(db, session["id"], user_id)
    set_studio_status(db, studio_id, "audit_approved")
    log_action(
        db, user_id, studio_id, "audit_session", uuid.UUID(session["id"]), "audit:approve",
        old_value={"status": session["status"]},
        new_value={"status": "approved", "reviewed_items": session["reviewed_items"],
                   "total_items": session["total_items"]},
    )
    db.commit()
    return {**get_audit_summary(db, studio_id), "already_approved": False}

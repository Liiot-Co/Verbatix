"""Fase 5 — Auditoría. Orquesta la auditoría de una ronda en transacciones:
materializa una muestra global reproducible de lo codificado, registra las
revisiones del analista (correcto / reasignar / eliminar) y aprueba el cierre.

Molde: pipeline/resolution.py — misma convención de errores, locking optimista
con expected_status e idempotencia ante doble-submit.
"""
from __future__ import annotations

import hashlib
import logging
import math
import random
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories import (
    approve_scratch_codebooks_for_round,
    assign_codes_to_group,
    create_audit_code_review,
    create_audit_item,
    create_audit_session,
    create_code,
    deactivate_group_codes,
    finalize_audit_session,
    get_audit_code_review,
    get_audit_item,
    get_audit_session,
    get_audit_summary,
    get_coded_population,
    get_latest_processing_run,
    get_resolution_summary,
    get_round_audit_percentage,
    increment_review_corrections,
    log_action,
    mark_audit_group_items_reassigned,
    mark_group_resolved,
    mark_review_items_correct,
    refresh_audit_session_progress,
    reopen_group_after_audit,
    set_code_review_result,
    set_run_random_seed,
    set_round_status,
    update_audit_item_review,
)
from app.services.notifications import emit
from app.repositories import global_admin_ids, project_supervisor_ids

logger = logging.getLogger(__name__)


class AuditConflict(Exception):
    """El item/sesión cambió de estado mientras se revisaba (last-write-wins con aviso)."""


class AuditPrecondition(Exception):
    """Falta una precondición de negocio: resolución incompleta o target no alcanzado."""


def _subproject_context(db: Session, subproject_id: uuid.UUID) -> dict | None:
    """round_id + codebook_id del subproyecto — audit_logs.round_id no bajó de
    nivel en la migración v8 (a diferencia de audit_sessions/processing_runs),
    así que loggear una acción de auditoría necesita resolverlo aparte."""
    row = db.execute(
        text("select round_id, codebook_id from subprojects where id = :id"),
        {"id": subproject_id},
    ).mappings().first()
    return dict(row) if row else None


def select_sample(population: list[dict], pct: float, seed: int) -> list[dict]:
    """Muestra estratificada reproducible: n = ceil(total * pct/100).

    Determinista: ordena por sha256(verbatim_id:seed) — no por hash() de Python,
    que va salteado por proceso y rompería la reproducibilidad entre reinicios.
    Con pct==0 la muestra es vacía (auditoría trivialmente satisfecha); no se
    Intercala código primario, fuente y banda de confianza. Así un código/fuente
    minoritario puede entrar antes que el segundo caso de un estrato masivo, sin
    aumentar el porcentaje pactado.
    """
    if not population or pct <= 0:
        return []
    n = min(len(population), math.ceil(len(population) * pct / 100))

    def sample_key(item: dict) -> str:
        return hashlib.sha256(f"{item['verbatim_id']}:{seed}".encode()).hexdigest()

    def confidence_band(value) -> str:
        if value is None:
            return "unknown"
        score = float(value)
        if score >= 0.95:
            return "very_high"
        if score >= 0.8:
            return "high"
        return "review_priority"

    strata: dict[tuple[str, str, str], list[dict]] = {}
    for item in population:
        primary = item["codes"][0]
        key = (
            str(primary["code_id"]),
            str(primary.get("source") or "unknown"),
            confidence_band(primary.get("confidence_score")),
        )
        strata.setdefault(key, []).append(item)

    for items in strata.values():
        items.sort(key=sample_key)
    ordered_keys = sorted(
        strata,
        key=lambda key: hashlib.sha256(f"{key}:{seed}".encode()).hexdigest(),
    )

    mandatory = sorted(
        [item for item in population if item.get("high_risk")],
        key=sample_key,
    )
    selected: list[dict] = list(mandatory)
    selected_ids = {item["verbatim_id"] for item in selected}
    target = max(n, len(selected))
    depth = 0
    while len(selected) < target:
        advanced = False
        for key in ordered_keys:
            if depth < len(strata[key]):
                advanced = True
                candidate = strata[key][depth]
                if candidate["verbatim_id"] not in selected_ids:
                    selected.append(candidate)
                    selected_ids.add(candidate["verbatim_id"])
                if len(selected) == target:
                    break
        if not advanced:
            break
        depth += 1
    return selected


def start_audit_session(db: Session, subproject_id: uuid.UUID, *, user_id, resample: bool = False) -> dict:
    """Crea o reanuda (idempotente) la sesión de auditoría del subproyecto.

    Reabrir no re-muestrea ni pierde progreso. Con resample=True y una sesión
    desactualizada (hubo un run del motor posterior al muestreo) se crea una
    sesión NUEVA anclada al último run — la vieja queda como constancia, nunca
    se borra en silencio.
    """
    ctx = _subproject_context(db, subproject_id)
    if not ctx:
        raise LookupError("Subproyecto no existe")
    round_id = ctx["round_id"]

    # React puede disparar dos bootstrap simultáneos (StrictMode, cambio de
    # pestaña o doble clic). El lock transaccional hace realmente idempotente la
    # creación: la segunda petición espera y luego reutiliza la sesión creada.
    db.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": str(subproject_id)},
    )

    # REQ-03: una sesión APROBADA pero desactualizada (llegó una carga nueva y el
    # motor volvió a correr) también admite re-muestreo — la sesión aprobada queda
    # como constancia histórica (superada) y la nueva muestrea el conjunto
    # combinado (viejo + nuevo). Sin resample, la sesión existente se reanuda.
    existing = get_audit_summary(db, subproject_id)
    if existing and not (resample and existing["is_stale"]):
        return existing

    summary = get_resolution_summary(db, subproject_id)
    if not summary["can_close"]:
        raise AuditPrecondition(
            f"Hay {summary['pending']} grupos sin resolver en el Centro de Resolución"
        )

    pct = get_round_audit_percentage(db, round_id)
    if pct is None:
        raise LookupError("La ronda no tiene % de auditoría configurado")

    # Semilla reproducible: la del último run; si el motor no la persistió, se
    # genera una acá y se guarda para que re-muestrear dé siempre lo mismo.
    run = get_latest_processing_run(db, subproject_id)
    seed = run["random_seed"] if run else None
    if seed is None:
        seed = random.randint(1, 2**31 - 1)
        if run:
            set_run_random_seed(db, uuid.UUID(run["id"]), seed)

    population = get_coded_population(db, subproject_id)
    sample = select_sample(population, pct, seed)

    session_id = create_audit_session(
        db, subproject_id, run["id"] if run else None, pct, len(sample)
    )

    # Los audit_code_reviews son la capa de agrupación para
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

    round_state = db.execute(
        text("select status, project_id from rounds where id = :id"), {"id": round_id}
    ).mappings().first()
    previous_round_status = round_state["status"] if round_state else None
    set_round_status(db, round_id, "audit_pending")
    log_action(
        db, user_id, round_id, "audit_session", uuid.UUID(session_id), "audit:start",
        new_value={
            "target_percentage": pct, "total_items": len(sample),
            "population": len(population), "random_seed": seed,
            "sample_strategy": "primary_code_source_confidence_round_robin_v1",
            "processing_run_id": run["id"] if run else None,
        },
    )
    db.commit()
    if previous_round_status != "audit_pending" and round_state:
        try:
            recipients = project_supervisor_ids(db, round_state["project_id"])
            if not recipients:
                recipients = global_admin_ids(db)
            recipients = [recipient for recipient in set(recipients) if recipient != user_id]
            emit(
                db,
                notification_type="ready_for_audit",
                title="Ronda lista para auditar",
                body="Un subproyecto ya está listo para su revisión de auditoría.",
                related_entity_id=round_id,
                user_ids=recipients,
                sender_id=user_id,
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("No se pudo emitir la notificación de auditoría pendiente")
    return get_audit_summary(db, subproject_id)


def review_item(
    db: Session,
    item_id: uuid.UUID,
    decision: dict,
    *,
    user_id,
    expected_status: str | None = None,
) -> dict:
    """Aplica una corrección sobre un item muestreado:

      reassign -> reemplaza los códigos activos del verbatim (source='audit_correction')
      remove   -> desactiva todas las asignaciones; el verbatim queda 'needs_review'

    No hay acción "correct" por item: el analista revisa POR SECCIÓN — corrige lo
    que esté mal y aprueba la sección (approve_code_review), que da por correctos
    los items sin corregir.
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
    group_id = uuid.UUID(item["mention_group_id"]) if item.get("mention_group_id") else None
    if group_id is None:
        raise AuditPrecondition("El verbatim auditado no pertenece a un mention_group")

    if action == "reassign":
        code_ids = [uuid.UUID(c) for c in (decision.get("code_ids") or [])]
        new_code = decision.get("new_code")
        if new_code:
            ctx = _subproject_context(db, uuid.UUID(item["subproject_id"]))
            cb_id = ctx["codebook_id"] if ctx else None
            if not cb_id:
                raise LookupError("Subproyecto no tiene codebook")
            new_code_result = create_code(db, cb_id, new_code["label"], new_code.get("net_id"), user_id)
            code_ids.append(uuid.UUID(new_code_result["id"]))
        if not code_ids:
            raise ValueError("Reasignar requiere al menos un código (code_ids o new_code)")
        deactivate_group_codes(db, group_id)
        affected_verbatims = assign_codes_to_group(
            db, group_id, code_ids, "audit_correction", user_id
        )
        mark_group_resolved(db, group_id, user_id)
        affected_items = mark_audit_group_items_reassigned(
            db, item["session_id"], group_id, comment, user_id
        )
        # Una corrección por transición: re-revisar un item ya corregido no re-cuenta.
        if item["status"] != "reassigned":
            increment_review_corrections(db, item["review_id"])
        new_status = "reassigned"

    elif action == "remove":
        deactivate_group_codes(db, group_id)
        affected_verbatims = reopen_group_after_audit(db, group_id)
        affected_items = mark_audit_group_items_reassigned(
            db, item["session_id"], group_id,
            comment or "Asignación de grupo eliminada en auditoría", user_id,
        )
        if item["status"] != "reassigned":
            increment_review_corrections(db, item["review_id"])
        new_status = "reassigned"

    else:
        raise ValueError(f"Acción inválida: {action!r}")

    progress = refresh_audit_session_progress(db, item["session_id"])
    subproject_id = uuid.UUID(item["subproject_id"])
    ctx = _subproject_context(db, subproject_id)
    log_action(
        db, user_id, ctx["round_id"], "audit_item", item_id, f"audit:{action}",
        old_value={"status": item["status"], "codes_snapshot": item["codes_snapshot"]},
        new_value={
            "status": new_status,
            "code_ids": decision.get("code_ids") or [],
            "new_code": new_code_result,
            "comment": comment,
            "mention_group_id": str(group_id),
            "affected_verbatims": affected_verbatims,
            "affected_audit_items": affected_items,
        },
    )
    db.commit()

    return {
        "item_id": item["id"],
        "status": new_status,
        "already_reviewed": False,
        "new_code": new_code_result,
        "mention_group_id": str(group_id),
        "affected_verbatims": affected_verbatims,
        "affected_audit_items": affected_items,
        "summary": {**get_audit_summary(db, subproject_id), **progress},
    }


def update_item(
    db: Session,
    item_id: uuid.UUID,
    *,
    user_id,
    comment: str | None = None,
) -> dict:
    """Edita el comentario sin tocar códigos ni estado — las correcciones van por
    review_item y el "dar por correcto" ocurre al aprobar la sección."""
    item = get_audit_item(db, item_id)
    if not item:
        raise LookupError("Item de auditoría no encontrado")
    if item["session_status"] == "approved":
        raise AuditConflict("La auditoría ya fue aprobada; no admite más cambios")

    update_audit_item_review(db, item_id, item["status"], comment, user_id)
    ctx = _subproject_context(db, uuid.UUID(item["subproject_id"]))
    log_action(
        db, user_id, ctx["round_id"], "audit_item", item_id, "audit:edit",
        old_value={"comment": item["comment"]},
        new_value={"comment": comment},
    )
    db.commit()
    return {"item_id": item["id"], "status": item["status"], "comment": comment}


def approve_code_review(db: Session, review_id: uuid.UUID, *, user_id) -> dict:
    """Aprueba una SECCIÓN (un código de la muestra): da por correctos los items
    que el analista no corrigió y cierra la sección como 'approved' o
    'with_corrections'. Es la unidad de revisión — no se marca verbatim por verbatim."""
    review = get_audit_code_review(db, review_id)
    if not review:
        raise LookupError("Sección de auditoría no encontrada")
    if review["session_status"] == "approved":
        raise AuditConflict("La auditoría ya fue aprobada; no admite más revisiones")

    subproject_id = uuid.UUID(review["subproject_id"])
    if review["status"] != "pending" and review["pending_items"] == 0:
        # Doble-submit: la sección ya estaba cerrada.
        return {
            "review_id": review["id"], "status": review["status"],
            "items_marked": 0, "already_approved": True,
            "summary": get_audit_summary(db, subproject_id),
        }

    marked = mark_review_items_correct(db, review_id, user_id)
    status = set_code_review_result(db, review_id, user_id)
    progress = refresh_audit_session_progress(db, review["session_id"])
    ctx = _subproject_context(db, subproject_id)
    log_action(
        db, user_id, ctx["round_id"], "audit_code_review", review_id,
        "audit:approve_section",
        old_value={"status": review["status"], "pending_items": review["pending_items"]},
        new_value={"status": status, "items_marked": marked},
    )
    db.commit()

    return {
        "review_id": review["id"],
        "status": status,
        "items_marked": marked,
        "already_approved": False,
        "summary": {**get_audit_summary(db, subproject_id), **progress},
    }


def approve_session(db: Session, subproject_id: uuid.UUID, *, user_id) -> dict:
    """Cierra la auditoría: exige target_met (o muestra vacía) y deja la ronda
    en 'audit_approved' — el estado que el dashboard futuro leerá como "Auditado"."""
    session = get_audit_session(db, subproject_id)
    if not session:
        raise LookupError("El subproyecto no tiene sesión de auditoría")
    if session["status"] == "approved":
        return {**get_audit_summary(db, subproject_id), "already_approved": True}

    if session["reviewed_items"] < session["total_items"]:
        raise AuditPrecondition(
            f"Faltan {session['total_items'] - session['reviewed_items']} items por revisar "
            f"({session['reviewed_items']}/{session['total_items']})"
        )

    ctx = _subproject_context(db, subproject_id)
    previous_round_status = db.execute(
        text("select status from rounds where id = :id"), {"id": ctx["round_id"]}
    ).scalar()
    finalize_audit_session(db, session["id"], user_id)
    set_round_status(db, ctx["round_id"], "audit_approved")
    current_round_status = db.execute(
        text("select status from rounds where id = :id"), {"id": ctx["round_id"]}
    ).scalar()
    approve_scratch_codebooks_for_round(db, ctx["round_id"], user_id)
    log_action(
        db, user_id, ctx["round_id"], "audit_session", uuid.UUID(session["id"]), "audit:approve",
        old_value={"status": session["status"]},
        new_value={"status": "approved", "reviewed_items": session["reviewed_items"],
                   "total_items": session["total_items"]},
    )
    db.commit()
    if previous_round_status != "audit_approved" and current_round_status == "audit_approved":
        try:
            recipients = [recipient for recipient in set(global_admin_ids(db)) if recipient != user_id]
            emit(
                db,
                notification_type="audit_approved",
                title="Auditoría de ronda aprobada",
                body="La auditoría completa de una ronda fue aprobada.",
                related_entity_id=ctx["round_id"],
                user_ids=recipients,
                sender_id=user_id,
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("No se pudo emitir la notificación de auditoría aprobada")
    return {**get_audit_summary(db, subproject_id), "already_approved": False}

"""Fase 4 — Centro de Resolución. Orquesta la resolución de un mention_group en una
transacción: crea código si corresponde, (re)asigna, marca resuelto y audita.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories import (
    add_alias_from_group,
    add_negative_alias_from_group,
    assign_codes_to_group,
    create_code,
    deactivate_group_codes,
    get_group_detail,
    list_codebook_codes,
    log_action,
    mark_group_resolved,
)


class ResolutionConflict(Exception):
    """El grupo cambió de estado mientras se resolvía (last-write-wins con aviso)."""


class BelowThresholdError(Exception):
    """El grupo no supera min_mentions_threshold: no se puede crear un código nuevo para él."""


def _subproject_context(db: Session, subproject_id: uuid.UUID) -> dict | None:
    """round_id + codebook_id del subproyecto — audit_logs.round_id no bajó de
    nivel en la migración v8, así que loggear una acción necesita resolverlo aparte."""
    row = db.execute(
        text("select codebook_id, round_id, coding_type from subprojects where id = :id"),
        {"id": subproject_id},
    ).mappings().first()
    return dict(row) if row else None


def resolve_group(
    db: Session,
    subproject_id: uuid.UUID,
    group_id: uuid.UUID,
    decision: dict,
    *,
    user_id,
    expected_status: str | None = None,
) -> dict:
    group = get_group_detail(db, group_id)
    if not group or group["subproject_id"] != str(subproject_id):
        raise LookupError("Grupo no encontrado")

    if group["status"] == "resolved":
        # Idempotente: un doble-submit o el motor reprocesando no debe reabrir/pisar un grupo ya resuelto.
        return {
            "group_id": str(group_id), "status": "resolved", "already_resolved": True,
            "codes_assigned": [], "verbatims_updated": 0, "new_code": None,
        }

    if expected_status is not None and group["status"] != expected_status:
        raise ResolutionConflict(
            f"El grupo cambió de estado ('{group['status']}') mientras se resolvía"
        )

    ctx = _subproject_context(db, subproject_id)
    if not ctx:
        raise LookupError("Subproyecto no existe")
    cb_id = ctx["codebook_id"]
    round_id = ctx["round_id"]

    action = decision.get("action")
    new_code_result = None
    is_system_target = False

    if action == "discard":
        discard = db.execute(
            text("""
                select id from codes
                 where codebook_id = :cb
                   and (
                     system_type = 'anomaly'
                     or (system_type is null and code_number = :n)
                   )
                 order by system_type nulls last
                 limit 1
            """),
            {"cb": cb_id, "n": settings.discard_code_number},
        ).mappings().first()
        if discard:
            code_ids = [discard["id"]]
            is_system_target = True
        elif settings.allow_pure_discard:
            code_ids = []
        else:
            raise LookupError("Código de descarte no configurado en el codebook")
        source = "analyst_manual"
    elif action == "approve":
        code_ids = [uuid.UUID(c) for c in (decision.get("code_ids") or [])]
        new_code = decision.get("new_code")
        if new_code:
            # resolve_group solo lo llama un analista autenticado. El mínimo de
            # menciones es regla del motor (bootstrap/fuzzy), no de Resolución:
            # aquí se puede crear "El Artesano" con 1 mención tras confirmar en UI.
            new_code_result = create_code(db, cb_id, new_code["label"], new_code.get("net_id"), user_id)
            code_ids.append(uuid.UUID(new_code_result["id"]))
        source = "analyst_manual"
    else:
        raise ValueError(f"Acción inválida: {action!r}")

    should_add_alias = (
        action == "approve" and decision.get("add_alias")
        and not is_system_target and bool(code_ids)
    )
    if should_add_alias and not add_alias_from_group(db, cb_id, code_ids[0], group):
        db.execute(
            text("update mention_groups set status = 'conflict' where id = :id"),
            {"id": group_id},
        )
        db.execute(
            text("update verbatims set coding_status = 'conflict' where mention_group_id = :id"),
            {"id": group_id},
        )
        log_action(
            db, user_id, round_id, "mention_group", group_id, "alias_conflict",
            old_value={"status": group["status"]},
            new_value={"status": "conflict", "code_id": str(code_ids[0])},
        )
        db.commit()
        raise ResolutionConflict(
            "El texto contradice un alias aprobado de otro código; quedó en conflicto para adjudicación"
        )

    deactivate_group_codes(db, group_id)

    # REQ-08: código único es por Marcas/Razones (subproject), no por pregunta.
    from app.pipeline.question_controls import assert_single_code_assignment
    single_code = bool(db.execute(
        text("select single_code_per_response from subprojects where id = :sp"),
        {"sp": subproject_id},
    ).scalar())
    if code_ids:
        code_meta = db.execute(
            text("""
                select id, is_system from codes where id = any(:ids)
            """),
            {"ids": list(code_ids)},
        ).mappings().all()
        by_id = {row["id"]: dict(row) for row in code_meta}
        ordered = [by_id[cid] for cid in code_ids if cid in by_id]
        assert_single_code_assignment(ordered, single_code=single_code)

    verbatims_updated = assign_codes_to_group(db, group_id, code_ids, source, user_id) if code_ids else 0

    if action == "approve" and code_ids:
        # Una marca nueva propuesta por el motor en una ronda heredada
        # (discover_new_brands) nace 'pending'. Confirmar una mención suya la
        # aprueba: así la propuesta se materializa por decisión humana, sin dejar
        # códigos 'pending' huérfanos en un libro ya aprobado. Solo afecta códigos
        # no-sistema que el humano asignó explícitamente.
        db.execute(
            text("""
                update codes
                   set approval_status = 'approved',
                       created_by = coalesce(created_by, :user)
                 where id = any(:ids)
                   and approval_status = 'pending'
                   and coalesce(is_system, false) = false
            """),
            {"ids": list(code_ids), "user": user_id},
        )

    if action == "approve" and ctx["coding_type"] == "reasons" and len(code_ids) == 1:
        # Solo una decisión humana inequívoca alimenta el caché aprobado. Un
        # texto multi-idea no se duplica como ejemplo de cada código.
        from app.pipeline.semantic.cache import write as write_reason_example
        write_reason_example(
            db, str(code_ids[0]), group.get("sample_text") or group["normalized_text"], 1.0,
            approval_status="approved", source="human_resolution",
        )

    suggested = group.get("suggested_code") or {}
    suggested_id = suggested.get("id")
    if suggested_id:
        rejected_id = uuid.UUID(suggested_id)
        if rejected_id not in code_ids:
            add_negative_alias_from_group(
                db, cb_id, rejected_id, group, user_id,
            )

    similar_suggestions = []
    if should_add_alias:
        similar_suggestions = _suggest_similar_pending_groups(db, subproject_id, group)

    mark_group_resolved(db, group_id, user_id)

    log_action(
        db, user_id, round_id, "mention_group", group_id, f"resolve:{action}",
        old_value={"status": group["status"]},
        new_value={"status": "resolved", "code_ids": [str(c) for c in code_ids]},
    )
    db.commit()

    codes_by_id = {c["id"]: c for c in list_codebook_codes(db, cb_id, include_system=True)}
    codes_assigned = [codes_by_id[str(c)] for c in code_ids if str(c) in codes_by_id]

    return {
        "group_id": str(group_id),
        "status": "resolved",
        "already_resolved": False,
        "codes_assigned": codes_assigned,
        "verbatims_updated": verbatims_updated,
        "new_code": new_code_result,
        # Compatibilidad de respuesta: ya no se autocierra ningún grupo por
        # WRatio. Los parecidos se ofrecen aparte para confirmación agrupada.
        "auto_resolved_groups": [],
        "similar_suggestions": similar_suggestions,
    }

def _suggest_similar_pending_groups(db, subproject_id, reference_group):
    from rapidfuzz import fuzz
    from app.pipeline.fuzzy.models import SCORE_THRESHOLD, SHORT_TEXT_EXACT_MAX_LEN

    new_alias = reference_group.get("normalized_text")
    if not new_alias:
        return []

    # below_threshold incluido: menciones insuficientes de la misma marca ("pia monte")
    # se consolidan al clasificar una manualmente ("Piamonte").
    pending = db.execute(
        text("""SELECT id, normalized_text, status FROM mention_groups
                WHERE subproject_id = :sp AND status IN ('pending_review', 'below_threshold')"""),
        {"sp": subproject_id}
    ).mappings().all()

    suggestions = []
    for p_group in pending:
        text_norm = p_group["normalized_text"]
        if not text_norm:
            continue

        if len(text_norm) <= SHORT_TEXT_EXACT_MAX_LEN or len(new_alias) <= SHORT_TEXT_EXACT_MAX_LEN:
            score = 100.0 if text_norm == new_alias else 0.0
        else:
            score = fuzz.WRatio(text_norm, new_alias)

        if score >= SCORE_THRESHOLD:
            suggestions.append({
                "id": str(p_group["id"]),
                "normalized_text": text_norm,
                "status": p_group["status"],
                "score": score,
            })

    return suggestions

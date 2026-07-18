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
        text("select codebook_id, round_id from subprojects where id = :id"),
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
            text("select id from codes where codebook_id = :cb and code_number = :n"),
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
            new_code_result = create_code(db, cb_id, new_code["label"], new_code.get("net_id"), user_id)
            code_ids.append(uuid.UUID(new_code_result["id"]))
        source = "analyst_manual"
    else:
        raise ValueError(f"Acción inválida: {action!r}")

    deactivate_group_codes(db, group_id)
    verbatims_updated = assign_codes_to_group(db, group_id, code_ids, source, user_id) if code_ids else 0

    auto_resolved = []
    if action == "approve" and decision.get("add_alias") and not is_system_target and code_ids:
        add_alias_from_group(db, cb_id, code_ids[0], group)
        auto_resolved = _auto_resolve_similar_pending_groups(db, subproject_id, round_id, code_ids[0], group, user_id)

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
        "auto_resolved_groups": auto_resolved,
    }

def _auto_resolve_similar_pending_groups(db, subproject_id, round_id, code_id, reference_group, user_id):
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

    auto_resolved = []
    for p_group in pending:
        text_norm = p_group["normalized_text"]
        if not text_norm:
            continue

        if len(text_norm) <= SHORT_TEXT_EXACT_MAX_LEN or len(new_alias) <= SHORT_TEXT_EXACT_MAX_LEN:
            score = 100.0 if text_norm == new_alias else 0.0
        else:
            score = fuzz.WRatio(text_norm, new_alias)

        if score >= SCORE_THRESHOLD:
            pid = p_group["id"]
            deactivate_group_codes(db, pid)
            assign_codes_to_group(db, pid, [code_id], "analyst_manual", user_id)
            mark_group_resolved(db, pid, user_id)

            log_action(
                db, user_id, round_id, "mention_group", pid, "resolve:approve:auto_fuzzy",
                old_value={"status": p_group["status"]},
                new_value={"status": "resolved", "code_ids": [str(code_id)], "score": score, "matched_alias": new_alias},
            )
            auto_resolved.append({"id": str(pid), "normalized_text": text_norm})

    return auto_resolved

"""REQ-05 — Perfil de referencia pactado vs data a procesar.

Cruce por unión: Respondent ID (Serial) **o** realid presentes en el Excel
de perfil. Modos:
  - combinado (coding_type NULL): un Excel; exclusión global del encuestado
  - por tipo (brands|reasons): Excel acotado; exclusión solo desengancha
    verbatims de ese subproyecto
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.ingest import excel
from app.repositories import log_action

_SERIAL_ALIASES = ("respondent id", "respondent_id", "serial")
_REALID_ALIASES = ("realid", "real id")
_COMPLETION_ALIASES = ("completion indicator", "completion_indicator", "completion")


class ProfileFormatError(ValueError):
    """El Excel de perfil no trae Respondent ID ni realid (u otra requerida)."""


def _norm_header(name: object) -> str:
    return str(name or "").strip().lower()


def _find_col(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    by_low = {_norm_header(c): c for c in columns if c}
    for alias in aliases:
        if alias in by_low:
            return by_low[alias]
    return None


def _cell_str(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def parse_profile_rows(
    content: bytes,
    sheet: str | None = None,
) -> tuple[str, list[dict]]:
    """Lee el Excel de perfil. Requiere Respondent ID y/o realid.

    Devuelve (sheet_usada, filas) con:
      respondent_external_id, realid, completion_indicator, quotas
    """
    sheets = excel.detect_sheets(content)
    if not sheets:
        raise ProfileFormatError("El archivo de perfil no tiene hojas")
    sheet_name = sheet or sheets[0]["name"]
    try:
        columns, rows = excel.read_rows(content, sheet_name)
    except KeyError as exc:
        raise ProfileFormatError(f"Hoja no encontrada: {sheet_name}") from exc

    serial_col = _find_col(columns, _SERIAL_ALIASES)
    realid_col = _find_col(columns, _REALID_ALIASES)
    if not serial_col and not realid_col:
        raise ProfileFormatError(
            "El perfil debe traer 'Respondent ID' (o Serial) y/o 'realid'. "
            "No se adivina el mapeo en silencio."
        )
    completion_col = _find_col(columns, _COMPLETION_ALIASES)
    known = {c for c in (serial_col, realid_col, completion_col) if c}

    parsed: list[dict] = []
    for row in rows:
        serial = _cell_str(row.get(serial_col)) if serial_col else None
        realid = _cell_str(row.get(realid_col)) if realid_col else None
        if not serial and not realid:
            continue
        quotas: dict[str, str] = {}
        for k, v in row.items():
            if not k or k in known:
                continue
            if v is None or str(v).strip() == "":
                continue
            quotas[str(k)] = str(v).strip()
        parsed.append({
            "respondent_external_id": serial,
            "realid": realid,
            "completion_indicator": (
                _cell_str(row.get(completion_col)) if completion_col else None
            ),
            "quotas": quotas or None,
        })
    if not parsed:
        raise ProfileFormatError(
            "El perfil no tiene filas con Respondent ID o realid válido"
        )
    return sheet_name, parsed


def get_latest_profile_file_id(db: Session, round_id: uuid.UUID) -> uuid.UUID | None:
    """Perfil más reciente de la ronda (cualquier coding_type)."""
    return db.execute(
        text("""
            select id from profile_files
             where round_id = :round
             order by created_at desc
             limit 1
        """),
        {"round": round_id},
    ).scalar()


def resolve_profile_targets(db: Session, round_id: uuid.UUID) -> dict:
    """Activos según el modo del upload más reciente.

    Returns:
      mode: None | 'combined' | 'split'
      combined_id: uuid | None
      by_type: {brands?: uuid, reasons?: uuid}
    """
    rows = db.execute(
        text("""
            select id, coding_type, created_at
              from profile_files
             where round_id = :round
             order by created_at desc
        """),
        {"round": round_id},
    ).mappings().all()
    if not rows:
        return {"mode": None, "combined_id": None, "by_type": {}}

    latest = rows[0]
    if latest["coding_type"] is None:
        return {
            "mode": "combined",
            "combined_id": latest["id"],
            "by_type": {},
        }

    by_type: dict[str, uuid.UUID] = {}
    for row in rows:
        ct = row["coding_type"]
        if ct in ("brands", "reasons") and ct not in by_type:
            by_type[ct] = row["id"]
    return {"mode": "split", "combined_id": None, "by_type": by_type}


def save_profile_file(
    db: Session,
    *,
    round_id: uuid.UUID,
    original_filename: str,
    storage_path: str | None,
    entries: list[dict],
    uploaded_by,
    coding_type: str | None = None,
) -> dict:
    """Persiste profile_files + profile_entries. No borra perfiles previos."""
    if coding_type is not None and coding_type not in ("brands", "reasons"):
        raise ValueError(f"coding_type inválido: {coding_type!r}")

    profile_id = uuid.uuid4()
    db.execute(
        text("""
            insert into profile_files
              (id, round_id, original_filename, storage_path, total_rows,
               uploaded_by, coding_type)
            values (:id, :round, :name, :path, :rows, :user, :ct)
        """),
        {
            "id": profile_id,
            "round": round_id,
            "name": original_filename,
            "path": storage_path,
            "rows": len(entries),
            "user": uploaded_by,
            "ct": coding_type,
        },
    )
    for entry in entries:
        db.execute(
            text("""
                insert into profile_entries
                  (id, profile_file_id, respondent_external_id, realid,
                   completion_indicator, quotas)
                values (:id, :file, :serial, :realid, :comp, cast(:quotas as jsonb))
            """),
            {
                "id": uuid.uuid4(),
                "file": profile_id,
                "serial": entry.get("respondent_external_id"),
                "realid": entry.get("realid"),
                "comp": entry.get("completion_indicator"),
                "quotas": json.dumps(entry.get("quotas")) if entry.get("quotas") else None,
            },
        )
    serials = {
        e["respondent_external_id"] for e in entries if e.get("respondent_external_id")
    }
    return {
        "profile_file_id": str(profile_id),
        "original_filename": original_filename,
        "total_rows": len(entries),
        "expected_respondents": len(entries),
        "coding_type": coding_type,
        "match_keys": len(serials | {e["realid"] for e in entries if e.get("realid")}),
    }


def profile_id_sets(db: Session, profile_file_id: uuid.UUID) -> tuple[set[str], set[str]]:
    rows = db.execute(
        text("""
            select respondent_external_id, realid from profile_entries
             where profile_file_id = :file
        """),
        {"file": profile_file_id},
    ).mappings().all()
    serials = {
        str(r["respondent_external_id"]).strip()
        for r in rows
        if r["respondent_external_id"] and str(r["respondent_external_id"]).strip()
    }
    realids = {
        str(r["realid"]).strip()
        for r in rows
        if r["realid"] and str(r["realid"]).strip()
    }
    return serials, realids


def profile_serial_set(db: Session, profile_file_id: uuid.UUID) -> set[str]:
    """Compat: solo serials (tests / callers antiguos)."""
    serials, _ = profile_id_sets(db, profile_file_id)
    return serials


def _respondents_for_file(
    db: Session,
    *,
    round_id: uuid.UUID,
    imported_file_id: uuid.UUID,
    coding_type: str | None = None,
) -> list:
    """Encuestados de la carga. Si coding_type, solo con verbatims de ese tipo."""
    if coding_type is None:
        return list(db.execute(
            text("""
                select id, respondent_external_id, realid, profile_status
                  from respondents
                 where round_id = :round
                   and imported_file_id = :file
            """),
            {"round": round_id, "file": imported_file_id},
        ).mappings().all())

    return list(db.execute(
        text("""
            select distinct r.id, r.respondent_external_id, r.realid, r.profile_status
              from respondents r
              join verbatims v on v.respondent_id = r.id
              join subprojects sp on sp.id = v.subproject_id
             where r.round_id = :round
               and r.imported_file_id = :file
               and sp.coding_type = :ct
               and sp.round_id = :round
        """),
        {"round": round_id, "file": imported_file_id, "ct": coding_type},
    ).mappings().all())


def _subproject_id_for_type(
    db: Session, round_id: uuid.UUID, coding_type: str,
) -> uuid.UUID | None:
    return db.execute(
        text("""
            select id from subprojects
             where round_id = :round and coding_type = :ct
        """),
        {"round": round_id, "ct": coding_type},
    ).scalar()


def _in_profile(serial: str, realid: str | None, serials: set[str], realids: set[str]) -> bool:
    if serial and serial in serials:
        return True
    if realid and realid in realids:
        return True
    return False


def _match_one_profile(
    db: Session,
    *,
    round_id: uuid.UUID,
    imported_file_id: uuid.UUID,
    profile_file_id: uuid.UUID,
    coding_type: str | None,
) -> dict:
    serials, realids = profile_id_sets(db, profile_file_id)
    expected = db.execute(
        text("select count(*) from profile_entries where profile_file_id = :file"),
        {"file": profile_file_id},
    ).scalar() or 0
    respondents = _respondents_for_file(
        db,
        round_id=round_id,
        imported_file_id=imported_file_id,
        coding_type=coding_type,
    )
    arrived = len(respondents)
    candidates: list[dict] = []

    for resp in respondents:
        serial = str(resp["respondent_external_id"] or "").strip()
        realid = str(resp["realid"]).strip() if resp["realid"] else None
        if resp["profile_status"] == "excluded_confirmed" and coding_type is None:
            continue

        existing = db.execute(
            text("""
                select id, status, detail from import_review_flags
                 where imported_file_id = :file
                   and respondent_id = :resp
                   and flag_type = 'not_in_profile'
                 order by created_at desc
                 limit 1
            """),
            {"file": imported_file_id, "resp": resp["id"]},
        ).mappings().first()

        # En modo split, el flag debe ser del mismo coding_type (detail).
        if existing and coding_type is not None:
            raw = existing["detail"]
            detail_obj = raw if isinstance(raw, dict) else json.loads(raw or "{}")
            if detail_obj.get("coding_type") not in (None, coding_type):
                # Flag de otro tipo: buscar uno del tipo actual
                existing = None
                typed = db.execute(
                    text("""
                        select id, status, detail from import_review_flags
                         where imported_file_id = :file
                           and respondent_id = :resp
                           and flag_type = 'not_in_profile'
                           and detail->>'coding_type' = :ct
                         order by created_at desc
                         limit 1
                    """),
                    {"file": imported_file_id, "resp": resp["id"], "ct": coding_type},
                ).mappings().first()
                existing = typed

        if existing and existing["status"] == "approved_keep":
            continue
        if existing and existing["status"] == "approved_remove":
            continue

        if _in_profile(serial, realid, serials, realids):
            if coding_type is None and resp["profile_status"] != "matched":
                db.execute(
                    text("update respondents set profile_status = 'matched' where id = :id"),
                    {"id": resp["id"]},
                )
            continue

        if coding_type is None:
            db.execute(
                text("update respondents set profile_status = 'not_in_profile' where id = :id"),
                {"id": resp["id"]},
            )

        detail = {
            "serial": serial,
            "realid": realid,
            "profile_file_id": str(profile_file_id),
            "match_key": "serial_or_realid",
            "coding_type": coding_type,
        }
        if existing and existing["status"] == "pending":
            flag_id = existing["id"]
        else:
            flag_id = uuid.uuid4()
            db.execute(
                text("""
                    insert into import_review_flags
                      (id, imported_file_id, respondent_id, flag_type, detail, status)
                    values (:id, :file, :resp, 'not_in_profile', cast(:detail as jsonb), 'pending')
                """),
                {
                    "id": flag_id,
                    "file": imported_file_id,
                    "resp": resp["id"],
                    "detail": json.dumps(detail),
                },
            )

        candidates.append({
            "flag_id": str(flag_id),
            "status": "pending",
            "serial": serial or None,
            "realid": realid,
            "respondent_id": str(resp["id"]),
            "coding_type": coding_type,
        })

    pending = db.execute(
        text("""
            select count(*) from import_review_flags
             where imported_file_id = :file
               and flag_type = 'not_in_profile'
               and status = 'pending'
        """),
        {"file": imported_file_id},
    ).scalar() or 0

    return {
        "has_profile": True,
        "profile_file_id": str(profile_file_id),
        "coding_type": coding_type,
        "expected": expected,
        "arrived": arrived,
        "extra": len(candidates),
        "candidates": candidates,
        "pending_flags": pending,
        "summary": (
            f"El perfil tiene {expected} esperados; "
            f"en la data llegaron {arrived}; "
            f"sobran {len(candidates)}."
        ),
    }


def match_file_against_profile(
    db: Session,
    *,
    round_id: uuid.UUID,
    imported_file_id: uuid.UUID,
    profile_file_id: uuid.UUID | None = None,
) -> dict:
    """Cruza encuestados de UNA carga vs perfil(es) activos.

    Sin perfil → no-op. Con profile_file_id → solo ese archivo.
    Sin id → según resolve_profile_targets (combinado o split).
    """
    if profile_file_id is not None:
        row = db.execute(
            text("select coding_type from profile_files where id = :id"),
            {"id": profile_file_id},
        ).mappings().first()
        ct = row["coding_type"] if row else None
        return _match_one_profile(
            db,
            round_id=round_id,
            imported_file_id=imported_file_id,
            profile_file_id=profile_file_id,
            coding_type=ct,
        )

    targets = resolve_profile_targets(db, round_id)
    if not targets["mode"]:
        return {
            "has_profile": False,
            "expected": 0,
            "arrived": 0,
            "extra": 0,
            "candidates": [],
            "pending_flags": 0,
            "mode": None,
        }

    if targets["mode"] == "combined":
        result = _match_one_profile(
            db,
            round_id=round_id,
            imported_file_id=imported_file_id,
            profile_file_id=targets["combined_id"],
            coding_type=None,
        )
        result["mode"] = "combined"
        return result

    # split: acumular candidatos de cada tipo presente
    all_candidates: list[dict] = []
    expected = arrived = 0
    parts = []
    for ct, pid in targets["by_type"].items():
        part = _match_one_profile(
            db,
            round_id=round_id,
            imported_file_id=imported_file_id,
            profile_file_id=pid,
            coding_type=ct,
        )
        parts.append(part)
        all_candidates.extend(part["candidates"])
        expected += part["expected"]
        arrived += part["arrived"]

    pending = db.execute(
        text("""
            select count(*) from import_review_flags
             where imported_file_id = :file
               and flag_type = 'not_in_profile'
               and status = 'pending'
        """),
        {"file": imported_file_id},
    ).scalar() or 0

    return {
        "has_profile": bool(targets["by_type"]),
        "mode": "split",
        "by_type": {ct: str(pid) for ct, pid in targets["by_type"].items()},
        "expected": expected,
        "arrived": arrived,
        "extra": len(all_candidates),
        "candidates": all_candidates,
        "pending_flags": pending,
        "parts": parts,
        "summary": (
            f"Perfiles por tipo: {expected} esperados (suma); "
            f"llegaron {arrived}; sobran {len(all_candidates)}."
        ),
    }


def _unlink_verbatims(
    db: Session,
    *,
    respondent_ids: list,
    imported_file_id: uuid.UUID,
    coding_type: str | None,
    round_id: uuid.UUID | None = None,
) -> None:
    if not respondent_ids:
        return
    if coding_type is None:
        db.execute(
            text("""
                update verbatims
                   set mention_group_id = null
                 where respondent_id = any(:resps)
                   and imported_file_id = :file
            """),
            {"resps": respondent_ids, "file": imported_file_id},
        )
        return

    sp_id = _subproject_id_for_type(db, round_id, coding_type) if round_id else None
    if sp_id is None and round_id is not None:
        return
    if sp_id is not None:
        db.execute(
            text("""
                update verbatims
                   set mention_group_id = null
                 where respondent_id = any(:resps)
                   and imported_file_id = :file
                   and subproject_id = :sp
            """),
            {"resps": respondent_ids, "file": imported_file_id, "sp": sp_id},
        )
    else:
        db.execute(
            text("""
                update verbatims v
                   set mention_group_id = null
                  from subprojects sp
                 where v.subproject_id = sp.id
                   and sp.coding_type = :ct
                   and v.respondent_id = any(:resps)
                   and v.imported_file_id = :file
            """),
            {"resps": respondent_ids, "file": imported_file_id, "ct": coding_type},
        )


def resolve_profile_flag(
    db: Session,
    flag_id: uuid.UUID,
    action: str,
    *,
    user_id,
    note: str | None = None,
) -> dict:
    """keep → approved_keep; remove → exclusión (global o tipada)."""
    flag = db.execute(
        text("""
            select f.id, f.status, f.respondent_id, f.detail, f.imported_file_id,
                   i.round_id
              from import_review_flags f
              join imported_files i on i.id = f.imported_file_id
             where f.id = :id and f.flag_type = 'not_in_profile'
        """),
        {"id": flag_id},
    ).mappings().first()
    if not flag:
        raise LookupError("Flag de perfil no encontrado")
    if flag["status"] != "pending":
        return {
            "flag_id": str(flag_id),
            "status": flag["status"],
            "already_resolved": True,
            "pending_flags": _count_all_pending(db, flag["imported_file_id"]),
        }

    raw = flag["detail"]
    detail = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    coding_type = detail.get("coding_type")

    if action == "keep":
        new_status = "approved_keep"
    elif action == "remove":
        new_status = "approved_remove"
        if coding_type is None:
            db.execute(
                text("""
                    update respondents
                       set profile_status = 'excluded_confirmed'
                     where id = :id
                """),
                {"id": flag["respondent_id"]},
            )
        _unlink_verbatims(
            db,
            respondent_ids=[flag["respondent_id"]],
            imported_file_id=flag["imported_file_id"],
            coding_type=coding_type,
            round_id=flag["round_id"],
        )
    else:
        raise ValueError(
            f"Acción inválida para perfil: {action!r} (usa keep o remove)"
        )

    if note:
        detail["note"] = note
        db.execute(
            text(
                "update import_review_flags set detail = cast(:detail as jsonb) where id = :id"
            ),
            {"detail": json.dumps(detail), "id": flag_id},
        )

    db.execute(
        text("""
            update import_review_flags
               set status = :st, reviewed_by = :u, reviewed_at = now()
             where id = :id
        """),
        {"st": new_status, "u": user_id, "id": flag_id},
    )
    log_action(
        db, user_id, flag["round_id"], "import_review_flag", flag_id,
        f"profile_review:{action}",
        old_value={"status": "pending"},
        new_value={"status": new_status, "note": note, "coding_type": coding_type},
    )
    db.commit()
    return {
        "flag_id": str(flag_id),
        "status": new_status,
        "already_resolved": False,
        "pending_flags": _count_all_pending(db, flag["imported_file_id"]),
    }


def resolve_profile_flags_bulk(
    db: Session,
    flag_ids: list[uuid.UUID],
    action: str,
    *,
    user_id,
) -> dict:
    if action not in ("keep", "remove"):
        raise ValueError(f"Acción inválida para perfil: {action!r} (usa keep o remove)")
    if not flag_ids:
        return {
            "resolved": 0,
            "status": "approved_keep" if action == "keep" else "approved_remove",
            "flag_ids": [],
            "pending_flags": 0,
            "round_id": None,
            "file_id": None,
        }

    flags = db.execute(
        text("""
            select f.id, f.respondent_id, f.imported_file_id, f.detail, i.round_id
              from import_review_flags f
              join imported_files i on i.id = f.imported_file_id
             where f.id = any(:ids)
               and f.flag_type = 'not_in_profile'
               and f.status = 'pending'
        """),
        {"ids": list(flag_ids)},
    ).mappings().all()

    if not flags:
        sample = db.execute(
            text("""
                select f.imported_file_id as file_id, i.round_id
                  from import_review_flags f
                  join imported_files i on i.id = f.imported_file_id
                 where f.id = any(:ids)
                 limit 1
            """),
            {"ids": list(flag_ids)},
        ).mappings().first()
        pending = _count_all_pending(db, sample["file_id"]) if sample else 0
        return {
            "resolved": 0,
            "status": "approved_keep" if action == "keep" else "approved_remove",
            "flag_ids": [],
            "pending_flags": pending,
            "round_id": sample["round_id"] if sample else None,
            "file_id": sample["file_id"] if sample else None,
            "already_resolved": True,
        }

    file_ids = {row["imported_file_id"] for row in flags}
    if len(file_ids) > 1:
        raise ValueError("Los flags de perfil deben ser de la misma carga")

    file_id = flags[0]["imported_file_id"]
    round_id = flags[0]["round_id"]
    ids = [row["id"] for row in flags]
    new_status = "approved_keep" if action == "keep" else "approved_remove"

    if action == "remove":
        # Agrupar por coding_type del detail (None = global)
        by_ct: dict[str | None, list] = {}
        for row in flags:
            raw = row["detail"]
            detail = raw if isinstance(raw, dict) else json.loads(raw or "{}")
            ct = detail.get("coding_type")
            by_ct.setdefault(ct, []).append(row["respondent_id"])

        for ct, resp_ids in by_ct.items():
            if ct is None:
                db.execute(
                    text("""
                        update respondents
                           set profile_status = 'excluded_confirmed'
                         where id = any(:ids)
                    """),
                    {"ids": resp_ids},
                )
            _unlink_verbatims(
                db,
                respondent_ids=resp_ids,
                imported_file_id=file_id,
                coding_type=ct,
                round_id=round_id,
            )

    db.execute(
        text("""
            update import_review_flags
               set status = :st, reviewed_by = :u, reviewed_at = now()
             where id = any(:ids) and status = 'pending'
        """),
        {"st": new_status, "u": user_id, "ids": ids},
    )
    log_action(
        db, user_id, round_id, "import_review_flag", ids[0],
        f"profile_review_bulk:{action}",
        old_value={"status": "pending", "count": len(ids)},
        new_value={"status": new_status, "count": len(ids)},
    )
    db.commit()
    return {
        "resolved": len(ids),
        "status": new_status,
        "flag_ids": [str(i) for i in ids],
        "pending_flags": _count_all_pending(db, file_id),
        "round_id": round_id,
        "file_id": file_id,
        "already_resolved": False,
    }


def resolve_all_pending_profile_flags(
    db: Session,
    *,
    round_id: uuid.UUID,
    imported_file_id: uuid.UUID,
    action: str,
    user_id,
) -> dict:
    if action not in ("keep", "remove"):
        raise ValueError(f"Acción inválida para perfil: {action!r} (usa keep o remove)")

    flag_ids = db.execute(
        text("""
            select f.id
              from import_review_flags f
              join imported_files i on i.id = f.imported_file_id
             where f.imported_file_id = :file
               and i.round_id = :round
               and f.flag_type = 'not_in_profile'
               and f.status = 'pending'
        """),
        {"file": imported_file_id, "round": round_id},
    ).scalars().all()

    if not flag_ids:
        return {
            "resolved": 0,
            "status": "approved_keep" if action == "keep" else "approved_remove",
            "flag_ids": [],
            "pending_flags": _count_all_pending(db, imported_file_id),
            "round_id": round_id,
            "file_id": imported_file_id,
            "already_resolved": True,
        }

    return resolve_profile_flags_bulk(db, list(flag_ids), action, user_id=user_id)


def _count_all_pending(db: Session, file_id: uuid.UUID) -> int:
    return db.execute(
        text("""
            select count(*) from import_review_flags
             where imported_file_id = :file and status = 'pending'
        """),
        {"file": file_id},
    ).scalar() or 0


def get_profile_summary(db: Session, round_id: uuid.UUID) -> dict | None:
    """Resumen del/los perfiles activos según el modo del más reciente."""
    targets = resolve_profile_targets(db, round_id)
    if not targets["mode"]:
        return None

    def _one(pid: uuid.UUID, coding_type: str | None) -> dict:
        row = db.execute(
            text("""
                select id, original_filename, total_rows, created_at, coding_type
                  from profile_files
                 where id = :id
            """),
            {"id": pid},
        ).mappings().first()
        serials, realids = profile_id_sets(db, pid)
        n_rows = db.execute(
            text("select count(*) from profile_entries where profile_file_id = :id"),
            {"id": pid},
        ).scalar() or 0
        return {
            "profile_file_id": str(row["id"]),
            "original_filename": row["original_filename"],
            "total_rows": row["total_rows"],
            "expected_respondents": n_rows,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "coding_type": coding_type,
            "match_keys": len(serials | realids),
        }

    if targets["mode"] == "combined":
        one = _one(targets["combined_id"], None)
        return {
            **one,
            "mode": "combined",
            "profiles": [one],
        }

    profiles = [
        _one(pid, ct) for ct, pid in sorted(targets["by_type"].items())
    ]
    return {
        "mode": "split",
        "profile_file_id": profiles[0]["profile_file_id"] if profiles else None,
        "original_filename": (
            " + ".join(p["original_filename"] for p in profiles) if profiles else None
        ),
        "total_rows": sum((p["total_rows"] or 0) for p in profiles),
        "expected_respondents": sum(p["expected_respondents"] for p in profiles),
        "created_at": profiles[0]["created_at"] if profiles else None,
        "coding_type": None,
        "profiles": profiles,
    }

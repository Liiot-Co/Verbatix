"""REQ-05 — Perfil de referencia pactado vs data a procesar.

Cruza por Respondent ID (`respondent_external_id` / Serial), NUNCA por `realid`
(eso es REQ-03/REQ-06: duplicados entre cargas). Los que están en la data pero
no en el perfil son candidatos a exclusión; el analista aprueba o mantiene —
nunca se borra el registro físicamente.
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.ingest import excel
from app.repositories import log_action

# Columnas conocidas del Excel de perfil (case-insensitive). El resto va a quotas.
_SERIAL_ALIASES = ("respondent id", "respondent_id", "serial")
_REALID_ALIASES = ("realid", "real id")
_COMPLETION_ALIASES = ("completion indicator", "completion_indicator", "completion")


class ProfileFormatError(ValueError):
    """El Excel de perfil no trae la columna Respondent ID (u otra requerida)."""


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
    """Lee el Excel de perfil con el importador genérico (`excel.read_rows`).

    Devuelve (sheet_usada, filas) donde cada fila tiene:
      respondent_external_id, realid, completion_indicator, quotas (dict)
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
    if not serial_col:
        raise ProfileFormatError(
            "El perfil debe traer la columna 'Respondent ID' "
            "(también acepta 'Serial'). No se adivina el mapeo en silencio."
        )
    realid_col = _find_col(columns, _REALID_ALIASES)
    completion_col = _find_col(columns, _COMPLETION_ALIASES)
    known = {c for c in (serial_col, realid_col, completion_col) if c}

    parsed: list[dict] = []
    for row in rows:
        serial = _cell_str(row.get(serial_col))
        if not serial:
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
            "realid": _cell_str(row.get(realid_col)) if realid_col else None,
            "completion_indicator": (
                _cell_str(row.get(completion_col)) if completion_col else None
            ),
            "quotas": quotas or None,
        })
    if not parsed:
        raise ProfileFormatError(
            "El perfil no tiene filas con Respondent ID válido"
        )
    return sheet_name, parsed


def get_latest_profile_file_id(db: Session, round_id: uuid.UUID) -> uuid.UUID | None:
    return db.execute(
        text("""
            select id from profile_files
             where round_id = :round
             order by created_at desc
             limit 1
        """),
        {"round": round_id},
    ).scalar()


def save_profile_file(
    db: Session,
    *,
    round_id: uuid.UUID,
    original_filename: str,
    storage_path: str | None,
    entries: list[dict],
    uploaded_by,
) -> dict:
    """Persiste profile_files + profile_entries. No borra perfiles previos
    (historial); el cruce usa siempre el más reciente."""
    profile_id = uuid.uuid4()
    db.execute(
        text("""
            insert into profile_files
              (id, round_id, original_filename, storage_path, total_rows, uploaded_by)
            values (:id, :round, :name, :path, :rows, :user)
        """),
        {
            "id": profile_id,
            "round": round_id,
            "name": original_filename,
            "path": storage_path,
            "rows": len(entries),
            "user": uploaded_by,
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
                "serial": entry["respondent_external_id"],
                "realid": entry.get("realid"),
                "comp": entry.get("completion_indicator"),
                "quotas": json.dumps(entry.get("quotas")) if entry.get("quotas") else None,
            },
        )
    return {
        "profile_file_id": str(profile_id),
        "original_filename": original_filename,
        "total_rows": len(entries),
        "expected_respondents": len({e["respondent_external_id"] for e in entries}),
    }


def profile_serial_set(db: Session, profile_file_id: uuid.UUID) -> set[str]:
    rows = db.execute(
        text("""
            select respondent_external_id from profile_entries
             where profile_file_id = :file
               and respondent_external_id is not null
               and respondent_external_id <> ''
        """),
        {"file": profile_file_id},
    ).scalars().all()
    return {str(s).strip() for s in rows if s}


def match_file_against_profile(
    db: Session,
    *,
    round_id: uuid.UUID,
    imported_file_id: uuid.UUID,
    profile_file_id: uuid.UUID | None = None,
) -> dict:
    """Cruza encuestados de UNA carga por Respondent ID vs el perfil.

    Sin perfil → no-op: deja profile_status en not_checked y resumen neutro.
    Con perfil → matched | not_in_profile + flags pending (idempotente).
    """
    pid = profile_file_id or get_latest_profile_file_id(db, round_id)
    if not pid:
        return {
            "has_profile": False,
            "expected": 0,
            "arrived": 0,
            "extra": 0,
            "candidates": [],
            "pending_flags": 0,
        }

    profile_serials = profile_serial_set(db, pid)
    expected = len(profile_serials)

    respondents = db.execute(
        text("""
            select id, respondent_external_id, realid, profile_status
              from respondents
             where round_id = :round
               and imported_file_id = :file
        """),
        {"round": round_id, "file": imported_file_id},
    ).mappings().all()

    arrived = len(respondents)
    candidates: list[dict] = []

    for resp in respondents:
        serial = str(resp["respondent_external_id"] or "").strip()
        if resp["profile_status"] == "excluded_confirmed":
            continue
        existing = db.execute(
            text("""
                select id, status from import_review_flags
                 where imported_file_id = :file
                   and respondent_id = :resp
                   and flag_type = 'not_in_profile'
                 order by created_at desc
                 limit 1
            """),
            {"file": imported_file_id, "resp": resp["id"]},
        ).mappings().first()
        if existing and existing["status"] == "approved_keep":
            continue
        if existing and existing["status"] == "approved_remove":
            continue

        if serial in profile_serials:
            if resp["profile_status"] != "matched":
                db.execute(
                    text("update respondents set profile_status = 'matched' where id = :id"),
                    {"id": resp["id"]},
                )
            continue

        # Candidato: Serial de la data NO está en el perfil (aunque realid
        # pudiera coincidir — el cruce es SOLO por Respondent ID).
        db.execute(
            text("update respondents set profile_status = 'not_in_profile' where id = :id"),
            {"id": resp["id"]},
        )
        detail = {
            "serial": serial,
            "realid": resp["realid"],
            "profile_file_id": str(pid),
            "match_key": "respondent_external_id",
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
            "serial": serial,
            "realid": resp["realid"],
            "respondent_id": str(resp["id"]),
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
        "profile_file_id": str(pid),
        "expected": expected,
        "arrived": arrived,
        "extra": pending,
        "candidates": candidates,
        "pending_flags": pending,
        "summary": (
            f"El perfil tiene {expected} esperados; "
            f"en la data llegaron {arrived}; "
            f"sobran {pending}."
        ),
    }


def resolve_profile_flag(
    db: Session,
    flag_id: uuid.UUID,
    action: str,
    *,
    user_id,
    note: str | None = None,
) -> dict:
    """Decisión humana sobre candidato a exclusión (REQ-05).

      keep   -> se procesa con normalidad (approved_keep); registro intacto
      remove -> profile_status = excluded_confirmed; se desengancha de grupos
                de mención pero NO se borra el encuestado ni sus verbatims
    """
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

    if action == "keep":
        new_status = "approved_keep"
    elif action == "remove":
        new_status = "approved_remove"
        db.execute(
            text("""
                update respondents
                   set profile_status = 'excluded_confirmed'
                 where id = :id
            """),
            {"id": flag["respondent_id"]},
        )
        # Desenganchar de grupos sin borrar verbatims (regla dura REQ-05).
        db.execute(
            text("""
                update verbatims
                   set mention_group_id = null
                 where respondent_id = :resp
                   and imported_file_id = :file
            """),
            {"resp": flag["respondent_id"], "file": flag["imported_file_id"]},
        )
    else:
        raise ValueError(
            f"Acción inválida para perfil: {action!r} (usa keep o remove)"
        )

    if note:
        raw = flag["detail"]
        detail = raw if isinstance(raw, dict) else json.loads(raw or "{}")
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
        new_value={"status": new_status, "note": note},
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
    """Resuelve muchos candidatos a exclusión en UNA transacción (REQ-05).

    keep   -> approved_keep para todos
    remove -> excluded_confirmed + desenganche de grupos (sin borrar filas)
    """
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
            select f.id, f.respondent_id, f.imported_file_id, i.round_id
              from import_review_flags f
              join imported_files i on i.id = f.imported_file_id
             where f.id = any(:ids)
               and f.flag_type = 'not_in_profile'
               and f.status = 'pending'
        """),
        {"ids": list(flag_ids)},
    ).mappings().all()

    if not flags:
        # Ninguno pendiente: devolver conteo si el caller pasó ids conocidos.
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
    resp_ids = [row["respondent_id"] for row in flags]
    new_status = "approved_keep" if action == "keep" else "approved_remove"

    if action == "remove":
        db.execute(
            text("""
                update respondents
                   set profile_status = 'excluded_confirmed'
                 where id = any(:ids)
            """),
            {"ids": resp_ids},
        )
        db.execute(
            text("""
                update verbatims
                   set mention_group_id = null
                 where respondent_id = any(:resps)
                   and imported_file_id = :file
            """),
            {"resps": resp_ids, "file": file_id},
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
    """Excluir/mantener TODOS los pendientes de perfil de una carga — 1 query."""
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
    """Resumen del perfil más reciente de la ronda (para la UI)."""
    row = db.execute(
        text("""
            select id, original_filename, total_rows, created_at
              from profile_files
             where round_id = :round
             order by created_at desc
             limit 1
        """),
        {"round": round_id},
    ).mappings().first()
    if not row:
        return None
    expected = db.execute(
        text("""
            select count(distinct respondent_external_id)
              from profile_entries
             where profile_file_id = :id
               and respondent_external_id is not null
               and respondent_external_id <> ''
        """),
        {"id": row["id"]},
    ).scalar() or 0
    return {
        "profile_file_id": str(row["id"]),
        "original_filename": row["original_filename"],
        "total_rows": row["total_rows"],
        "expected_respondents": expected,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }

"""REQ-03 — Cargas múltiples sobre una ronda existente.

Compara una carga nueva contra lo ya importado en la misma ronda y alimenta la
cola de aprobación humana (`import_review_flags`):

  - mismo `realid` en otra carga  -> posible duplicado real (flag 'pending';
    la fila SÍ se inserta — nada queda flotando fuera de una tabla con estado,
    el analista decide después: mantener / quitar / editar).
  - mismo Serial con otro realid  -> aviso informativo, NO bloqueante (dos
    plataformas numeran desde 1; son personas distintas). No se persiste flag.

Molde: pipeline/resolution.py — SQL explícito con text(), errores tipados,
transacción por operación.
"""
from __future__ import annotations

import json
import re
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.ingest import dau, excel
from app.repositories import log_action


class ImportReviewConflict(Exception):
    """El flag cambió de estado mientras se resolvía (doble submit)."""


def suggest_source_label(filename: str) -> str:
    """Etiqueta por defecto de la carga: nombre de archivo limpio, sin extensión.
    El analista puede editarla en la pantalla de confirmación antes de importar."""
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename or "").strip()
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or "Carga"


def field_metadata_for_dau(records: list[dict[str, str]], n: int = 5) -> list[dict]:
    """Metadata por campo de un `.dau` ya parseado, para el preview de selección
    de campos: sugerencia de coding_type (patrón NBS_UNAID/VYK) + muestra de
    valores. Excluye los mismos campos de infraestructura que `dau.parse_verbatims`."""
    from app.pipeline.question_controls import max_mentions_per_respondent

    fields = sorted({
        key for record in records for key in record
        if not key.startswith("##") and key not in dau._NON_RESPONSE_FIELDS
    })
    # Filas virtuales (una por registro×campo) para contar menciones REQ-04.
    virtual_rows: list[dict] = []
    for record in records:
        serial = record.get(dau._SERIAL_KEY) or record.get("realid") or ""
        for field in fields:
            value = record.get(field)
            if value:
                virtual_rows.append({
                    "respondent_external_id": serial,
                    "question_key": field,
                })
    out = []
    for field in fields:
        coding_type = dau.guess_coding_type(field)
        single_default = dau.guess_single_code_default(field)
        reason = (
            "coincide con plantilla conocida (NBS_UNAID/VYK)" if coding_type
            else "sin patrón conocido, requiere clasificación manual"
        )
        out.append({
            "field": field,
            "suggested_coding_type": coding_type,
            "suggested_single_code_per_response": single_default,
            "detected_max_mentions": max_mentions_per_respondent(virtual_rows, field),
            "reason": reason,
            "sample_values": dau.sample_values(records, field, n),
        })
    return out


def field_metadata_for_excel(rows: list[dict[str, object]], columns: list[str], n: int = 5) -> list[dict]:
    """Metadata por columna de una hoja de Excel ya leída: sin heurística de
    sugerencia (no hay patrón fiable de nombre de columna), solo muestra."""
    return [
        {
            "field": column,
            "suggested_coding_type": None,
            "suggested_single_code_per_response": None,
            "detected_max_mentions": 0,
            "reason": None,
            "sample_values": excel.sample_values(rows, column, n),
        }
        for column in columns
    ]


def find_checksum_duplicate(db: Session, round_id: uuid.UUID, checksum: str) -> dict | None:
    """Mismo archivo (sha256) ya subido en esta ronda — el caller avisa en la UI
    para que subir dos veces lo mismo nunca duplique en silencio."""
    row = db.execute(
        text("""
            select id, original_filename, source_label, status
            from imported_files
            where round_id = :round and checksum = :sum
            order by created_at
            limit 1
        """),
        {"round": round_id, "sum": checksum},
    ).mappings().first()
    if not row:
        return None
    return {
        "file_id": str(row["id"]),
        "original_filename": row["original_filename"],
        "source_label": row["source_label"],
        "status": row["status"],
    }


def round_has_previous_load(db: Session, round_id: uuid.UUID, file_id: uuid.UUID) -> bool:
    """¿Esta ronda ya tenía otra carga de verbatims validada? (define si el
    import actual es "primera carga" — flujo intacto — o "carga adicional")."""
    return bool(db.execute(
        text("""
            select 1 from imported_files
            where round_id = :round and id <> :file
              and status = 'validated'
              and file_type in ('verbatims_xlsx', 'combined_xlsx', 'dau')
            limit 1
        """),
        {"round": round_id, "file": file_id},
    ).scalar())


def analyze_new_load(db: Session, round_id: uuid.UUID, file_id: uuid.UUID) -> dict:
    """Compara los encuestados de la carga `file_id` contra las cargas previas
    de la ronda. Crea flags 'possible_duplicate' (idempotente por respondent) y
    devuelve las dos secciones de revisión. NO comitea — corre dentro de la
    transacción del import."""
    # Duplicado real: mismo realid en otra carga de la misma ronda.
    duplicate_rows = db.execute(
        text("""
            select nuevo.id as respondent_id,
                   nuevo.respondent_external_id as serial,
                   nuevo.realid,
                   previo.respondent_external_id as previous_serial,
                   coalesce(pf.source_label, pf.original_filename) as previous_source_label
            from respondents nuevo
            join respondents previo
              on previo.round_id = nuevo.round_id
             and previo.realid = nuevo.realid
             and previo.imported_file_id is distinct from nuevo.imported_file_id
            left join imported_files pf on pf.id = previo.imported_file_id
            where nuevo.round_id = :round
              and nuevo.imported_file_id = :file
              and nuevo.realid is not null and nuevo.realid <> ''
            order by nuevo.respondent_external_id
        """),
        {"round": round_id, "file": file_id},
    ).mappings().all()

    duplicates = []
    seen: dict[str, dict] = {}
    for row in duplicate_rows:
        rid = str(row["respondent_id"])
        entry = seen.get(rid)
        if entry is None:
            existing_flag = db.execute(
                text("""
                    select id, status from import_review_flags
                    where imported_file_id = :file and respondent_id = :resp
                      and flag_type = 'possible_duplicate'
                """),
                {"file": file_id, "resp": row["respondent_id"]},
            ).mappings().first()
            entry = {
                "flag_id": str(existing_flag["id"]) if existing_flag else None,
                "status": existing_flag["status"] if existing_flag else "pending",
                "serial": row["serial"],
                "realid": row["realid"],
                "matches": [],
            }
            seen[rid] = entry
            duplicates.append((row["respondent_id"], entry))
        entry["matches"].append({
            "serial": row["previous_serial"],
            "source_label": row["previous_source_label"] or "Carga original / sin registrar",
        })

    for respondent_id, entry in duplicates:
        if entry["flag_id"] is not None:
            continue  # re-import del mismo archivo (retry tras clasificar variables): no duplicar flags
        flag_id = uuid.uuid4()
        db.execute(
            text("""
                insert into import_review_flags (id, imported_file_id, respondent_id, flag_type, detail, status)
                values (:id, :file, :resp, 'possible_duplicate', cast(:detail as jsonb), 'pending')
            """),
            {
                "id": flag_id, "file": file_id, "resp": respondent_id,
                "detail": _json({"serial": entry["serial"], "realid": entry["realid"],
                                 "matches": entry["matches"]}),
            },
        )
        entry["flag_id"] = str(flag_id)

    # Serial repetido entre cargas con realid distinto: informativo, no bloquea
    # ni se persiste — el par (Serial, carga) ya lo desambigua source_label.
    collision_rows = db.execute(
        text("""
            select nuevo.respondent_external_id as serial,
                   nuevo.realid as new_realid,
                   previo.realid as previous_realid,
                   coalesce(pf.source_label, pf.original_filename) as previous_source_label
            from respondents nuevo
            join respondents previo
              on previo.round_id = nuevo.round_id
             and previo.respondent_external_id = nuevo.respondent_external_id
             and previo.imported_file_id is distinct from nuevo.imported_file_id
            left join imported_files pf on pf.id = previo.imported_file_id
            where nuevo.round_id = :round
              and nuevo.imported_file_id = :file
              and previo.realid is distinct from nuevo.realid
            order by nuevo.respondent_external_id
        """),
        {"round": round_id, "file": file_id},
    ).mappings().all()

    serial_collisions = [
        {
            "serial": row["serial"],
            "new_realid": row["new_realid"],
            "previous_realid": row["previous_realid"],
            "previous_source_label": row["previous_source_label"] or "Carga original / sin registrar",
        }
        for row in collision_rows
    ]

    return {
        "duplicates": [entry for _, entry in duplicates],
        "serial_collisions": serial_collisions,
    }


def get_load_review(db: Session, round_id: uuid.UUID, file_id: uuid.UUID) -> dict:
    """Estado actual de la cola de revisión de una carga (para retomar la
    pantalla sin re-importar): flags persistidos + avisos de Serial recomputados."""
    flags = db.execute(
        text("""
            select f.id, f.status, f.detail, f.flag_type,
                   r.respondent_external_id as serial, r.realid
            from import_review_flags f
            left join respondents r on r.id = f.respondent_id
            where f.imported_file_id = :file
            order by f.created_at
        """),
        {"file": file_id},
    ).mappings().all()

    duplicates = []
    for row in flags:
        if row["flag_type"] != "possible_duplicate":
            continue
        detail = _load_detail(row["detail"])
        duplicates.append({
            "flag_id": str(row["id"]),
            "status": row["status"],
            "serial": row["serial"] or detail.get("serial"),
            "realid": row["realid"] or detail.get("realid"),
            "matches": detail.get("matches", []),
        })

    # Los avisos de Serial no se persisten: se recomputan con la misma consulta.
    serial_collisions = db.execute(
        text("""
            select nuevo.respondent_external_id as serial,
                   nuevo.realid as new_realid,
                   previo.realid as previous_realid,
                   coalesce(pf.source_label, pf.original_filename) as previous_source_label
            from respondents nuevo
            join respondents previo
              on previo.round_id = nuevo.round_id
             and previo.respondent_external_id = nuevo.respondent_external_id
             and previo.imported_file_id is distinct from nuevo.imported_file_id
            left join imported_files pf on pf.id = previo.imported_file_id
            where nuevo.round_id = :round
              and nuevo.imported_file_id = :file
              and previo.realid is distinct from nuevo.realid
            order by nuevo.respondent_external_id
        """),
        {"round": round_id, "file": file_id},
    ).mappings().all()

    pending = sum(1 for d in duplicates if d["status"] == "pending")
    return {
        "duplicates": duplicates,
        "serial_collisions": [
            {
                "serial": r["serial"],
                "new_realid": r["new_realid"],
                "previous_realid": r["previous_realid"],
                "previous_source_label": r["previous_source_label"] or "Carga original / sin registrar",
            }
            for r in serial_collisions
        ],
        "pending_flags": pending,
        "requires_review": pending > 0,
    }


def count_pending_flags(db: Session, file_id: uuid.UUID) -> int:
    return db.execute(
        text("""
            select count(*) from import_review_flags
            where imported_file_id = :file and status = 'pending'
        """),
        {"file": file_id},
    ).scalar() or 0


def resolve_flag(
    db: Session,
    flag_id: uuid.UUID,
    action: str,
    *,
    user_id,
    note: str | None = None,
) -> dict:
    """Decisión humana sobre un posible duplicado:

      keep   -> ambos registros se conservan (personas distintas o duplicado aceptado)
      remove -> se quitan los verbatims de la carga NUEVA para ese encuestado
                (aún sin codificar: el motor está bloqueado hasta resolver la cola);
                el flag conserva la constancia con el detalle y los textos.
      edit   -> se conserva, con nota del analista (status 'edited').

    El `realid` y el Serial NUNCA se modifican (regla dura de REQ-03).
    """
    flag = db.execute(
        text("""
            select f.id, f.status, f.respondent_id, f.detail, f.imported_file_id,
                   i.round_id
            from import_review_flags f
            join imported_files i on i.id = f.imported_file_id
            where f.id = :id and f.flag_type = 'possible_duplicate'
        """),
        {"id": flag_id},
    ).mappings().first()
    if not flag:
        raise LookupError("Flag de revisión no encontrado")
    if flag["status"] != "pending":
        return {
            "flag_id": str(flag_id),
            "status": flag["status"],
            "already_resolved": True,
            "pending_flags": count_pending_flags(db, flag["imported_file_id"]),
        }

    if action == "keep":
        new_status = "approved_keep"
    elif action == "edit":
        new_status = "edited"
    elif action == "remove":
        new_status = "approved_remove"
    else:
        raise ValueError(f"Acción inválida: {action!r}")

    removed_verbatims = 0
    if action == "remove":
        # Constancia antes de quitar: los textos quedan en el detail del flag.
        texts = db.execute(
            text("""
                select source_question_key, original_text from verbatims
                where respondent_id = :resp and imported_file_id = :file
            """),
            {"resp": flag["respondent_id"], "file": flag["imported_file_id"]},
        ).mappings().all()
        result = db.execute(
            text("""
                delete from verbatims
                where respondent_id = :resp and imported_file_id = :file
            """),
            {"resp": flag["respondent_id"], "file": flag["imported_file_id"]},
        )
        removed_verbatims = result.rowcount or 0
        detail = _load_detail(flag["detail"])
        detail["removed_verbatims"] = [
            {"question_key": t["source_question_key"], "original_text": t["original_text"]}
            for t in texts
        ]
        db.execute(
            text("update import_review_flags set detail = cast(:detail as jsonb) where id = :id"),
            {"detail": _json(detail), "id": flag_id},
        )

    if action == "edit" and note:
        detail = _load_detail(flag["detail"])
        detail["note"] = note
        db.execute(
            text("update import_review_flags set detail = cast(:detail as jsonb) where id = :id"),
            {"detail": _json(detail), "id": flag_id},
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
        f"import_review:{action}",
        old_value={"status": "pending"},
        new_value={"status": new_status, "removed_verbatims": removed_verbatims, "note": note},
    )
    db.commit()

    return {
        "flag_id": str(flag_id),
        "status": new_status,
        "already_resolved": False,
        "removed_verbatims": removed_verbatims,
        "pending_flags": count_pending_flags(db, flag["imported_file_id"]),
    }


def cleanup_orphan_groups(db: Session, round_id: uuid.UUID) -> int:
    """Tras quitar duplicados, los mention_groups pendientes cuyo único origen
    eran esos verbatims quedan vacíos: se limpian antes de disparar el motor.
    Solo toca grupos SIN resolver — un grupo resuelto jamás se borra."""
    result = db.execute(
        text("""
            delete from mention_groups mg
            using subprojects sp
            where sp.id = mg.subproject_id
              and sp.round_id = :round
              and mg.status in ('pending_review', 'below_threshold', 'anomaly')
              and not exists (select 1 from verbatims v where v.mention_group_id = mg.id)
        """),
        {"round": round_id},
    )
    return result.rowcount or 0


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load_detail(detail) -> dict:
    """El driver puede devolver jsonb ya deserializado (psycopg) o como str (SQLite en tests)."""
    if not detail:
        return {}
    if isinstance(detail, str):
        return json.loads(detail)
    return dict(detail)

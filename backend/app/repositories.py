"""Acceso a datos con SQL explícito (fuente de verdad: 001_schema_v8.sql)."""
import json
import uuid

import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.ingest.dau import guess_coding_type
from app.pipeline.normalize import normalize, rows_to_normalized_df

SYSTEM_CODES = [
    (95, "Menciones confusas/Incorrectas", "anomaly"),
    (96, "No sabe", "no_answer"),
    (97, "Otras menciones", "other_mentions"),
    (98, "Nada/Ninguna", "none"),
    (99, "No recuerda/No responde", "no_recall"),
]


# ── Notificaciones ────────────────────────────────────────────────────

def create_notifications(
    db: Session,
    user_ids: list[uuid.UUID],
    notification_type: str,
    title: str,
    body: str,
    related_entity_id: uuid.UUID | None,
    sender_id: uuid.UUID | None,
) -> int:
    """Inserta una audiencia completa en una sola sentencia PostgreSQL."""
    recipients = list(set(user_ids))
    if not recipients:
        return 0
    result = db.execute(
        text("""
            insert into notifications (id, user_id, type, title, body, related_entity_id, sender_id)
            select gen_random_uuid(), recipient_id, :type, :title, :body, :related_entity_id, :sender_id
            from unnest(cast(:user_ids as uuid[])) as recipient_id
        """),
        {
            "user_ids": recipients,
            "type": notification_type,
            "title": title,
            "body": body,
            "related_entity_id": related_entity_id,
            "sender_id": sender_id,
        },
    )
    return result.rowcount or len(recipients)


def list_notifications(
    db: Session, user_id: uuid.UUID, limit: int, offset: int, only_unread: bool = False
) -> tuple[list[dict], int]:
    where = "where n.user_id = :user_id and n.is_read = false" if only_unread else "where n.user_id = :user_id"
    rows = db.execute(
        text(f"""
            select n.id, n.type, n.title, n.body, n.related_entity_id, n.sender_id,
                   coalesce(nullif(btrim(sender.name), ''), sender.email) as sender_name,
                   n.is_read, n.created_at, n.last_reminded_at, n.reminder_count,
                   count(*) over() as total
            from notifications n
            left join users sender on sender.id = n.sender_id
            {where}
            order by n.created_at desc
            limit :limit offset :offset
        """),
        {"user_id": user_id, "limit": limit, "offset": offset},
    ).mappings().all()
    if rows:
        return [dict(row) for row in rows], int(rows[0]["total"])
    # Una página fuera del rango sigue reportando el total correcto para que la
    # UI pueda recuperar su paginación después de lecturas concurrentes.
    total = db.execute(
        text(f"select count(*) from notifications n {where}"), {"user_id": user_id}
    ).scalar()
    return [], int(total or 0)


def notification_stream_state(db: Session, user_id: uuid.UUID) -> tuple[int, int]:
    row = db.execute(
        text("""
            select count(*) filter (where not is_read) as unread_count,
                   coalesce(
                     (extract(epoch from max(greatest(created_at, coalesce(last_reminded_at, created_at)))
                       filter (where not is_read)) * 1000)::bigint,
                     0
                   ) as signal
            from notifications where user_id = :user_id
        """),
        {"user_id": user_id},
    ).mappings().one()
    return int(row["unread_count"] or 0), int(row["signal"] or 0)


def notification_preview(db: Session, user_id: uuid.UUID) -> dict | None:
    row = db.execute(
        text("""
            select n.id, n.type, n.title, n.body, n.related_entity_id, n.sender_id,
                   coalesce(nullif(btrim(sender.name), ''), sender.email) as sender_name,
                   n.is_read, n.created_at, n.last_reminded_at, n.reminder_count
            from notifications n
            left join users sender on sender.id = n.sender_id
            where n.user_id = :user_id and n.is_read = false
            order by greatest(n.created_at, coalesce(n.last_reminded_at, n.created_at)) desc, n.created_at desc
            limit 1
        """),
        {"user_id": user_id},
    ).mappings().first()
    return dict(row) if row else None


def mark_notification_read(db: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
    return bool(db.execute(
        text("""
            update notifications set is_read = true
            where id = :notification_id and user_id = :user_id and is_read = false
            returning id
        """),
        {"notification_id": notification_id, "user_id": user_id},
    ).scalar())


def mark_all_notifications_read(db: Session, user_id: uuid.UUID) -> int:
    result = db.execute(
        text("update notifications set is_read = true where user_id = :user_id and is_read = false"),
        {"user_id": user_id},
    )
    return result.rowcount or 0


def sweep_reminders(db: Session, max_reminders: int, window_seconds: int) -> list[dict]:
    """Hace un bump atómico; la cláusula WHERE lo vuelve seguro entre workers."""
    rows = db.execute(
        text("""
            update notifications
            set last_reminded_at = now(), reminder_count = reminder_count + 1
            where is_read = false
              and reminder_count < :max_reminders
              and now() - greatest(created_at, coalesce(last_reminded_at, created_at))
                    >= make_interval(secs => :window_seconds)
            returning id, user_id
        """),
        {"max_reminders": max_reminders, "window_seconds": window_seconds},
    ).mappings().all()
    return [dict(row) for row in rows]


def project_supervisor_ids(db: Session, project_id: uuid.UUID) -> list[uuid.UUID]:
    return list(db.execute(
        text("""
            select distinct a.user_id
            from assignments a join user_roles ur on ur.user_id = a.user_id
            where a.project_id = :project_id and a.status = 'active' and a.revoked_at is null
              and ur.role_code = 'supervisor'
        """),
        {"project_id": project_id},
    ).scalars().all())


def global_admin_ids(db: Session) -> list[uuid.UUID]:
    return list(db.execute(
        text("select distinct user_id from user_roles where role_code = 'admin'"),
    ).scalars().all())


def create_codebook(
    db: Session,
    project_id: uuid.UUID,
    coding_type: str,
    parent_codebook_id=None,
    *,
    origin: str = "scratch",
    status: str = "draft",
) -> uuid.UUID:
    """El codebook vive a nivel Estudio (project_id+coding_type), compartido entre
    categorías/rondas — una Ronda 2 puede heredar el mismo libro sin reprocesarlo."""
    cb_id = uuid.uuid4()
    version = db.execute(
        text("select coalesce(max(version), 0) + 1 from codebooks where project_id = :project and coding_type = :ct"),
        {"project": project_id, "ct": coding_type},
    ).scalar()
    db.execute(
        text("""
            insert into codebooks (
              id, project_id, coding_type, version, parent_codebook_id, origin, status
            )
            values (:id, :project, :ct, :v, :parent, :origin, :status)
        """),
        {
            "id": cb_id,
            "project": project_id,
            "ct": coding_type,
            "v": version,
            "parent": parent_codebook_id,
            "origin": origin,
            "status": status,
        },
    )
    return cb_id


def seed_system_codes(db: Session, codebook_id: uuid.UUID, *, overflow: bool = False) -> None:
    """Crea códigos técnicos una sola vez.

    Si el catálogo del cliente ocupa 95..99, los códigos Verbatix nacen
    directamente en 995..999; nunca se renumera una fila ya persistida.
    """
    for number, label, stype in SYSTEM_CODES:
        persisted_number = number + 900 if overflow else number
        db.execute(
            text("""
                insert into codes (
                  id, codebook_id, code_number, label, origin, is_system,
                  system_type, is_system_overflow, overflow_base_system_type
                )
                values (
                  :id, :cb, :n, :l, 'inherited', true,
                  :st, :overflow, :overflow_type
                )
                on conflict (codebook_id, code_number) do nothing
            """),
            {
                "id": uuid.uuid4(),
                "cb": codebook_id,
                "n": persisted_number,
                "l": label,
                "st": stype,
                "overflow": overflow,
                "overflow_type": stype if overflow else None,
            },
        )


def clone_codebook(
    db: Session, source_codebook_id: uuid.UUID, target_codebook_id: uuid.UUID
) -> dict:
    codes = db.execute(
        text("""
            insert into codes (id, codebook_id, code_number, label, origin, is_system,
                               system_type, inherited_from_code_id,
                               is_system_overflow, overflow_base_system_type)
            select gen_random_uuid(), :cb, code_number, label, 'inherited', is_system,
                   system_type, id, is_system_overflow, overflow_base_system_type
            from codes where codebook_id = :src and is_active
            returning id
        """),
        {"cb": target_codebook_id, "src": source_codebook_id},
    ).rowcount

    aliases = db.execute(
        text("""
            insert into code_aliases (id, codebook_id, code_id, alias_normalized,
                                      alias_sample, occurrences, origin)
            select gen_random_uuid(), :cb, nc.id, a.alias_normalized, a.alias_sample,
                   a.occurrences, 'inherited'
            from code_aliases a
            join codes oc on oc.id = a.code_id
            join codes nc on nc.codebook_id = :cb and nc.inherited_from_code_id = oc.id
            where a.codebook_id = :src
        """),
        {"cb": target_codebook_id, "src": source_codebook_id},
    ).rowcount

    nets = db.execute(
        text("""
            with new_nets as (
              insert into nets (id, codebook_id, name, origin, display_order)
              select gen_random_uuid(), :cb, name, 'engine_auto', display_order
              from nets where codebook_id = :src
              returning id, name
            )
            insert into net_codes (id, net_id, code_id)
            select gen_random_uuid(), nn.id, nc.id
            from net_codes onc
            join nets onet on onet.id = onc.net_id and onet.codebook_id = :src
            join new_nets nn on nn.name = onet.name
            join codes oc on oc.id = onc.code_id
            join codes nc on nc.codebook_id = :cb and nc.inherited_from_code_id = oc.id
        """),
        {"cb": target_codebook_id, "src": source_codebook_id},
    ).rowcount

    return {"codes": codes, "aliases": aliases, "nets": nets}


def insert_codebook_from_excel(
    db: Session,
    codebook_id: uuid.UUID,
    parsed: dict,
    *,
    imported_from_file_id: uuid.UUID,
    approved_by,
) -> dict:
    """Confirma un catálogo de cliente conservando sus números exactos."""
    numbers = [code["code_number"] for code in parsed["codes"]]
    if len(numbers) != len(set(numbers)):
        raise ValueError("El catálogo contiene números de código repetidos")
    if (
        any(95 <= number <= 99 for number in numbers)
        and any(995 <= number <= 999 for number in numbers)
    ):
        raise ValueError(
            "El catálogo ocupa simultáneamente 95–99 y 995–999; "
            "no hay un rango seguro para los códigos de sistema"
        )

    codebook = db.execute(
        text("select origin, status from codebooks where id = :id for update"),
        {"id": codebook_id},
    ).mappings().first()
    if not codebook or codebook["origin"] != "imported_client_catalog":
        raise ValueError("El subproyecto no fue configurado para importar un catálogo")

    existing_client_codes = db.execute(
        text("select count(*) from codes where codebook_id = :cb and not is_system"),
        {"cb": codebook_id},
    ).scalar()
    if existing_client_codes:
        raise ValueError("El catálogo del cliente ya fue importado")

    net_ids, n_alias = {}, 0
    for i, name in enumerate(parsed["nets"]):
        nid = uuid.uuid4()
        db.execute(
            text("""
                insert into nets (id, codebook_id, name, origin, display_order)
                values (:id, :cb, :n, 'analyst_manual', :o)
            """),
            {"id": nid, "cb": codebook_id, "n": name, "o": i},
        )
        net_ids[name] = nid

    for c in parsed["codes"]:
        cid = uuid.uuid4()
        db.execute(
            text("""
                insert into codes (id, codebook_id, code_number, label, origin, is_system, system_type)
                values (:id, :cb, :n, :l, 'imported_client', false, null)
            """),
            {
                "id": cid,
                "cb": codebook_id,
                "n": c["code_number"],
                "l": c["label"],
            },
        )

        real_id = cid

        if c["net"] and c["net"] in net_ids:
            db.execute(
                text("""
                    insert into net_codes (id, net_id, code_id)
                    values (:id, :n, :c)
                    on conflict (net_id, code_id) do nothing
                """),
                {"id": uuid.uuid4(), "n": net_ids[c["net"]], "c": real_id},
            )

        for a in c["aliases"]:
            norm = normalize(a["text"])
            if not norm:
                continue
            db.execute(
                text("""
                    insert into code_aliases (id, codebook_id, code_id, alias_normalized,
                                              alias_sample, occurrences, origin)
                    values (:id, :cb, :c, :norm, :sample, :occ, 'imported_xlsx')
                    on conflict (codebook_id, alias_normalized, code_id) do nothing
                """),
                {
                    "id": uuid.uuid4(),
                    "cb": codebook_id,
                    "c": real_id,
                    "norm": norm,
                    "sample": a["text"],
                    "occ": a["occurrences"],
                },
            )
            n_alias += 1

    overflow = any(95 <= number <= 99 for number in numbers)
    seed_system_codes(db, codebook_id, overflow=overflow)
    db.execute(
        text("""
            update codebooks
               set imported_from_file_id = :file,
                   status = 'approved',
                   approved_by = :user,
                   approved_at = now()
             where id = :cb
        """),
        {"file": imported_from_file_id, "user": approved_by, "cb": codebook_id},
    )
    return {
        "codes": len(parsed["codes"]),
        "aliases": n_alias,
        "nets": len(parsed["nets"]),
        "system_codes_overflow": overflow,
    }


def _resolve_question_id(db: Session, project_id: uuid.UUID, question_key: str | None) -> uuid.UUID | None:
    """Resuelve question_key (directo o vía question_aliases) a una fila ya clasificada
    de `questions`. None si la variable es nueva y todavía no se sabe si es Marcas o
    Razones (sección 2.5) — el caller debe tratarla como pendiente, no fallar."""
    if not question_key:
        return None
    direct = db.execute(
        text("select id from questions where project_id = :project and question_key = :qk"),
        {"project": project_id, "qk": question_key},
    ).scalar()
    if direct:
        return direct
    result = db.execute(
        text("""
            select q.id from questions q
            join question_aliases qa on qa.canonical_question_id = q.id
            where q.project_id = :project and qa.alias_key = :qk
        """),
        {"project": project_id, "qk": question_key},
    ).scalar()
    return result


def classify_question(
    db: Session,
    project_id: uuid.UUID,
    question_key: str,
    coding_type: str,
    single_code_per_response: bool = False,
    expected_max_mentions: int | None = None,
) -> uuid.UUID:
    """El analista responde 'esta variable es Marcas o Razones' una sola vez por
    estudio (sección 2.5/2.6) — queda guardado en `questions` para siempre; las
    rondas futuras del mismo estudio la reutilizan sin volver a preguntar. Una vez
    clasificada, reintentar `insert_verbatims` con las mismas filas ya no las deja
    pendientes (Tarea 9)."""
    existing = db.execute(
        text("select id from questions where project_id = :project and question_key = :qk"),
        {"project": project_id, "qk": question_key},
    ).scalar()
    if existing:
        return existing
    qid = uuid.uuid4()
    db.execute(
        text("""
            insert into questions (id, project_id, coding_type, question_key,
                                   single_code_per_response, expected_max_mentions)
            values (:id, :project, :ct, :qk, :single, :max_m)
        """),
        {
            "id": qid, "project": project_id, "ct": coding_type, "qk": question_key,
            "single": single_code_per_response, "max_m": expected_max_mentions,
        },
    )
    return qid


def _get_or_create_respondent(
    db: Session,
    round_id: uuid.UUID,
    respondent_external_id: str,
    imported_file_id: uuid.UUID,
    realid: str | None = None,
) -> uuid.UUID:
    """v9 (REQ-03): la unicidad del Serial es por (ronda, carga, Serial) — el mismo
    Serial puede venir legítimamente de dos cargas distintas (Dimension/Enfield
    numeran cada una desde 1) y ambos se conservan. `realid` identifica a la
    persona real (el parser .dau ya lo separa del Serial); cuando la fuente no
    trae un realid aparte (Excel), cae al propio respondent_external_id — REQ-03
    trata Serial/realid como sinónimos si no hay campo separado."""
    result = db.execute(
        text("""
            insert into respondents (id, round_id, imported_file_id, respondent_external_id, realid)
            values (:id, :round, :file, :resp, :realid)
            on conflict (round_id, imported_file_id, respondent_external_id) do update set
              realid = excluded.realid
            returning id
        """),
        {
            "id": uuid.uuid4(),
            "round": round_id,
            "file": imported_file_id,
            "resp": respondent_external_id,
            "realid": realid or respondent_external_id,
        },
    ).scalar()
    return result


def insert_verbatims(
    db: Session,
    round_id: uuid.UUID,
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    rows: list[dict],
    min_mentions_threshold: int | None = None,
    audit_percentage: float | None = None,
    field_selections: list[dict] | None = None,
) -> tuple[int, pl.DataFrame, list[str], dict[str, int]]:
    """Normaliza, inserta verbatims y devuelve (n_inserted, DF slim para fuzzy,
    question_keys nuevas sin clasificar, filas omitidas por coding_type no
    configurado en la ronda). Cada fila se reparte al subproject_id que le
    corresponde según `questions.coding_type` de su variable de origen (sección 2.5) —
    no según un coding_type fijo. Filas cuya question_key no tiene fila en `questions`
    todavía se excluyen (no fallan) y se listan en el 3er valor de retorno para que el
    caller dispare el flujo de clasificación de variable nueva (Tarea 9) — salvo que
    `guess_coding_type` reconozca la plantilla NBS_UNAID* (sección 2.5b) Y ese tipo
    exista en la ronda, en cuyo caso se auto-clasifica sin pedirle al analista.

    No se crean subproyectos nuevos aquí: la ronda ya declaró Marcas / Razones /
    ambos al crearse (con origen de catálogo obligatorio). Si el archivo trae un
    tipo que la ronda no configuró, esas filas se omiten y se reportan en el 4º
    valor. `min_mentions_threshold`/`audit_percentage` se conservan en la firma
    por compatibilidad con callers viejos, pero ya no se usan para crear
    subproyectos."""
    subproject_by_coding_type = {
        r["coding_type"]: r["id"]
        for r in db.execute(
            text("select id, coding_type from subprojects where round_id = :round"),
            {"round": round_id},
        ).mappings().all()
    }
    configured_types = set(subproject_by_coding_type)

    # Pre-load all questions + aliases for this project (elimina per-row SELECTs)
    questions_by_key: dict[str, dict] = {}
    for q in db.execute(
        text("SELECT id, question_key, coding_type FROM questions WHERE project_id = :project"),
        {"project": project_id},
    ).mappings().all():
        questions_by_key[q["question_key"]] = q

    for a in db.execute(
        text("""
            SELECT qa.alias_key, q.id, q.coding_type
            FROM question_aliases qa
            JOIN questions q ON q.id = qa.canonical_question_id
            WHERE q.project_id = :project
        """),
        {"project": project_id},
    ).mappings().all():
        if a["alias_key"] not in questions_by_key:
            a["question_key"] = a["alias_key"]
            questions_by_key[a["alias_key"]] = a

    # Selección de campos del wizard (Task 4): excluye campos marcados
    # `included=False` antes de procesar filas, y pre-clasifica los que traen
    # `coding_type` explícito para que nunca caigan en pending_questions.
    if field_selections:
        excluded_fields = {fs["field"] for fs in field_selections if not fs.get("included", True)}
        if excluded_fields:
            rows = [r for r in rows if r.get("question_key") not in excluded_fields]
        for fs in field_selections:
            coding_type = fs.get("coding_type")
            if not coding_type:
                continue
            if coding_type not in configured_types:
                raise ValueError(
                    f"coding_type '{coding_type}' para el campo '{fs['field']}' "
                    f"no está configurado en esta ronda"
                )
            field = fs["field"]
            if field not in questions_by_key:
                qid = classify_question(db, project_id, field, coding_type)
                questions_by_key[field] = {"id": qid, "coding_type": coding_type}

    pending: set[str] = set()
    skipped_by_type: dict[str, int] = {}
    rows_by_coding_type: dict[str, list[dict]] = {"brands": [], "reasons": []}
    question_id_by_key: dict[str | None, uuid.UUID | None] = {}

    for row in rows:
        resp = str(row.get("respondent_external_id") or "").strip()
        if not resp:
            continue
        qk = row.get("question_key")
        q_info = questions_by_key.get(qk) if qk else None

        if qk and q_info is None:
            guessed = guess_coding_type(qk)
            # Solo auto-clasifica si el tipo adivinado existe en esta ronda;
            # si no, queda pendiente para que el analista elija entre los tipos
            # configurados (nunca se inventa un subproyecto a ciegas).
            if guessed is None or guessed not in configured_types:
                pending.add(qk)
                continue
            qid = classify_question(db, project_id, qk, guessed)
            q_info = {"id": qid, "coding_type": guessed}
            questions_by_key[qk] = q_info

        if q_info is None:
            continue

        coding_type = q_info["coding_type"]
        if coding_type not in configured_types:
            skipped_by_type[coding_type] = skipped_by_type.get(coding_type, 0) + 1
            continue

        question_id_by_key[qk] = q_info["id"]
        rows_by_coding_type.setdefault(coding_type, []).append(row)

    n = 0
    df_parts = []
    for coding_type, ct_rows in rows_by_coding_type.items():
        if not ct_rows:
            continue
        subproject_id = subproject_by_coding_type.get(coding_type)
        if not subproject_id:
            skipped_by_type[coding_type] = skipped_by_type.get(coding_type, 0) + len(ct_rows)
            continue

        df = rows_to_normalized_df(ct_rows, coding_type)
        df_parts.append(df)

        originals: dict[tuple[str, str | None], dict] = {}
        for r in ct_rows:
            resp = str(r.get("respondent_external_id") or "").strip()
            if not resp:
                continue
            originals[(resp, r.get("question_key"))] = r

        # Phase 1: Batch respondent INSERT + SELECT (replaces per-row _get_or_create_respondent)
        respondent_keys: set[str] = set()
        for row in df.iter_rows(named=True):
            respondent_keys.add(row["respondent_external_id"])

        respondent_cache: dict[str, uuid.UUID] = {}
        if respondent_keys:
            respondent_params = [
                {"id": uuid.uuid4(), "round": round_id, "file": file_id, "resp": resp, "realid": resp}
                for resp in respondent_keys
            ]
            db.execute(
                text("""
                    INSERT INTO respondents (id, round_id, imported_file_id, respondent_external_id, realid)
                    VALUES (:id, :round, :file, :resp, :realid)
                    ON CONFLICT (round_id, imported_file_id, respondent_external_id)
                    DO UPDATE SET realid = excluded.realid
                """),
                respondent_params,
            )
            resp_rows = db.execute(
                text("""
                    SELECT respondent_external_id, id FROM respondents
                    WHERE round_id = :round AND imported_file_id = :file
                    AND respondent_external_id = ANY(:resps)
                """),
                {"round": round_id, "file": file_id, "resps": list(respondent_keys)},
            ).mappings().all()
            respondent_cache = {r["respondent_external_id"]: r["id"] for r in resp_rows}

        # Phase 2: Batch verbatim INSERT (replaces per-row INSERT)
        verbatim_params = []
        for row in df.iter_rows(named=True):
            key = (row["respondent_external_id"], row.get("question_key"))
            src = originals.get(key) or originals.get((row["respondent_external_id"], None))
            original = (src or {}).get("original_text") or row["normalized_text"]
            input_code = (src or {}).get("input_code_number")
            respondent_id = respondent_cache.get(row["respondent_external_id"])

            verbatim_params.append({
                "id": uuid.uuid4(),
                "sp": subproject_id,
                "resp_id": respondent_id,
                "qid": question_id_by_key.get(row.get("question_key")),
                "f": file_id,
                "q": row.get("question_key"),
                "txt": original,
                "norm": row["normalized_text"],
                "inp": input_code,
            })

        if verbatim_params:
            db.execute(
                text("""
                    INSERT INTO verbatims (id, subproject_id, respondent_id, question_id,
                                           imported_file_id, source_question_key,
                                           original_text, normalized_text, input_code_number,
                                           coding_status)
                    VALUES (:id, :sp, :resp_id, :qid, :f, :q, :txt, :norm, :inp, 'pending')
                    ON CONFLICT (subproject_id, respondent_id, source_question_key)
                    DO UPDATE SET
                      normalized_text = excluded.normalized_text,
                      original_text = excluded.original_text,
                      imported_file_id = excluded.imported_file_id
                    WHERE verbatims.coding_status = 'pending'
                """),
                verbatim_params,
            )
            n += len(verbatim_params)

    combined_df = pl.concat(df_parts) if df_parts else rows_to_normalized_df([], "brands")
    return n, combined_df, sorted(pending), skipped_by_type


def build_mention_groups(db: Session, subproject_id: uuid.UUID) -> int:
    """Agrupa verbatims ya normalizados por texto exacto (dedup para el paso 2)."""
    db.execute(
        text("""
            insert into mention_groups (id, subproject_id, normalized_text, sample_text,
                                        frequency_count, status)
            select gen_random_uuid(), :sp, v.normalized_text, min(v.original_text),
                   count(*), 'pending_review'
            from verbatims v
            where v.subproject_id = :sp and v.normalized_text <> ''
            group by v.normalized_text
            on conflict (subproject_id, normalized_text)
            do update set frequency_count = excluded.frequency_count
        """),
        {"sp": subproject_id},
    )

    db.execute(
        text("""
            update verbatims v
            set mention_group_id = g.id
            from mention_groups g
            where g.subproject_id = :sp
              and v.subproject_id = :sp
              and v.normalized_text = g.normalized_text
        """),
        {"sp": subproject_id},
    )

    return db.execute(
        text("select count(*) from mention_groups where subproject_id = :sp"),
        {"sp": subproject_id},
    ).scalar()


def propagate_group_codes_to_pending(db: Session, subproject_id: uuid.UUID) -> int:
    """REQ-03: un verbatim de una carga nueva cuyo texto normalizado calza con un
    mention_group YA resuelto/auto-codificado se cuelga de ese grupo (UNIQUE por
    subproject+normalized_text), pero el motor solo mira grupos 'pending_review' —
    sin esto quedaría 'pending' para siempre. Se le copian los códigos activos de
    un hermano del grupo (la resolución asigna el mismo set a todo el grupo) sin
    reabrir ni tocar el grupo histórico. Devuelve cuántos verbatims se actualizaron."""
    pending = db.execute(
        text("""
            select v.id as verbatim_id, g.id as group_id, g.status as group_status
            from verbatims v
            join mention_groups g on g.id = v.mention_group_id
            where g.subproject_id = :sp
              and g.status in ('auto_coded', 'resolved')
              and v.coding_status = 'pending'
            order by g.id
        """),
        {"sp": subproject_id},
    ).mappings().all()
    if not pending:
        return 0

    codes_by_group: dict = {}
    updated = 0
    for row in pending:
        gid = row["group_id"]
        if gid not in codes_by_group:
            # Códigos de referencia: los del hermano más antiguo con asignación activa.
            sibling = db.execute(
                text("""
                    select v2.id from verbatims v2
                    where v2.mention_group_id = :gid and v2.coding_status <> 'pending'
                      and exists (
                        select 1 from verbatim_codes vc
                        where vc.verbatim_id = v2.id and vc.is_active
                      )
                    order by v2.created_at
                    limit 1
                """),
                {"gid": gid},
            ).scalar()
            codes_by_group[gid] = db.execute(
                text("""
                    select code_id, output_index, source, confidence_score, matched_alias
                    from verbatim_codes
                    where verbatim_id = :vid and is_active
                    order by output_index
                """),
                {"vid": sibling},
            ).mappings().all() if sibling else []

        for code in codes_by_group[gid]:
            db.execute(
                text("""
                    insert into verbatim_codes (id, verbatim_id, code_id, output_index,
                                                source, confidence_score, matched_alias)
                    values (:id, :vid, :code, :idx, :src, :score, :alias)
                    on conflict (verbatim_id, code_id) do nothing
                """),
                {
                    "id": uuid.uuid4(), "vid": row["verbatim_id"], "code": code["code_id"],
                    "idx": code["output_index"], "src": code["source"],
                    "score": code["confidence_score"], "alias": code["matched_alias"],
                },
            )
        # Aun sin códigos (grupo resuelto por descarte puro) el estado acompaña
        # al del grupo: no puede quedar 'pending' un verbatim de un grupo cerrado.
        db.execute(
            text("update verbatims set coding_status = :st where id = :vid"),
            {
                "st": "manually_coded" if row["group_status"] == "resolved" else "auto_coded",
                "vid": row["verbatim_id"],
            },
        )
        updated += 1
    return updated


# =====================================================================
# Centro de Resolución (Fase 4)
# =====================================================================

def _current_codebook_id(db: Session, project_id: uuid.UUID, coding_type: str) -> uuid.UUID | None:
    return db.execute(
        text("select id from codebooks where project_id = :project and coding_type = :ct order by version desc limit 1"),
        {"project": project_id, "ct": coding_type},
    ).scalar()


def get_or_create_subproject(
    db: Session,
    round_id: uuid.UUID,
    project_id: uuid.UUID,
    coding_type: str,
    min_mentions_threshold: int | None = None,
    audit_percentage: float | None = None,
) -> uuid.UUID:
    """Crea el subproyecto de este coding_type la primera vez que aparece en la
    ronda — antes create_round creaba siempre los 2 (Marcas y Razones) sin mirar
    el archivo; ahora una ronda solo tiene los subproyectos que sus archivos
    importados realmente traen (una ronda con un .dau de solo marcas termina con
    un único subproyecto). Reutiliza el codebook compartido del Estudio
    (project_id+coding_type) igual que hacía create_round, incluida la
    homologación cross-estudio si la ronda es 'homologated'.

    `min_mentions_threshold`/`audit_percentage` solo se aplican en esta creación
    (vienen del formulario de import, capturados al soltar el archivo) — cambiarlos
    después de que el subproyecto arrancó a procesar puede dejar el motor en un
    estado inconsistente (ej. el catálogo por frecuencia ya se derivó con el
    umbral viejo), así que no existe un endpoint para editarlos más tarde."""
    existing = db.execute(
        text("select id from subprojects where round_id = :round and coding_type = :ct"),
        {"round": round_id, "ct": coding_type},
    ).scalar()
    if existing:
        return existing

    cb_id = _current_codebook_id(db, project_id, coding_type)
    if not cb_id:
        cb_id = create_codebook(db, project_id, coding_type)
        seed_system_codes(db, cb_id)

        round_row = db.execute(
            text("select origin_mode, source_round_id from rounds where id = :id"),
            {"id": round_id},
        ).mappings().first()
        if round_row and round_row["origin_mode"] == "homologated" and round_row["source_round_id"]:
            source_project_id = db.execute(
                text("select project_id from rounds where id = :id"),
                {"id": round_row["source_round_id"]},
            ).scalar()
            if source_project_id and source_project_id != project_id:
                clone_codebook(db, source_project_id, coding_type, cb_id)

    sp_id = uuid.uuid4()
    db.execute(
        text("""
            insert into subprojects (id, round_id, codebook_id, coding_type,
                                     min_mentions_threshold, audit_percentage)
            values (:id, :round, :cb, :ct,
                    coalesce(:min_m, 3), coalesce(:audit, 10))
        """),
        {
            "id": sp_id, "round": round_id, "cb": cb_id, "ct": coding_type,
            "min_m": min_mentions_threshold, "audit": audit_percentage,
        },
    )
    return sp_id


def get_resolution_queue(
    db: Session, subproject_id: uuid.UUID, statuses: list[str], limit: int, offset: int
) -> tuple[list[dict], int]:
    """Grupos pendientes ordenados por frecuencia (impacto). `statuses` filtra mention_groups.status."""
    rows = db.execute(
        text("""
            select g.id, g.normalized_text, g.sample_text, g.frequency_count, g.status,
                   c.id as suggested_code_id, c.code_number as suggested_code_number,
                   c.label as suggested_code_label
            from mention_groups g
            left join codes c on c.id = g.suggested_code_id
            where g.subproject_id = :sp and g.status = any(:statuses)
            order by g.frequency_count desc, g.normalized_text
            limit :lim offset :off
        """),
        {"sp": subproject_id, "statuses": statuses, "lim": limit, "off": offset},
    ).mappings().all()

    total = db.execute(
        text("""
            select count(*) from mention_groups
            where subproject_id = :sp and status = any(:statuses)
        """),
        {"sp": subproject_id, "statuses": statuses},
    ).scalar()

    items = [
        {
            "id": str(r["id"]),
            "normalized_text": r["normalized_text"],
            "sample_text": r["sample_text"],
            "frequency_count": r["frequency_count"],
            "status": r["status"],
            "suggested_code": (
                {
                    "id": str(r["suggested_code_id"]),
                    "code_number": r["suggested_code_number"],
                    "label": r["suggested_code_label"],
                }
                if r["suggested_code_id"]
                else None
            ),
        }
        for r in rows
    ]
    return items, total


def get_resolution_summary(db: Session, subproject_id: uuid.UUID) -> dict:
    counts = db.execute(
        text("select status, count(*) as n from mention_groups where subproject_id = :sp group by status"),
        {"sp": subproject_id},
    ).mappings().all()
    by_status = {r["status"]: r["n"] for r in counts}
    pending = by_status.get("anomaly", 0) + by_status.get("below_threshold", 0) + by_status.get("pending_review", 0)
    auto_coded = by_status.get("auto_coded", 0)
    resolved = by_status.get("resolved", 0)
    total = pending + auto_coded + resolved
    return {
        "pending": pending,
        "auto_coded": auto_coded,
        "resolved": resolved,
        "progress_pct": round((resolved + auto_coded) / total * 100, 1) if total else 0.0,
        "can_close": pending == 0,
    }


def get_pending_summary(db: Session, subproject_id: uuid.UUID) -> list[dict]:
    """Menciones aún sin resolver — una fila por mention_group (ya son únicas por
    texto), con el código que el motor sugirió si lo hay."""
    rows = db.execute(
        text("""
            select g.normalized_text, g.sample_text, g.frequency_count,
                   c.code_number as suggested_code_number, c.label as suggested_code_label
            from mention_groups g
            left join codes c on c.id = g.suggested_code_id
            where g.subproject_id = :sp and g.status in ('anomaly', 'below_threshold', 'pending_review')
            order by g.frequency_count desc, g.normalized_text
        """),
        {"sp": subproject_id},
    ).mappings().all()

    total = sum(r["frequency_count"] for r in rows) or 1
    return [
        {
            "code_id": None,
            "code_number": r["suggested_code_number"],
            "label": r["suggested_code_label"],
            "content": r["sample_text"] or r["normalized_text"],
            "frequency": r["frequency_count"],
            "percentage": round(r["frequency_count"] / total * 100, 1),
        }
        for r in rows
    ]


def get_coded_summary(db: Session, subproject_id: uuid.UUID) -> list[dict]:
    """Menciones ya codificadas (auto_coded/resolved), agrupadas por código —una fila
    por código, no por verbatim. `frequency` suma frequency_count de cada mention_group
    distinto asignado a ese código (el código real vía verbatim_codes, no la sugerencia
    del motor, porque resolver a mano puede cambiar el código sugerido)."""
    rows = db.execute(
        text("""
            select c.id as code_id, c.code_number, c.label,
                   sum(g.frequency_count) as frequency,
                   (array_agg(g.sample_text order by g.frequency_count desc))[1] as content
            from (
                select distinct on (mg.id)
                       mg.id, mg.frequency_count, mg.sample_text, vc.code_id
                from mention_groups mg
                join verbatims v on v.mention_group_id = mg.id
                join verbatim_codes vc on vc.verbatim_id = v.id and vc.is_active and vc.output_index = 1
                where mg.subproject_id = :sp and mg.status in ('auto_coded', 'resolved')
                order by mg.id, v.id
            ) g
            join codes c on c.id = g.code_id
            group by c.id, c.code_number, c.label
            order by frequency desc
        """),
        {"sp": subproject_id},
    ).mappings().all()

    total = sum(r["frequency"] for r in rows) or 1
    return [
        {
            "code_id": str(r["code_id"]),
            "code_number": r["code_number"],
            "label": r["label"],
            "content": r["content"],
            "frequency": r["frequency"],
            "percentage": round(r["frequency"] / total * 100, 1),
        }
        for r in rows
    ]


def get_group_detail(db: Session, group_id: uuid.UUID, sample_limit: int = 5) -> dict | None:
    group = db.execute(
        text("""
            select g.id, g.subproject_id, g.normalized_text, g.sample_text, g.frequency_count, g.status,
                   c.id as suggested_code_id, c.code_number as suggested_code_number,
                   c.label as suggested_code_label
            from mention_groups g
            left join codes c on c.id = g.suggested_code_id
            where g.id = :id
        """),
        {"id": group_id},
    ).mappings().first()
    if not group:
        return None

    samples = db.execute(
        text("""
            select original_text from verbatims
            where mention_group_id = :id
            order by created_at
            limit :lim
        """),
        {"id": group_id, "lim": sample_limit},
    ).scalars().all()

    verbatims_count = db.execute(
        text("select count(*) from verbatims where mention_group_id = :id"),
        {"id": group_id},
    ).scalar()

    return {
        "id": str(group["id"]),
        "subproject_id": str(group["subproject_id"]),
        "normalized_text": group["normalized_text"],
        "sample_text": group["sample_text"],
        "frequency_count": group["frequency_count"],
        "status": group["status"],
        "verbatims_count": verbatims_count,
        "samples": list(samples),
        "suggested_code": (
            {
                "id": str(group["suggested_code_id"]),
                "code_number": group["suggested_code_number"],
                "label": group["suggested_code_label"],
            }
            if group["suggested_code_id"]
            else None
        ),
    }


def list_codebook_codes(db: Session, codebook_id: uuid.UUID, include_system: bool = False) -> list[dict]:
    """Antes `list_round_codes(round_id)`: el codebook ya no es 1:1 con la ronda (vive
    a nivel project_id+coding_type, Tarea 3), así que el caller resuelve el codebook_id
    correcto (vía subproject_id -> subprojects.codebook_id) y lo pasa directo."""
    rows = db.execute(
        text("""
            select c.id, c.code_number, c.label, c.is_system, n.name as net
            from codes c
            left join net_codes nc on nc.code_id = c.id
            left join nets n on n.id = nc.net_id
            where c.codebook_id = :cb and c.is_active
              and (:include_system or not c.is_system)
            order by c.code_number
        """),
        {"cb": codebook_id, "include_system": include_system},
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "code_number": r["code_number"],
            "label": r["label"],
            "net": r["net"],
            "is_system": r["is_system"],
        }
        for r in rows
    ]


def create_code(db: Session, codebook_id: uuid.UUID, label: str, net_id: uuid.UUID | None, user_id) -> dict:
    """Crea un código nuevo (deduplicado por normalize(label)); si ya existe, lo retorna."""
    norm_label = normalize(label.strip()) if label else label
    existing = db.execute(
        text("""
            select id, code_number, label from codes
            where codebook_id = :cb and is_active and lower(label) = lower(:label)
            limit 1
        """),
        {"cb": codebook_id, "label": norm_label},
    ).mappings().first()
    if not existing:
        rows = db.execute(
            text("select id, code_number, label from codes where codebook_id = :cb and is_active"),
            {"cb": codebook_id},
        ).mappings().all()
        for r in rows:
            if normalize(r["label"]) == norm_label:
                existing = r
                break

    if existing:
        return {"id": str(existing["id"]), "code_number": existing["code_number"], "label": existing["label"], "is_new": False}

    # Serializa la asignación para que dos resoluciones concurrentes no elijan
    # el mismo número. Los números existentes jamás se reciclan ni actualizan.
    db.execute(
        text("select id from codebooks where id = :cb for update"),
        {"cb": codebook_id},
    )
    number_rows = db.execute(
        text("select code_number, is_system from codes where codebook_id = :cb"),
        {"cb": codebook_id},
    ).mappings().all()
    occupied = {row["code_number"] for row in number_rows}
    non_system = [row["code_number"] for row in number_rows if not row["is_system"]]
    next_number = (max(non_system) if non_system else 0) + 1
    while next_number in occupied:
        next_number += 1

    code_id = uuid.uuid4()
    db.execute(
        text("""
            insert into codes (id, codebook_id, code_number, label, origin, is_system, created_by)
            values (:id, :cb, :n, :l, 'analyst_manual', false, :u)
        """),
        {"id": code_id, "cb": codebook_id, "n": next_number, "l": norm_label, "u": user_id},
    )
    if net_id:
        db.execute(
            text("""
                insert into net_codes (id, net_id, code_id)
                values (:id, :n, :c)
                on conflict (net_id, code_id) do nothing
            """),
            {"id": uuid.uuid4(), "n": net_id, "c": code_id},
        )
    return {"id": str(code_id), "code_number": next_number, "label": norm_label, "is_new": True}


def deactivate_group_codes(db: Session, group_id: uuid.UUID) -> None:
    """Preserva histórico: para reasignaciones, apaga las relaciones viejas en vez de borrarlas."""
    db.execute(
        text("""
            update verbatim_codes set is_active = false
            where is_active and verbatim_id in (
                select id from verbatims where mention_group_id = :gid
            )
        """),
        {"gid": group_id},
    )


def assign_codes_to_group(
    db: Session, group_id: uuid.UUID, code_ids: list[uuid.UUID], source: str, user_id
) -> int:
    """Propaga code_ids (en orden -> output_index 1..N) a todos los verbatims del grupo."""
    verbatim_ids = db.execute(
        text("select id from verbatims where mention_group_id = :gid"),
        {"gid": group_id},
    ).scalars().all()

    for vid in verbatim_ids:
        for idx, code_id in enumerate(code_ids, start=1):
            db.execute(
                text("""
                    insert into verbatim_codes (id, verbatim_id, code_id, output_index, source, assigned_by, is_active)
                    values (:id, :vid, :cid, :idx, :src, :u, true)
                    on conflict (verbatim_id, code_id) do update set
                      output_index = excluded.output_index,
                      source = excluded.source,
                      assigned_by = excluded.assigned_by,
                      is_active = true
                """),
                {"id": uuid.uuid4(), "vid": vid, "cid": code_id, "idx": idx, "src": source, "u": user_id},
            )
    return len(verbatim_ids)


def mark_group_resolved(db: Session, group_id: uuid.UUID, user_id) -> None:
    db.execute(
        text("""
            update mention_groups set status = 'resolved', resolved_by = :u, resolved_at = now()
            where id = :gid
        """),
        {"gid": group_id, "u": user_id},
    )
    db.execute(
        text("update verbatims set coding_status = 'manually_coded' where mention_group_id = :gid"),
        {"gid": group_id},
    )


def unresolve_group(db: Session, group_id: uuid.UUID, user_id) -> None:
    """Deshace la resolución de un grupo: apaga las asignaciones activas hechas por
    este usuario, reabre el grupo a 'pending_review' y revierte el coding_status de
    sus verbatims. NO borra códigos ni alias aprendidos (pueden reusarse)."""
    db.execute(
        text("""
            update verbatim_codes set is_active = false
            where is_active and assigned_by = :u and verbatim_id in (
                select id from verbatims where mention_group_id = :gid
            )
        """),
        {"gid": group_id, "u": user_id},
    )
    db.execute(
        text("""
            update mention_groups
            set status = 'pending_review', resolved_by = null, resolved_at = null
            where id = :gid
        """),
        {"gid": group_id},
    )
    db.execute(
        text("update verbatims set coding_status = 'pending' where mention_group_id = :gid"),
        {"gid": group_id},
    )


def add_alias_from_group(db: Session, codebook_id: uuid.UUID, code_id: uuid.UUID, group: dict) -> None:
    norm = group["normalized_text"]
    if not norm:
        return
    db.execute(
        text("""
            insert into code_aliases (id, codebook_id, code_id, alias_normalized, alias_sample, origin)
            values (:id, :cb, :c, :norm, :sample, 'analyst_manual')
            on conflict (codebook_id, alias_normalized, code_id) do nothing
        """),
        {"id": uuid.uuid4(), "cb": codebook_id, "c": code_id, "norm": norm, "sample": group.get("sample_text")},
    )


# =====================================================================
# Auditoría (Fase 5)
# =====================================================================

def _serialize_audit_session(row) -> dict:
    return {
        "id": str(row["id"]),
        "subproject_id": str(row["subproject_id"]),
        "processing_run_id": str(row["processing_run_id"]) if row["processing_run_id"] else None,
        "target_percentage": float(row["target_percentage"]),
        "total_items": row["total_items"],
        "reviewed_items": row["reviewed_items"],
        "target_met": row["target_met"],
        "status": row["status"],
        "approved_by": str(row["approved_by"]) if row["approved_by"] else None,
        "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def get_audit_session(db: Session, subproject_id: uuid.UUID) -> dict | None:
    """Última sesión de auditoría del subproyecto (puede haber más de una tras un reproceso)."""
    row = db.execute(
        text("""
            select id, subproject_id, processing_run_id, target_percentage, total_items,
                   reviewed_items, target_met, status, approved_by, approved_at, created_at
            from audit_sessions
            where subproject_id = :sp
            order by created_at desc
            limit 1
        """),
        {"sp": subproject_id},
    ).mappings().first()
    return _serialize_audit_session(row) if row else None


def get_latest_processing_run(db: Session, subproject_id: uuid.UUID) -> dict | None:
    row = db.execute(
        text("""
            select id, random_seed from processing_runs
            where subproject_id = :sp
            order by created_at desc
            limit 1
        """),
        {"sp": subproject_id},
    ).mappings().first()
    return {"id": str(row["id"]), "random_seed": row["random_seed"]} if row else None


def set_run_random_seed(db: Session, run_id: uuid.UUID, seed: int) -> None:
    db.execute(
        text("update processing_runs set random_seed = :seed where id = :id"),
        {"seed": seed, "id": run_id},
    )


def get_round_audit_percentage(db: Session, round_id: uuid.UUID) -> float | None:
    """El % de auditoría vive directo en la ronda."""
    pct = db.execute(
        text("select audit_percentage from rounds where id = :round"),
        {"round": round_id},
    ).scalar()
    return float(pct) if pct is not None else None


def get_coded_population(db: Session, subproject_id: uuid.UUID) -> list[dict]:
    """La población auditable: un registro por verbatim con ≥1 código activo
    (lo que irá al Excel), con la foto de sus códigos ordenados por output_index."""
    rows = db.execute(
        text("""
            select v.id as verbatim_id,
                   jsonb_agg(
                     jsonb_build_object(
                       'code_id', c.id, 'code_number', c.code_number,
                       'label', c.label, 'source', vc.source
                     ) order by vc.output_index
                   ) as codes
            from verbatims v
            join verbatim_codes vc on vc.verbatim_id = v.id and vc.is_active
            join codes c on c.id = vc.code_id
            where v.subproject_id = :sp
            group by v.id
        """),
        {"sp": subproject_id},
    ).mappings().all()
    return [{"verbatim_id": str(r["verbatim_id"]), "codes": r["codes"]} for r in rows]


def create_audit_session(
    db: Session,
    subproject_id: uuid.UUID,
    processing_run_id: str | None,
    target_percentage: float,
    total_items: int,
) -> str:
    session_id = uuid.uuid4()
    db.execute(
        text("""
            insert into audit_sessions (id, subproject_id, processing_run_id, target_percentage,
                                        total_items, reviewed_items, target_met, status)
            values (:id, :sp, :run, :pct, :total, 0, :met, 'in_progress')
        """),
        # target_met arranca en true solo si la muestra es vacía (pct 0 o nada
        # codificado): la auditoría queda trivialmente satisfecha y se puede aprobar.
        {"id": session_id, "sp": subproject_id, "run": processing_run_id,
         "pct": target_percentage, "total": total_items, "met": total_items == 0},
    )
    return str(session_id)


def create_audit_code_review(db: Session, session_id: str, code_id: str, items_count: int) -> str:
    review_id = uuid.uuid4()
    db.execute(
        text("""
            insert into audit_code_reviews (id, audit_session_id, code_id, items_count, status)
            values (:id, :session, :code, :count, 'pending')
        """),
        {"id": review_id, "session": session_id, "code": code_id, "count": items_count},
    )
    return str(review_id)


def create_audit_item(db: Session, review_id: str, verbatim_id: str, codes_snapshot: list) -> str:
    item_id = uuid.uuid4()
    db.execute(
        text("""
            insert into audit_items (id, audit_code_review_id, verbatim_id, codes_snapshot, status)
            values (:id, :review, :verbatim, cast(:snapshot as jsonb), 'pending')
        """),
        {"id": item_id, "review": review_id, "verbatim": verbatim_id,
         "snapshot": json.dumps(codes_snapshot)},
    )
    return str(item_id)


def get_audit_summary(db: Session, subproject_id: uuid.UUID) -> dict | None:
    """Resumen de la última sesión: progreso, contadores por estado de item y si la
    sesión quedó desactualizada por un reproceso posterior del motor."""
    session = get_audit_session(db, subproject_id)
    if not session:
        return None

    counts = db.execute(
        text("""
            select i.status, count(*) as n
            from audit_items i
            join audit_code_reviews r on r.id = i.audit_code_review_id
            where r.audit_session_id = :session
            group by i.status
        """),
        {"session": session["id"]},
    ).mappings().all()
    by_status = {r["status"]: r["n"] for r in counts}

    latest_run = get_latest_processing_run(db, subproject_id)
    total = session["total_items"]
    reviewed = session["reviewed_items"]
    return {
        **session,
        "progress_pct": round(reviewed / total * 100, 1) if total else 100.0,
        "items_pending": by_status.get("pending", 0),
        "items_correct": by_status.get("correct", 0),
        "items_reassigned": by_status.get("reassigned", 0),
        # Un run nuevo tras muestrear invalida la foto: la UI avisa y ofrece re-muestrear.
        "is_stale": bool(
            latest_run and session["processing_run_id"]
            and latest_run["id"] != session["processing_run_id"]
        ),
    }


def list_audit_code_reviews(db: Session, session_id: str) -> list[dict]:
    rows = db.execute(
        text("""
            select r.id, r.items_count, r.corrections_count, r.status,
                   c.id as code_id, c.code_number, c.label, n.name as net,
                   count(i.id) filter (where i.status <> 'pending') as reviewed_count
            from audit_code_reviews r
            join codes c on c.id = r.code_id
            left join net_codes nc on nc.code_id = c.id
            left join nets n on n.id = nc.net_id
            left join audit_items i on i.audit_code_review_id = r.id
            where r.audit_session_id = :session
            group by r.id, c.id, n.name
            order by c.code_number
        """),
        {"session": session_id},
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "code": {
                "id": str(r["code_id"]),
                "code_number": r["code_number"],
                "label": r["label"],
                "net": r["net"],
            },
            "items_count": r["items_count"],
            "reviewed_count": r["reviewed_count"],
            "corrections_count": r["corrections_count"],
            "status": r["status"],
        }
        for r in rows
    ]


def list_audit_items(db: Session, review_id: uuid.UUID, limit: int, offset: int) -> tuple[list[dict], int]:
    rows = db.execute(
        text("""
            select i.id, i.status, i.comment, i.codes_snapshot, i.reviewed_at,
                   v.id as verbatim_id, v.original_text, v.normalized_text, v.coding_status,
                   coalesce(
                     jsonb_agg(
                       jsonb_build_object(
                         'code_id', c.id, 'code_number', c.code_number,
                         'label', c.label, 'source', vc.source
                       ) order by vc.output_index
                     ) filter (where vc.id is not null),
                     '[]'::jsonb
                   ) as current_codes,
                   coalesce((
                     select jsonb_agg(jsonb_build_object(
                       'id', ac.id, 'author_id', ac.author_id,
                       'author_name', u.name, 'author_email', u.email,
                       'roles', array(select role_code from user_roles where user_id = ac.author_id order by role_code),
                       'content', ac.content, 'created_at', ac.created_at, 'updated_at', ac.updated_at
                     ) order by ac.created_at)
                     from audit_comments ac left join users u on u.id = ac.author_id
                     where ac.audit_item_id = i.id and ac.deleted_at is null
                   ), '[]'::jsonb) as comments
            from audit_items i
            join verbatims v on v.id = i.verbatim_id
            left join verbatim_codes vc on vc.verbatim_id = v.id and vc.is_active
            left join codes c on c.id = vc.code_id
            where i.audit_code_review_id = :review
            group by i.id, v.id
            order by v.created_at, v.id
            limit :lim offset :off
        """),
        {"review": review_id, "lim": limit, "off": offset},
    ).mappings().all()

    total = db.execute(
        text("select count(*) from audit_items where audit_code_review_id = :review"),
        {"review": review_id},
    ).scalar()

    items = [
        {
            "id": str(r["id"]),
            "verbatim_id": str(r["verbatim_id"]),
            "original_text": r["original_text"],
            "normalized_text": r["normalized_text"],
            "coding_status": r["coding_status"],
            "codes_snapshot": r["codes_snapshot"] or [],
            "current_codes": r["current_codes"],
            "status": r["status"],
            "comment": r["comment"],
            "comments": r["comments"],
            "reviewed_at": r["reviewed_at"].isoformat() if r["reviewed_at"] else None,
        }
        for r in rows
    ]
    return items, total


def get_audit_item(db: Session, item_id: uuid.UUID) -> dict | None:
    """Item + contexto de su review/sesión/subproyecto (lo que las mutaciones necesitan validar)."""
    row = db.execute(
        text("""
            select i.id, i.status, i.comment, i.verbatim_id, i.codes_snapshot,
                   r.id as review_id, r.corrections_count,
                   s.id as session_id, s.status as session_status,
                   s.total_items, s.reviewed_items, s.subproject_id
            from audit_items i
            join audit_code_reviews r on r.id = i.audit_code_review_id
            join audit_sessions s on s.id = r.audit_session_id
            where i.id = :id
        """),
        {"id": item_id},
    ).mappings().first()
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "comment": row["comment"],
        "verbatim_id": str(row["verbatim_id"]),
        "codes_snapshot": row["codes_snapshot"] or [],
        "review_id": str(row["review_id"]),
        "corrections_count": row["corrections_count"],
        "session_id": str(row["session_id"]),
        "session_status": row["session_status"],
        "total_items": row["total_items"],
        "reviewed_items": row["reviewed_items"],
        "subproject_id": str(row["subproject_id"]),
    }


def get_audit_code_review(db: Session, review_id: uuid.UUID) -> dict | None:
    """Sección (code review) + contexto de su sesión — lo que la aprobación por sección valida."""
    row = db.execute(
        text("""
            select r.id, r.status, r.items_count, r.corrections_count,
                   s.id as session_id, s.status as session_status, s.subproject_id,
                   (select count(*) from audit_items i
                     where i.audit_code_review_id = r.id and i.status = 'pending') as pending_items
            from audit_code_reviews r
            join audit_sessions s on s.id = r.audit_session_id
            where r.id = :id
        """),
        {"id": review_id},
    ).mappings().first()
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "items_count": row["items_count"],
        "corrections_count": row["corrections_count"],
        "pending_items": row["pending_items"],
        "session_id": str(row["session_id"]),
        "session_status": row["session_status"],
        "subproject_id": str(row["subproject_id"]),
    }


def mark_review_items_correct(db: Session, review_id: uuid.UUID, user_id) -> int:
    """Aprobar la sección da por correctos sus items sin corregir — el analista revisa
    por código, no verbatim por verbatim; lo editado/eliminado ya quedó 'reassigned'."""
    return db.execute(
        text("""
            update audit_items
            set status = 'correct', reviewer_id = :u, reviewed_at = now()
            where audit_code_review_id = :id and status = 'pending'
        """),
        {"id": review_id, "u": user_id},
    ).rowcount


def set_code_review_result(db: Session, review_id: uuid.UUID, user_id) -> str:
    """Cierra la sección: 'approved' si no hubo correcciones, 'with_corrections' si las hubo."""
    return db.execute(
        text("""
            update audit_code_reviews
            set status = case when corrections_count > 0 then 'with_corrections' else 'approved' end,
                reviewer_id = :u, reviewed_at = now()
            where id = :id
            returning status
        """),
        {"id": review_id, "u": user_id},
    ).scalar()


def deactivate_verbatim_codes(db: Session, verbatim_id: uuid.UUID) -> int:
    """Como deactivate_group_codes pero para un solo verbatim: preserva histórico."""
    return db.execute(
        text("update verbatim_codes set is_active = false where is_active and verbatim_id = :vid"),
        {"vid": verbatim_id},
    ).rowcount


def assign_codes_to_verbatim(db: Session, verbatim_id: uuid.UUID, code_ids: list, user_id) -> None:
    """La corrección de auditoría escribe con source='audit_correction' (trazable en export)."""
    for idx, code_id in enumerate(code_ids, start=1):
        db.execute(
            text("""
                insert into verbatim_codes (id, verbatim_id, code_id, output_index, source, assigned_by, is_active)
                values (:id, :vid, :cid, :idx, 'audit_correction', :u, true)
                on conflict (verbatim_id, code_id) do update set
                  output_index = excluded.output_index,
                  source = excluded.source,
                  assigned_by = excluded.assigned_by,
                  is_active = true
            """),
            {"id": uuid.uuid4(), "vid": verbatim_id, "cid": code_id, "idx": idx, "u": user_id},
        )


def set_verbatim_coding_status(db: Session, verbatim_id: uuid.UUID, status: str) -> None:
    db.execute(
        text("update verbatims set coding_status = :st where id = :id"),
        {"st": status, "id": verbatim_id},
    )


def update_audit_item_review(
    db: Session, item_id: uuid.UUID, status: str, comment: str | None, user_id
) -> None:
    db.execute(
        text("""
            update audit_items
            set status = :st, comment = coalesce(:comment, comment),
                reviewer_id = :u, reviewed_at = now()
            where id = :id
        """),
        {"st": status, "comment": comment, "u": user_id, "id": item_id},
    )


def increment_review_corrections(db: Session, review_id: str) -> None:
    db.execute(
        text("""
            update audit_code_reviews
            set corrections_count = corrections_count + 1
            where id = :id
        """),
        {"id": review_id},
    )


def refresh_audit_session_progress(db: Session, session_id: str) -> dict:
    """Recalcula reviewed_items desde los items (fuente de verdad) y actualiza target_met."""
    reviewed = db.execute(
        text("""
            select count(*) from audit_items i
            join audit_code_reviews r on r.id = i.audit_code_review_id
            where r.audit_session_id = :session and i.status <> 'pending'
        """),
        {"session": session_id},
    ).scalar()
    row = db.execute(
        text("""
            update audit_sessions
            set reviewed_items = :n, target_met = (:n >= total_items)
            where id = :id
            returning total_items, reviewed_items, target_met
        """),
        {"n": reviewed, "id": session_id},
    ).mappings().first()
    return dict(row) if row else {"total_items": 0, "reviewed_items": reviewed, "target_met": True}


def finalize_audit_session(db: Session, session_id: str, user_id) -> None:
    """Cierra la sesión: cada code review sin correcciones queda 'approved', con
    correcciones queda 'with_corrections' (constancia de qué códigos se tocaron)."""
    db.execute(
        text("""
            update audit_code_reviews
            set status = case when corrections_count > 0 then 'with_corrections' else 'approved' end,
                reviewed_at = coalesce(reviewed_at, now())
            where audit_session_id = :session
        """),
        {"session": session_id},
    )
    db.execute(
        text("""
            update audit_sessions
            set status = 'approved', approved_by = :u, approved_at = now(), target_met = true
            where id = :id
        """),
        {"u": user_id, "id": session_id},
    )


def set_round_status(db: Session, round_id: uuid.UUID, status: str) -> None:
    if status == "audit_approved":
        # Una sección/subproyecto aprobado no debe adelantar a toda la ronda.
        # La sesión que se acaba de finalizar ya está visible en esta transacción.
        db.execute(
            text("""
                update rounds r set status = 'audit_approved', updated_at = now()
                where r.id = :id
                  and exists (select 1 from subprojects where round_id = r.id)
                  and not exists (
                    select 1 from subprojects sp
                    where sp.round_id = r.id
                      and not exists (
                        select 1 from audit_sessions ases
                        where ases.subproject_id = sp.id and ases.status = 'approved'
                      )
                  )
            """),
            {"id": round_id},
        )
        return
    db.execute(
        text("update rounds set status = :st, updated_at = now() where id = :id"),
        {"st": status, "id": round_id},
    )


def approve_scratch_codebooks_for_round(
    db: Session, round_id: uuid.UUID, user_id
) -> int:
    """Oficializa catálogos scratch solo cuando la ronda cerró su auditoría."""
    result = db.execute(
        text("""
            update codebooks cb
               set status = 'approved',
                   approved_by = :user,
                   approved_at = now()
             where cb.origin = 'scratch'
               and cb.status <> 'approved'
               and cb.id in (
                 select sp.codebook_id
                   from subprojects sp
                   join rounds r on r.id = sp.round_id
                  where sp.round_id = :round
                    and r.status = 'audit_approved'
               )
        """),
        {"round": round_id, "user": user_id},
    )
    return getattr(result, "rowcount", 0)


def log_action(
    db: Session,
    user_id,
    round_id: uuid.UUID,
    entity_name: str,
    entity_id: uuid.UUID,
    action: str,
    old_value: dict | None = None,
    new_value: dict | None = None,
) -> None:
    db.execute(
        text("""
            insert into audit_logs (id, user_id, round_id, entity_name, entity_id, action, old_value, new_value)
            values (:id, :u, :round, :entity, :eid, :action,
                    cast(:old as jsonb), cast(:new as jsonb))
        """),
        {
            "id": uuid.uuid4(),
            "u": user_id,
            "round": round_id,
            "entity": entity_name,
            "eid": entity_id,
            "action": action,
            "old": json.dumps(old_value) if old_value is not None else None,
            "new": json.dumps(new_value) if new_value is not None else None,
        },
    )


# =====================================================================
# Reporte final + export Libro de Códigos (Fase 5)
# =====================================================================

def get_round_report(db: Session, round_id: uuid.UUID) -> dict:
    """Métricas del reporte: totales, % auto/manual (coding_status) y frecuencia por código.
    Suma a través de los subproyectos de la ronda (Marcas + Razones), no de un único
    coding_type — la ronda ya no tiene uno solo (sección 2.5/2.6 del documento v8)."""
    total = db.execute(
        text("""
            select count(*) from verbatims v
            join subprojects sp on sp.id = v.subproject_id
            where sp.round_id = :round
        """),
        {"round": round_id},
    ).scalar() or 0

    status_rows = db.execute(
        text("""
            select v.coding_status, count(*) as n
            from verbatims v
            join subprojects sp on sp.id = v.subproject_id
            where sp.round_id = :round
            group by v.coding_status
        """),
        {"round": round_id},
    ).mappings().all()
    by_status = {r["coding_status"]: r["n"] for r in status_rows}
    auto = by_status.get("auto_coded", 0)
    manual = by_status.get("manually_coded", 0)

    processed_at = db.execute(
        text("""
            select max(pr.finished_at) from processing_runs pr
            join subprojects sp on sp.id = pr.subproject_id
            where sp.round_id = :round and pr.status = 'completed'
        """),
        {"round": round_id},
    ).scalar()

    code_rows = db.execute(
        text("""
            select c.id, c.code_number, c.label, n.name as net,
                   count(distinct v.id) as frequency
            from codes c
            join codebooks cb on cb.id = c.codebook_id
            join subprojects sp on sp.codebook_id = cb.id
            left join net_codes nc on nc.code_id = c.id
            left join nets n on n.id = nc.net_id
            left join verbatim_codes vc on vc.code_id = c.id and vc.is_active
            left join verbatims v on v.id = vc.verbatim_id
            where sp.round_id = :round and c.is_active and not c.is_system
            group by c.id, c.code_number, c.label, n.name
            order by frequency desc, c.code_number
        """),
        {"round": round_id},
    ).mappings().all()

    codes = []
    for row in code_rows:
        samples = db.execute(
            text("""
                select v.original_text
                from verbatims v
                join verbatim_codes vc on vc.verbatim_id = v.id and vc.is_active
                where vc.code_id = :code_id
                order by v.created_at
                limit 3
            """),
            {"code_id": row["id"]},
        ).scalars().all()
        freq = row["frequency"]
        codes.append({
            "id": str(row["id"]),
            "code_number": row["code_number"],
            "label": row["label"],
            "net": row["net"],
            "frequency": freq,
            "pct": round(freq / total, 4) if total else 0.0,
            "samples": list(samples),
        })

    return {
        "verbatims_total": total,
        "auto_coded": auto,
        "auto_coded_pct": round(auto / total * 100, 1) if total else 0.0,
        "manually_coded": manual,
        "manually_coded_pct": round(manual / total * 100, 1) if total else 0.0,
        "processed_at": processed_at.isoformat() if processed_at else None,
        "codes": codes,
    }


def _build_codebook_nets(db: Session, codebook_id: uuid.UUID, total_verbatims: int, fallback_label: str) -> list[dict]:
    """Nets+codes de UN codebook (Marcas o Razones tienen catálogos independientes —
    confirmado contra MetaData.txt real: CB_2 significa algo distinto en cada uno)."""
    freq_rows = db.execute(
        text("""
            select c.id, count(distinct v.id) as frequency
            from codes c
            left join verbatim_codes vc on vc.code_id = c.id and vc.is_active
            left join verbatims v on v.id = vc.verbatim_id
            where c.codebook_id = :cb and c.is_active
            group by c.id
        """),
        {"cb": codebook_id},
    ).mappings().all()
    freq_by_id = {r["id"]: r["frequency"] for r in freq_rows}

    alias_rows = db.execute(
        text("""
            select code_id, alias_sample
            from (
                select code_id, alias_sample,
                       row_number() over (partition by code_id order by occurrences desc) as rn
                from code_aliases
                where codebook_id = :cb
            ) ranked
            where rn <= 3
        """),
        {"cb": codebook_id},
    ).mappings().all()
    aliases_by_code: dict[uuid.UUID, list[str]] = {}
    for row in alias_rows:
        aliases_by_code.setdefault(row["code_id"], []).append(row["alias_sample"])

    code_rows = db.execute(
        text("""
            select c.id, c.code_number, c.label, n.name as net_name, n.display_order as net_order
            from codes c
            left join net_codes nc on nc.code_id = c.id
            left join nets n on n.id = nc.net_id
            where c.codebook_id = :cb and c.is_active
            order by coalesce(n.display_order, 999), c.code_number
        """),
        {"cb": codebook_id},
    ).mappings().all()

    def _code_entry(row) -> dict:
        cid = row["id"]
        freq = freq_by_id.get(cid, 0)
        samples = [s for s in aliases_by_code.get(cid, []) if s]
        return {
            "code_number": row["code_number"],
            "label": row["label"],
            "content": "/".join(samples[:3]) if samples else "",
            "frequency": freq,
            "pct": round(freq / total_verbatims, 6) if total_verbatims else 0.0,
            "net_name": row["net_name"],
        }

    net_rows = db.execute(
        text("select name, display_order from nets where codebook_id = :cb order by display_order, name"),
        {"cb": codebook_id},
    ).mappings().all()

    def _by_frequency_desc(c: dict):
        return (-c["frequency"], c["code_number"])

    fallback_net = f"NETO {fallback_label.upper()}"
    if net_rows:
        nets = []
        for net in net_rows:
            codes_in_net = [_code_entry(r) for r in code_rows if r["net_name"] == net["name"]]
            nets.append({"name": net["name"], "codes": sorted(codes_in_net, key=_by_frequency_desc)})
        orphans = [_code_entry(r) for r in code_rows if not r["net_name"]]
        if orphans:
            nets.append({"name": fallback_net, "codes": sorted(orphans, key=_by_frequency_desc)})
    else:
        nets = [{"name": fallback_net, "codes": sorted([_code_entry(r) for r in code_rows], key=_by_frequency_desc)}]
    return nets


def get_round_export_data(db: Session, round_id: uuid.UUID) -> dict:
    """Datos para armar el Excel del Libro de Códigos (LC + Verbatims). Confirmado
    contra el Case 8 real de HBG Leches (OnNextCase.txt): un mismo respondente trae
    variables de Marcas Y Razones en el mismo bloque — los subproyectos se mantienen
    separados en el modelo (cada uno con su propio codebook/nets), pero `verbatims`
    combina ambos en una sola lista por respondent_external_id, igual que el archivo
    real de salida."""
    round_row = db.execute(
        text("""
            select r.*, p.name as study_name, p.external_code as project_external_code
            from rounds r
            join projects p on p.id = r.project_id
            where r.id = :id
        """),
        {"id": round_id},
    ).mappings().first()
    if not round_row:
        return {}

    subprojects = db.execute(
        text("select id, coding_type, codebook_id from subprojects where round_id = :round"),
        {"round": round_id},
    ).mappings().all()

    total_verbatims = db.execute(
        text("""
            select count(*) from verbatims v
            join subprojects sp on sp.id = v.subproject_id
            where sp.round_id = :round
        """),
        {"round": round_id},
    ).scalar() or 0

    nets_by_coding_type = {
        sp["coding_type"]: _build_codebook_nets(
            db, sp["codebook_id"], total_verbatims, f"{round_row['study_name']} {sp['coding_type']}"
        )
        for sp in subprojects
        if sp["codebook_id"]
    }

    verbatim_rows = db.execute(
        text("""
            select resp.respondent_external_id, v.source_question_key, v.original_text,
                   coalesce(
                     jsonb_agg(
                       jsonb_build_object(
                         'output_index', vc.output_index,
                         'code_number', c.code_number,
                         'label', c.label
                       ) order by vc.output_index
                     ) filter (where vc.id is not null),
                     '[]'::jsonb
                   ) as codes
            from verbatims v
            join subprojects sp on sp.id = v.subproject_id
            left join respondents resp on resp.id = v.respondent_id
            left join verbatim_codes vc on vc.verbatim_id = v.id and vc.is_active
            left join codes c on c.id = vc.code_id
            where sp.round_id = :round
            group by v.id, resp.respondent_external_id, v.source_question_key, v.original_text
            order by v.created_at
        """),
        {"round": round_id},
    ).mappings().all()

    max_output = db.execute(
        text("""
            select coalesce(max(vc.output_index), 0)
            from verbatim_codes vc
            join verbatims v on v.id = vc.verbatim_id
            join subprojects sp on sp.id = v.subproject_id
            where sp.round_id = :round and vc.is_active
        """),
        {"round": round_id},
    ).scalar() or 0

    verbatims = []
    for row in verbatim_rows:
        raw_codes = row["codes"]
        if isinstance(raw_codes, str):
            raw_codes = json.loads(raw_codes)
        verbatims.append({
            "respondent_external_id": row["respondent_external_id"],
            "question_key": row["source_question_key"],
            "original_text": row["original_text"],
            "codes": raw_codes or [],
        })

    return {
        "project_external_code": round_row["project_external_code"],
        "round_number": round_row["round_number"],
        "study_name": round_row["study_name"],
        "total_verbatims": total_verbatims,
        "nets_by_coding_type": nets_by_coding_type,
        "verbatims": verbatims,
        "max_output_index": max_output,
    }

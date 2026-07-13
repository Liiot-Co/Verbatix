"""Acceso a datos con SQL explícito (fuente de verdad: 001_schema_v5.sql)."""
import json
import uuid

import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.normalize import normalize, rows_to_normalized_df

SYSTEM_CODES = [
    (95, "Menciones confusas/Incorrectas", "anomaly"),
    (96, "No sabe", "no_answer"),
    (97, "Otras menciones", "other_mentions"),
    (98, "Nada/Ninguna", "none"),
    (99, "No recuerda/No responde", "no_recall"),
]


def create_codebook(db: Session, studio_id: uuid.UUID, parent_codebook_id=None) -> uuid.UUID:
    cb_id = uuid.uuid4()
    db.execute(
        text("""
            insert into codebooks (id, studio_id, version, parent_codebook_id, status)
            values (:id, :studio, 1, :parent, 'draft')
        """),
        {"id": cb_id, "studio": studio_id, "parent": parent_codebook_id},
    )
    return cb_id


def seed_system_codes(db: Session, codebook_id: uuid.UUID) -> None:
    for number, label, stype in SYSTEM_CODES:
        db.execute(
            text("""
                insert into codes (id, codebook_id, code_number, label, origin, is_system, system_type)
                values (:id, :cb, :n, :l, 'inherited', true, :st)
                on conflict (codebook_id, code_number) do nothing
            """),
            {"id": uuid.uuid4(), "cb": codebook_id, "n": number, "l": label, "st": stype},
        )


def clone_codebook(db: Session, source_studio_id: uuid.UUID, target_codebook_id: uuid.UUID) -> dict:
    src = db.execute(
        text("select id from codebooks where studio_id = :studio order by version desc limit 1"),
        {"studio": source_studio_id},
    ).scalar()
    if not src:
        return {"codes": 0, "aliases": 0, "nets": 0}

    codes = db.execute(
        text("""
            insert into codes (id, codebook_id, code_number, label, origin, is_system,
                               system_type, inherited_from_code_id)
            select gen_random_uuid(), :cb, code_number, label, 'inherited', is_system,
                   system_type, id
            from codes where codebook_id = :src and is_active
            returning id
        """),
        {"cb": target_codebook_id, "src": src},
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
        {"cb": target_codebook_id, "src": src},
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
        {"cb": target_codebook_id, "src": src},
    ).rowcount

    return {"codes": codes, "aliases": aliases, "nets": nets}


def insert_codebook_from_excel(db: Session, codebook_id: uuid.UUID, parsed: dict) -> dict:
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
                values (:id, :cb, :n, :l, 'inherited', :sys, :st)
                on conflict (codebook_id, code_number) do nothing
            """),
            {
                "id": cid,
                "cb": codebook_id,
                "n": c["code_number"],
                "l": c["label"],
                "sys": c["is_system"],
                "st": next((s[2] for s in SYSTEM_CODES if s[0] == c["code_number"]), None),
            },
        )

        real_id = db.execute(
            text("select id from codes where codebook_id = :cb and code_number = :n"),
            {"cb": codebook_id, "n": c["code_number"]},
        ).scalar()

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

    return {"codes": len(parsed["codes"]), "aliases": n_alias, "nets": len(parsed["nets"])}


def insert_verbatims(
    db: Session,
    studio_id: uuid.UUID,
    file_id: uuid.UUID,
    rows: list[dict],
    coding_type: str,
) -> tuple[int, pl.DataFrame]:
    """Normaliza, inserta verbatims (con original_text) y devuelve DF slim para fuzzy."""
    df = rows_to_normalized_df(rows, coding_type)
    n = 0
    # Index original texts by (respondent, question_key) for DB insert
    originals: dict[tuple[str, str | None], dict] = {}
    for r in rows:
        resp = str(r.get("respondent_external_id") or "").strip()
        if not resp:
            continue
        qk = r.get("question_key")
        originals[(resp, qk)] = r

    for row in df.iter_rows(named=True):
        key = (row["respondent_external_id"], row.get("question_key"))
        src = originals.get(key) or originals.get((row["respondent_external_id"], None))
        original = (src or {}).get("original_text") or row["normalized_text"]
        input_code = (src or {}).get("input_code_number")
        result = db.execute(
            text("""
                insert into verbatims (id, studio_id, imported_file_id, respondent_external_id,
                                       question_key, original_text, normalized_text, input_code_number,
                                       coding_status)
                values (:id, :studio, :f, :resp, :q, :txt, :norm, :inp, 'pending')
                on conflict (studio_id, respondent_external_id, question_key) do update set
                  normalized_text = excluded.normalized_text,
                  original_text = excluded.original_text,
                  imported_file_id = excluded.imported_file_id
                where verbatims.coding_status = 'pending'
            """),
            {
                "id": uuid.uuid4(),
                "studio": studio_id,
                "f": file_id,
                "resp": row["respondent_external_id"],
                "q": row.get("question_key"),
                "txt": original,
                "norm": row["normalized_text"],
                "inp": input_code,
            },
        )
        if result.rowcount:
            n += 1
    return n, df


def build_mention_groups(db: Session, studio_id: uuid.UUID) -> int:
    """Agrupa verbatims ya normalizados por texto exacto (dedup para el paso 2)."""
    db.execute(
        text("""
            insert into mention_groups (id, studio_id, normalized_text, sample_text,
                                        frequency_count, status)
            select gen_random_uuid(), :studio, v.normalized_text, min(v.original_text),
                   count(*), 'pending_review'
            from verbatims v
            where v.studio_id = :studio and v.normalized_text <> ''
            group by v.normalized_text
            on conflict (studio_id, normalized_text)
            do update set frequency_count = excluded.frequency_count
        """),
        {"studio": studio_id},
    )

    db.execute(
        text("""
            update verbatims v
            set mention_group_id = g.id
            from mention_groups g
            where g.studio_id = :studio
              and v.studio_id = :studio
              and v.normalized_text = g.normalized_text
        """),
        {"studio": studio_id},
    )

    return db.execute(
        text("select count(*) from mention_groups where studio_id = :studio"),
        {"studio": studio_id},
    ).scalar()


# =====================================================================
# Centro de Resolución (Fase 4)
# =====================================================================

def _current_codebook_id(db: Session, studio_id: uuid.UUID) -> uuid.UUID | None:
    return db.execute(
        text("select id from codebooks where studio_id = :studio order by version desc limit 1"),
        {"studio": studio_id},
    ).scalar()


def get_resolution_queue(
    db: Session, studio_id: uuid.UUID, statuses: list[str], limit: int, offset: int
) -> tuple[list[dict], int]:
    """Grupos pendientes ordenados por frecuencia (impacto). `statuses` filtra mention_groups.status."""
    rows = db.execute(
        text("""
            select g.id, g.normalized_text, g.sample_text, g.frequency_count, g.status,
                   c.id as suggested_code_id, c.code_number as suggested_code_number,
                   c.label as suggested_code_label
            from mention_groups g
            left join codes c on c.id = g.suggested_code_id
            where g.studio_id = :studio and g.status = any(:statuses)
            order by g.frequency_count desc, g.normalized_text
            limit :lim offset :off
        """),
        {"studio": studio_id, "statuses": statuses, "lim": limit, "off": offset},
    ).mappings().all()

    total = db.execute(
        text("""
            select count(*) from mention_groups
            where studio_id = :studio and status = any(:statuses)
        """),
        {"studio": studio_id, "statuses": statuses},
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


def get_resolution_summary(db: Session, studio_id: uuid.UUID) -> dict:
    counts = db.execute(
        text("select status, count(*) as n from mention_groups where studio_id = :studio group by status"),
        {"studio": studio_id},
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


def get_group_detail(db: Session, group_id: uuid.UUID, sample_limit: int = 5) -> dict | None:
    group = db.execute(
        text("""
            select g.id, g.studio_id, g.normalized_text, g.sample_text, g.frequency_count, g.status,
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
        "studio_id": str(group["studio_id"]),
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


def list_studio_codes(db: Session, studio_id: uuid.UUID, include_system: bool = False) -> list[dict]:
    cb_id = _current_codebook_id(db, studio_id)
    if not cb_id:
        return []
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
        {"cb": cb_id, "include_system": include_system},
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
    norm_label = normalize(label)
    existing = db.execute(
        text("""
            select id, code_number, label from codes
            where codebook_id = :cb and is_active and lower(label) = lower(:label)
            limit 1
        """),
        {"cb": codebook_id, "label": label},
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

    next_number = db.execute(
        text("select coalesce(max(code_number), 0) + 1 from codes where codebook_id = :cb and not is_system"),
        {"cb": codebook_id},
    ).scalar()

    code_id = uuid.uuid4()
    db.execute(
        text("""
            insert into codes (id, codebook_id, code_number, label, origin, is_system, created_by)
            values (:id, :cb, :n, :l, 'analyst_manual', false, :u)
        """),
        # Store the normalized label (lowercase, no accents/punctuation), not whatever
        # case the analyst typed — keeps codebook labels consistent regardless of who
        # created them or how they capitalized the input.
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


def log_action(
    db: Session,
    user_id,
    studio_id: uuid.UUID,
    entity_name: str,
    entity_id: uuid.UUID,
    action: str,
    old_value: dict | None = None,
    new_value: dict | None = None,
) -> None:
    db.execute(
        text("""
            insert into audit_logs (id, user_id, studio_id, entity_name, entity_id, action, old_value, new_value)
            values (:id, :u, :studio, :entity, :eid, :action,
                    cast(:old as jsonb), cast(:new as jsonb))
        """),
        {
            "id": uuid.uuid4(),
            "u": user_id,
            "studio": studio_id,
            "entity": entity_name,
            "eid": entity_id,
            "action": action,
            "old": json.dumps(old_value) if old_value is not None else None,
            "new": json.dumps(new_value) if new_value is not None else None,
        },
    )

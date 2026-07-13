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
    formatted_label = label.strip().capitalize() if label else label
    norm_label = normalize(formatted_label)
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
        {"id": code_id, "cb": codebook_id, "n": next_number, "l": formatted_label, "u": user_id},
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


# =====================================================================
# Auditoría (Fase 5)
# =====================================================================

def _serialize_audit_session(row) -> dict:
    return {
        "id": str(row["id"]),
        "studio_id": str(row["studio_id"]),
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


def get_audit_session(db: Session, studio_id: uuid.UUID) -> dict | None:
    """Última sesión de auditoría del estudio (puede haber más de una tras un reproceso)."""
    row = db.execute(
        text("""
            select id, studio_id, processing_run_id, target_percentage, total_items,
                   reviewed_items, target_met, status, approved_by, approved_at, created_at
            from audit_sessions
            where studio_id = :studio
            order by created_at desc
            limit 1
        """),
        {"studio": studio_id},
    ).mappings().first()
    return _serialize_audit_session(row) if row else None


def get_latest_processing_run(db: Session, studio_id: uuid.UUID) -> dict | None:
    row = db.execute(
        text("""
            select id, random_seed from processing_runs
            where studio_id = :studio
            order by created_at desc
            limit 1
        """),
        {"studio": studio_id},
    ).mappings().first()
    return {"id": str(row["id"]), "random_seed": row["random_seed"]} if row else None


def set_run_random_seed(db: Session, run_id: uuid.UUID, seed: int) -> None:
    db.execute(
        text("update processing_runs set random_seed = :seed where id = :id"),
        {"seed": seed, "id": run_id},
    )


def get_round_audit_percentage(db: Session, studio_id: uuid.UUID) -> float | None:
    """El % de auditoría vive en la ronda (migración 003), no en el estudio."""
    pct = db.execute(
        text("""
            select r.audit_percentage from rounds r
            join studio s on s.round_id = r.id
            where s.id = :studio
        """),
        {"studio": studio_id},
    ).scalar()
    return float(pct) if pct is not None else None


def get_coded_population(db: Session, studio_id: uuid.UUID) -> list[dict]:
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
            where v.studio_id = :studio
            group by v.id
        """),
        {"studio": studio_id},
    ).mappings().all()
    return [{"verbatim_id": str(r["verbatim_id"]), "codes": r["codes"]} for r in rows]


def create_audit_session(
    db: Session,
    studio_id: uuid.UUID,
    processing_run_id: str | None,
    target_percentage: float,
    total_items: int,
) -> str:
    session_id = uuid.uuid4()
    db.execute(
        text("""
            insert into audit_sessions (id, studio_id, processing_run_id, target_percentage,
                                        total_items, reviewed_items, target_met, status)
            values (:id, :studio, :run, :pct, :total, 0, :met, 'in_progress')
        """),
        # target_met arranca en true solo si la muestra es vacía (pct 0 o nada
        # codificado): la auditoría queda trivialmente satisfecha y se puede aprobar.
        {"id": session_id, "studio": studio_id, "run": processing_run_id,
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


def get_audit_summary(db: Session, studio_id: uuid.UUID) -> dict | None:
    """Resumen de la última sesión: progreso, contadores por estado de item y si la
    sesión quedó desactualizada por un reproceso posterior del motor."""
    session = get_audit_session(db, studio_id)
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

    latest_run = get_latest_processing_run(db, studio_id)
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
                   ) as current_codes
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
            "reviewed_at": r["reviewed_at"].isoformat() if r["reviewed_at"] else None,
        }
        for r in rows
    ]
    return items, total


def get_audit_item(db: Session, item_id: uuid.UUID) -> dict | None:
    """Item + contexto de su review/sesión/estudio (lo que las mutaciones necesitan validar)."""
    row = db.execute(
        text("""
            select i.id, i.status, i.comment, i.verbatim_id, i.codes_snapshot,
                   r.id as review_id, r.corrections_count,
                   s.id as session_id, s.status as session_status,
                   s.total_items, s.reviewed_items, s.studio_id
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
        "studio_id": str(row["studio_id"]),
    }


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


def set_studio_status(db: Session, studio_id: uuid.UUID, status: str) -> None:
    db.execute(
        text("update studio set status = :st, updated_at = now() where id = :id"),
        {"st": status, "id": studio_id},
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

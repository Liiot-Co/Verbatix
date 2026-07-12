"""Acceso a datos con SQL explícito (fuente de verdad: 001_schema_v5.sql)."""
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.normalize import normalize

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


def insert_verbatims(db: Session, studio_id: uuid.UUID, file_id: uuid.UUID, rows: list[dict]) -> int:
    n = 0
    for r in rows:
        if not r["respondent_external_id"]:
            continue
        result = db.execute(
            text("""
                insert into verbatims (id, studio_id, imported_file_id, respondent_external_id,
                                       question_key, original_text, normalized_text, input_code_number)
                values (:id, :studio, :f, :resp, :q, :txt, :norm, :inp)
                on conflict (studio_id, respondent_external_id, question_key) do nothing
            """),
            {
                "id": uuid.uuid4(),
                "studio": studio_id,
                "f": file_id,
                "resp": r["respondent_external_id"],
                "q": r["question_key"],
                "txt": r["original_text"],
                "norm": normalize(r["original_text"]),
                "inp": r["input_code_number"],
            },
        )
        if result.rowcount:
            n += 1
    return n


def build_mention_groups(db: Session, studio_id: uuid.UUID) -> int:
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

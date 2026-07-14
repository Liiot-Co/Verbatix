"""Fase 2 — "el motor propone". Dispatcha por coding_type del studio:

  brands  -> fuzzy contra el catálogo de aliases (pipeline.fuzzy)
  reasons -> LLM structured output (pipeline.llm.classify_studio)

Marcas primero: es fuzzy puro, determinista, y es lo que mejor se ve en demo
(ver Plan de Acción, Fase 2).
"""
from __future__ import annotations

import uuid

import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.fuzzy import (
    discover_catalog_from_frequency,
    load_catalog_aliases,
    run_fuzzy_matching,
)
from app.pipeline.fuzzy.models import Cols, SCORE_THRESHOLD, SYSTEM_ALIAS_VARIANTS
from app.pipeline.llm import classify_studio
from app.repositories import _current_codebook_id


def _process_brands(db: Session, studio_id: uuid.UUID, threshold: float) -> dict:
    groups = db.execute(
        text("""
            select id, normalized_text from mention_groups
            where studio_id = :studio and status = 'pending_review'
        """),
        {"studio": studio_id},
    ).mappings().all()

    # El catálogo sale del codebook cuando existe. Si el studio no trae libro de
    # códigos, se deriva de la frecuencia: las marcas que superan el mínimo de
    # menciones se vuelven semillas y el fuzzy arrastra sus typos hacia ellas.
    catalog = load_catalog_aliases(db, studio_id)
    min_mentions = None
    if not catalog:
        min_mentions = db.execute(
            text("""
                select r.min_mentions_threshold from rounds r
                join studio s on s.round_id = r.id
                where s.id = :studio
            """),
            {"studio": studio_id},
        ).scalar()
        catalog = discover_catalog_from_frequency(db, studio_id, min_mentions, threshold)

    run_id = uuid.uuid4()
    db.execute(
        text("""
            insert into processing_runs (id, studio_id, run_type, algorithm, min_mentions_threshold, status, started_at)
            values (:id, :studio, 'initial', :algo, :thr, 'running', now())
        """),
        {
            "id": run_id,
            "studio": studio_id,
            "algo": "fuzzy_frequency" if min_mentions is not None else "fuzzy_dictionary",
            "thr": min_mentions,
        },
    )
    db.commit()

    matched_by_group: dict[str, dict] = {}
    if groups and catalog:
        df = pl.DataFrame({
            Cols.RESPONDENT_ID: [str(g["id"]) for g in groups],
            Cols.QUESTION_KEY: [None] * len(groups),
            Cols.NORMALIZED_TEXT: [g["normalized_text"] for g in groups],
            Cols.CODING_TYPE: ["brands"] * len(groups),
        })
        result = run_fuzzy_matching(df, catalog, threshold=threshold)
        matched_by_group = {row[Cols.RESPONDENT_ID]: row for row in result.classified.iter_rows(named=True)}

    auto_coded = 0
    anomalies = 0

    update_groups_params = []
    insert_verbatim_codes_params = []
    update_verbatims_params = []

    for g in groups:
        gid = g["id"]
        match = matched_by_group.get(str(gid))
        if match:
            update_groups_params.append({"code": match[Cols.CODE_ID], "run": run_id, "id": gid})
            insert_verbatim_codes_params.append({
                "code": match[Cols.CODE_ID],
                "score": match[Cols.SCORE] / 100,
                "alias": match[Cols.MATCHED_ALIAS],
                "run": run_id,
                "gid": gid,
            })
            update_verbatims_params.append({"gid": gid})
            auto_coded += 1
        else:
            anomalies += 1

    if update_groups_params:
        db.execute(
            text("""
                update mention_groups
                set status = 'auto_coded', suggested_code_id = :code, created_by_run_id = :run
                where id = :id
            """),
            update_groups_params,
        )
        db.execute(
            text("""
                insert into verbatim_codes (id, verbatim_id, code_id, output_index, source, confidence_score, matched_alias, processing_run_id)
                select gen_random_uuid(), v.id, :code, 1, 'engine_fuzzy', :score, :alias, :run
                from verbatims v where v.mention_group_id = :gid
                on conflict (verbatim_id, code_id) do nothing
            """),
            insert_verbatim_codes_params,
        )
        db.execute(
            text("update verbatims set coding_status = 'auto_coded' where mention_group_id = :gid"),
            update_verbatims_params,
        )
    
    db.commit()

    db.execute(
        text("""
            update processing_runs
            set status = 'completed', finished_at = now(),
                total_verbatims = :total, auto_coded_count = :auto, anomalies_count = :anom
            where id = :id
        """),
        {"total": len(groups), "auto": auto_coded, "anom": anomalies, "id": run_id},
    )
    db.commit()

    return {"run_id": str(run_id), "groups_classified": auto_coded, "anomalies": anomalies, "total": len(groups)}


def _prefilter_garbage(db: Session, studio_id: uuid.UUID) -> int:
    # Ruido real (largo <= 2 o números sueltos): no hay nada que resolver, a revisión manual.
    garbage_res = db.execute(
        text("""
            update mention_groups
            set status = 'anomaly'
            where studio_id = :studio
            and status = 'pending_review'
            and (
                length(normalized_text) <= 2
                or normalized_text in ('uno', 'dos', 'tres')
            )
        """),
        {"studio": studio_id},
    )

    # "ninguna"/"no sabe"/"no recuerda" y sus variantes (SYSTEM_ALIAS_VARIANTS) sí
    # dicen algo: van directo a su código de sistema (96/98/99), auto_coded, en vez
    # de esperar revisión manual en la cola.
    resolved = 0
    cb_id = _current_codebook_id(db, studio_id)
    if cb_id is not None:
        system_codes = db.execute(
            text("select id, system_type from codes where codebook_id = :cb and is_system = true"),
            {"cb": cb_id},
        ).mappings().all()
        code_by_type = {c["system_type"]: c["id"] for c in system_codes}

        for system_type, variants in SYSTEM_ALIAS_VARIANTS.items():
            code_id = code_by_type.get(system_type)
            if not code_id:
                continue
            groups = db.execute(
                text("""
                    select id from mention_groups
                    where studio_id = :studio and status = 'pending_review'
                    and normalized_text = any(:variants)
                """),
                {"studio": studio_id, "variants": list(variants)},
            ).mappings().all()
            if not groups:
                continue
            group_ids = [g["id"] for g in groups]

            db.execute(
                text("""
                    update mention_groups
                    set status = 'auto_coded', suggested_code_id = :code
                    where id = any(:ids)
                """),
                {"code": code_id, "ids": group_ids},
            )
            db.execute(
                text("""
                    insert into verbatim_codes (id, verbatim_id, code_id, output_index, source, confidence_score, matched_alias)
                    select gen_random_uuid(), v.id, :code, 1, 'engine_exact', 1.0, v.normalized_text
                    from verbatims v where v.mention_group_id = any(:ids)
                    on conflict (verbatim_id, code_id) do nothing
                """),
                {"code": code_id, "ids": group_ids},
            )
            db.execute(
                text("update verbatims set coding_status = 'auto_coded' where mention_group_id = any(:ids)"),
                {"ids": group_ids},
            )
            resolved += len(group_ids)

    return garbage_res.rowcount + resolved


def process_studio(db: Session, studio_id: uuid.UUID, threshold: float = SCORE_THRESHOLD) -> dict:
    coding_type = db.execute(
        text("select coding_type from studio where id = :id"), {"id": studio_id}
    ).scalar()
    if coding_type is None:
        raise LookupError(f"Studio no encontrado: {studio_id}")

    # Step 0: Bypass LLM for obvious garbage strings to save cost and reduce noise
    filtered_count = _prefilter_garbage(db, studio_id)

    # Step 1: Run fuzzy matching to auto-code exact/close matches from the catalog
    fuzzy_result = _process_brands(db, studio_id, threshold)

    # Step 2: Whatever didn't match stays 'pending_review'. Hand those to the LLM.
    llm_result = classify_studio(db, studio_id)
    
    result = {
        "run_id": fuzzy_result["run_id"],
        "llm_run_id": llm_result["run_id"],
        "groups_classified": fuzzy_result["groups_classified"] + llm_result["groups_classified"],
        "anomalies": llm_result["anomalies"],
        "total": fuzzy_result["total"],
    }

    db.execute(
        text("update studio set status = 'preliminary_ready', updated_at = now() where id = :id"),
        {"id": studio_id},
    )
    db.commit()
    return result

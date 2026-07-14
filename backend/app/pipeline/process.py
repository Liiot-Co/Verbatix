"""Fase 2 — "el motor propone". Dispatcha por coding_type del estudio (Study):

  brands  -> fuzzy contra el catálogo de aliases (pipeline.fuzzy)
  reasons -> LLM structured output (pipeline.llm.classify_round)

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
from app.pipeline.fuzzy.models import Cols, SCORE_THRESHOLD
from app.pipeline.llm import classify_round


def _process_brands(db: Session, round_id: uuid.UUID, threshold: float) -> dict:
    groups = db.execute(
        text("""
            select id, normalized_text from mention_groups
            where round_id = :round and status = 'pending_review'
        """),
        {"round": round_id},
    ).mappings().all()

    # El catálogo sale del codebook cuando existe. Si la ronda no trae libro de
    # códigos, se deriva de la frecuencia: las marcas que superan el mínimo de
    # menciones se vuelven semillas y el fuzzy arrastra sus typos hacia ellas.
    catalog = load_catalog_aliases(db, round_id)
    min_mentions = None
    if not catalog:
        min_mentions = db.execute(
            text("select min_mentions_threshold from rounds where id = :round"),
            {"round": round_id},
        ).scalar()
        catalog = discover_catalog_from_frequency(db, round_id, min_mentions, threshold)

    run_id = uuid.uuid4()
    db.execute(
        text("""
            insert into processing_runs (id, round_id, run_type, algorithm, min_mentions_threshold, status, started_at)
            values (:id, :round, 'initial', :algo, :thr, 'running', now())
        """),
        {
            "id": run_id,
            "round": round_id,
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


def _prefilter_garbage(db: Session, round_id: uuid.UUID) -> int:
    # Filter short strings or meaningless stopwords
    res = db.execute(
        text("""
            update mention_groups
            set status = 'anomaly'
            where round_id = :round
            and status = 'pending_review'
            and (
                length(normalized_text) <= 2
                or normalized_text in ('uno', 'dos', 'tres', 'ninguna', 'nada', 'no se', 'ninguno', 'na', 'nc')
            )
        """),
        {"round": round_id},
    )
    return res.rowcount


def process_round(db: Session, round_id: uuid.UUID, threshold: float = SCORE_THRESHOLD) -> dict:
    coding_type = db.execute(
        text("""
            select st.coding_type
            from rounds r
            join studio st on st.id = r.studio_id
            where r.id = :id
        """),
        {"id": round_id},
    ).scalar()
    if coding_type is None:
        raise LookupError(f"Ronda no encontrada: {round_id}")

    # Step 0: Bypass LLM for obvious garbage strings to save cost and reduce noise
    filtered_count = _prefilter_garbage(db, round_id)

    # Step 1: Run fuzzy matching to auto-code exact/close matches from the catalog
    fuzzy_result = _process_brands(db, round_id, threshold)

    # Step 2: Whatever didn't match stays 'pending_review'. Hand those to the LLM.
    llm_result = classify_round(db, round_id)

    result = {
        "run_id": fuzzy_result["run_id"],
        "llm_run_id": llm_result["run_id"],
        "groups_classified": fuzzy_result["groups_classified"] + llm_result["groups_classified"],
        "anomalies": llm_result["anomalies"],
        "total": fuzzy_result["total"],
    }

    db.execute(
        text("update rounds set status = 'preliminary_ready', updated_at = now() where id = :id"),
        {"id": round_id},
    )
    db.commit()
    return result

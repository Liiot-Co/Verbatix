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
from app.pipeline.fuzzy.models import Cols, SCORE_THRESHOLD, SYSTEM_ALIAS_VARIANTS
from app.pipeline.llm import classify_round
from app.pipeline.semantic import cache as semantic_cache


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


def _apply_semantic_cache(db: Session, round_id: uuid.UUID, coding_type: str) -> dict:
    """Antes de mandar razones al LLM, busca cada mention_group pendiente en el
    caché semántico (Task C2 lo escribe): un hit por encima del umbral se
    auto-codifica sin tocar el LLM. Solo aplica a razones — para marcas el
    catálogo fuzzy ya cumple ese rol (ver fuzzy/matcher.py).
    """
    if coding_type != "reasons":
        return {"groups_classified": 0}

    # Import local: mismo motivo que en _prefilter_garbage (evita import circular).
    from app.repositories import _current_codebook_id

    codebook_id = _current_codebook_id(db, round_id)
    if codebook_id is None:
        return {"groups_classified": 0}

    # Arranque en caliente (Task C4): una ronda homologada busca también en el
    # codebook de su ronda origen, para tener hits desde el primer procesamiento
    # en vez de esperar a que su propio caché se llene.
    codebook_ids = [codebook_id]
    round_row = db.execute(
        text("select origin_mode, source_round_id from rounds where id = :id"),
        {"id": round_id},
    ).mappings().first()
    if round_row and round_row["origin_mode"] == "homologated" and round_row["source_round_id"]:
        source_codebook_id = _current_codebook_id(db, round_row["source_round_id"])
        if source_codebook_id:
            codebook_ids.append(source_codebook_id)

    groups = db.execute(
        text("""
            select id, normalized_text from mention_groups
            where round_id = :round and status = 'pending_review'
        """),
        {"round": round_id},
    ).mappings().all()

    hits = []
    for g in groups:
        match = semantic_cache.lookup(db, codebook_ids, g["normalized_text"])
        if not match:
            continue
        code_id = match["code_id"]
        if match["codebook_id"] != codebook_id:
            # code_id no se comparte entre codebooks clonados (ver
            # repositories.clone_codebook) — hay que remapear al code
            # equivalente en el propio codebook de esta ronda. Sin match, la
            # ronda origen no tiene un code inherited de ese id: se deja pasar
            # al LLM en vez de escribir una referencia cruzada inválida.
            own_code_id = db.execute(
                text("select id from codes where codebook_id = :cb and inherited_from_code_id = :src"),
                {"cb": codebook_id, "src": code_id},
            ).scalar()
            if own_code_id is None:
                continue
            code_id = own_code_id
        hits.append({"id": g["id"], "code": code_id, "score": match["similarity"]})

    if not hits:
        return {"groups_classified": 0}

    run_id = uuid.uuid4()
    db.execute(
        text("""
            insert into processing_runs (id, round_id, run_type, algorithm, status, started_at)
            values (:id, :round, 'initial', 'semantic_cache', 'running', now())
        """),
        {"id": run_id, "round": round_id},
    )
    db.execute(
        text("""
            update mention_groups
            set status = 'auto_coded', suggested_code_id = :code, created_by_run_id = :run
            where id = :id
        """),
        [{"code": h["code"], "run": run_id, "id": h["id"]} for h in hits],
    )
    db.execute(
        text("""
            insert into verbatim_codes (id, verbatim_id, code_id, output_index, source, confidence_score, processing_run_id)
            select gen_random_uuid(), v.id, :code, 1, 'semantic_cache', :score, :run
            from verbatims v where v.mention_group_id = :id
            on conflict (verbatim_id, code_id) do nothing
        """),
        [{"code": h["code"], "score": h["score"], "run": run_id, "id": h["id"]} for h in hits],
    )
    db.execute(
        text("update verbatims set coding_status = 'auto_coded' where mention_group_id = :id"),
        [{"id": h["id"]} for h in hits],
    )
    db.execute(
        text("""
            update processing_runs
            set status = 'completed', finished_at = now(), total_verbatims = :total, auto_coded_count = :auto
            where id = :id
        """),
        {"total": len(groups), "auto": len(hits), "id": run_id},
    )
    db.commit()

    return {"groups_classified": len(hits)}


def _prefilter_garbage(db: Session, round_id: uuid.UUID) -> int:
    # Ruido real (largo <= 2 o números sueltos): no hay nada que resolver, a revisión manual.
    garbage_res = db.execute(
        text("""
            update mention_groups
            set status = 'anomaly'
            where round_id = :round
            and status = 'pending_review'
            and (
                length(normalized_text) <= 2
                or normalized_text in ('uno', 'dos', 'tres')
            )
        """),
        {"round": round_id},
    )

    # "ninguna"/"no sabe"/"no recuerda" y sus variantes (SYSTEM_ALIAS_VARIANTS) sí
    # dicen algo: van directo a su código de sistema (96/98/99), auto_coded, en vez
    # de esperar revisión manual en la cola.
    # Import local: app.repositories importa app.pipeline.normalize, que dispara
    # app.pipeline.__init__ (importa este módulo) — un import a nivel de módulo
    # aquí sería circular.
    from app.repositories import _current_codebook_id

    resolved = 0
    cb_id = _current_codebook_id(db, round_id)
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
                    where round_id = :round and status = 'pending_review'
                    and normalized_text = any(:variants)
                """),
                {"round": round_id, "variants": list(variants)},
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

    # Step 2 (reasons only): near-identical text already seen and LLM-approved
    # before -> auto-code from the semantic cache without spending an LLM call.
    cache_result = _apply_semantic_cache(db, round_id, coding_type)

    # Step 3: Whatever didn't match stays 'pending_review'. Hand those to the LLM.
    llm_result = classify_round(db, round_id)

    result = {
        "run_id": fuzzy_result["run_id"],
        "llm_run_id": llm_result["run_id"],
        "groups_classified": (
            fuzzy_result["groups_classified"] + cache_result["groups_classified"] + llm_result["groups_classified"]
        ),
        "anomalies": llm_result["anomalies"],
        "total": fuzzy_result["total"],
    }

    db.execute(
        text("update rounds set status = 'preliminary_ready', updated_at = now() where id = :id"),
        {"id": round_id},
    )
    db.commit()
    return result

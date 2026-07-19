"""Fase 2 — "el motor propone". Una Ronda tiene 1 o 2 Subproyectos (Marcas y/o
Razones, según qué coding_type trajeron sus archivos importados — sección 2.5 del
documento v8, actualizada: ya no se crean los 2 a ciegas) y cada uno se procesa por
separado, dispatchando por su propio coding_type:

  brands  -> fuzzy contra el catálogo de aliases (pipeline.fuzzy)
  reasons -> LLM structured output (pipeline.llm.classify_round)

Cuando una ronda tiene los 2 subproyectos, se procesan en paralelo (thread por
subproyecto, sesión de DB propia cada uno — mismo patrón que core/scheduler.py ya
usa para paralelizar rondas completas): son independientes entre sí (fuzzy vs LLM,
sin filas compartidas) y el LLM de razones es la parte lenta, así que no tiene
sentido esperar a que termine marcas antes de arrancarlo.
"""
from __future__ import annotations

import threading
import uuid

import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.pipeline.fuzzy import (
    discover_catalog_from_frequency,
    load_catalog_aliases,
    run_fuzzy_matching,
)
from app.pipeline.fuzzy.models import Cols, SCORE_THRESHOLD, SYSTEM_ALIAS_VARIANTS
from app.pipeline.llm import classify_round
from app.pipeline.semantic import cache as semantic_cache
from app.pipeline.semantic.cluster import discover_reason_catalog


def _process_brands(db: Session, subproject_id: uuid.UUID, threshold: float) -> dict:
    groups = db.execute(
        text("""
            select id, normalized_text from mention_groups
            where subproject_id = :sp and status = 'pending_review'
        """),
        {"sp": subproject_id},
    ).mappings().all()

    # El catálogo sale del codebook cuando existe. Si el subproyecto no trae libro
    # de códigos, se deriva de la frecuencia: las marcas que superan el mínimo de
    # menciones se vuelven semillas y el fuzzy arrastra sus typos hacia ellas.
    catalog = load_catalog_aliases(db, subproject_id)
    min_mentions = None
    if not catalog:
        # subprojects.min_mentions_threshold, no rounds — se captura en el
        # wizard al importar y vive por subproyecto (ver get_or_create_subproject).
        min_mentions = db.execute(
            text("select min_mentions_threshold from subprojects where id = :sp"),
            {"sp": subproject_id},
        ).scalar()
        catalog = discover_catalog_from_frequency(db, subproject_id, min_mentions, threshold)

    run_id = uuid.uuid4()
    db.execute(
        text("""
            insert into processing_runs (id, subproject_id, run_type, algorithm, min_mentions_threshold, status, started_at)
            values (:id, :sp, 'initial', :algo, :thr, 'running', now())
        """),
        {
            "id": run_id,
            "sp": subproject_id,
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


def _apply_semantic_cache(db: Session, subproject_id: uuid.UUID, coding_type: str) -> dict:
    """Antes de mandar razones al LLM, busca cada mention_group pendiente en el
    caché semántico (Task C2 lo escribe): un hit por encima del umbral se
    auto-codifica sin tocar el LLM. Solo aplica a razones — para marcas el
    catálogo fuzzy ya cumple ese rol (ver fuzzy/matcher.py).
    """
    if coding_type != "reasons":
        return {"groups_classified": 0}

    sp_row = db.execute(
        text("select codebook_id, round_id from subprojects where id = :sp"),
        {"sp": subproject_id},
    ).mappings().first()
    codebook_id = sp_row["codebook_id"] if sp_row else None
    if codebook_id is None:
        return {"groups_classified": 0}

    # Arranque en caliente (Task C4): un subproyecto homologado busca también en
    # el codebook del subproyecto equivalente (mismo coding_type) de su ronda
    # origen, para tener hits desde el primer procesamiento en vez de esperar a
    # que su propio caché se llene.
    codebook_ids = [codebook_id]
    round_row = db.execute(
        text("select origin_mode, source_round_id from rounds where id = :id"),
        {"id": sp_row["round_id"]},
    ).mappings().first()
    if round_row and round_row["origin_mode"] == "homologated" and round_row["source_round_id"]:
        source_codebook_id = db.execute(
            text("select codebook_id from subprojects where round_id = :round and coding_type = :ct"),
            {"round": round_row["source_round_id"], "ct": coding_type},
        ).scalar()
        if source_codebook_id:
            codebook_ids.append(source_codebook_id)

    groups = db.execute(
        text("""
            select id, normalized_text from mention_groups
            where subproject_id = :sp and status = 'pending_review'
        """),
        {"sp": subproject_id},
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
            # equivalente en el propio codebook de este subproyecto. Sin match,
            # el subproyecto origen no tiene un code inherited de ese id: se deja
            # pasar al LLM en vez de escribir una referencia cruzada inválida.
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
            insert into processing_runs (id, subproject_id, run_type, algorithm, status, started_at)
            values (:id, :sp, 'initial', 'semantic_cache', 'running', now())
        """),
        {"id": run_id, "sp": subproject_id},
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


def _prefilter_garbage(db: Session, subproject_id: uuid.UUID) -> int:
    # Ruido real (largo <= 2 o números sueltos): no hay nada que resolver, a revisión manual.
    garbage_res = db.execute(
        text("""
            update mention_groups
            set status = 'anomaly'
            where subproject_id = :sp
            and status = 'pending_review'
            and (
                length(normalized_text) <= 2
                or normalized_text in ('uno', 'dos', 'tres')
            )
        """),
        {"sp": subproject_id},
    )

    # "ninguna"/"no sabe"/"no recuerda" y sus variantes (SYSTEM_ALIAS_VARIANTS) sí
    # dicen algo: van directo a su código de sistema (96/98/99), auto_coded, en vez
    # de esperar revisión manual en la cola.
    resolved = 0
    cb_id = db.execute(
        text("select codebook_id from subprojects where id = :sp"),
        {"sp": subproject_id},
    ).scalar()
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
                    where subproject_id = :sp and status = 'pending_review'
                    and normalized_text = any(:variants)
                """),
                {"sp": subproject_id, "variants": list(variants)},
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


def _process_subproject(db: Session, subproject_id: uuid.UUID, coding_type: str, threshold: float) -> dict:
    """Un subproyecto (Marcas o Razones) de punta a punta: prefiltro -> motor
    correspondiente a su propio coding_type -> lo que quede pending_review al LLM."""
    _prefilter_garbage(db, subproject_id)

    if coding_type == "brands":
        # Marcas primero: fuzzy puro, determinista (ver docstring del módulo).
        # Para razones el fuzzy da falsos positivos (ver fuzzy/matcher.py) — esas
        # van directo al caché semántico + LLM, nunca al catálogo fuzzy.
        fuzzy_result = _process_brands(db, subproject_id, threshold)
    else:
        # Si el codebook de razones arranca vacío (from_scratch), poblarlo con
        # categorías reales antes del LLM — si no, classify_round solo tiene los
        # 5 códigos de sistema para elegir y casi todo cae en 97 "Otras
        # menciones" (bug real reportado en producción). Idempotente: no hace
        # nada si el codebook ya tiene contenido propio.
        min_mentions = db.execute(
            text("select min_mentions_threshold from subprojects where id = :sp"),
            {"sp": subproject_id},
        ).scalar()
        discover_reason_catalog(db, subproject_id, min_mentions or 3)
        fuzzy_result = {"run_id": None, "groups_classified": 0, "anomalies": 0, "total": 0}

    cache_result = _apply_semantic_cache(db, subproject_id, coding_type)

    # Lo que no matcheó por fuzzy/caché sigue 'pending_review'. Al LLM.
    llm_result = classify_round(db, subproject_id)

    return {
        "run_id": fuzzy_result["run_id"] or llm_result["run_id"],
        "llm_run_id": llm_result["run_id"],
        "groups_classified": (
            fuzzy_result["groups_classified"] + cache_result["groups_classified"] + llm_result["groups_classified"]
        ),
        "anomalies": llm_result["anomalies"],
        "total": fuzzy_result["total"] + llm_result["total"],
    }


def _process_subproject_worker(
    sp_id: uuid.UUID, coding_type: str, threshold: float,
    results: dict[uuid.UUID, dict], errors: dict[uuid.UUID, BaseException],
) -> None:
    """Un subproyecto de punta a punta con su propia sesión de DB (no la del
    caller) — para que dos subproyectos de la misma ronda puedan correr en threads
    distintos sin pisarse la conexión (SQLAlchemy Session no es thread-safe)."""
    db = SessionLocal()
    try:
        results[sp_id] = _process_subproject(db, sp_id, coding_type, threshold)
        db.commit()
    except BaseException as exc:  # noqa: BLE001 - se re-lanza en el hilo principal
        db.rollback()
        errors[sp_id] = exc
    finally:
        db.close()


def process_round(db: Session, round_id: uuid.UUID, threshold: float = SCORE_THRESHOLD) -> dict:
    """Resuelve los subproyectos de la ronda (Marcas y/o Razones, los que existan)
    y corre la clasificación de cada uno en paralelo, sumando sus estadísticas
    (sección 2.5 del documento v8: la unidad de procesamiento es el Subproyecto, no
    la Ronda). Mantiene la firma por round_id para minimizar cambios en callers."""
    subprojects = db.execute(
        text("select id, coding_type from subprojects where round_id = :round"),
        {"round": round_id},
    ).mappings().all()
    if not subprojects:
        raise LookupError(f"Ronda no encontrada o sin subproyectos: {round_id}")

    results: dict[uuid.UUID, dict] = {}
    errors: dict[uuid.UUID, BaseException] = {}
    workers = [
        threading.Thread(
            target=_process_subproject_worker,
            args=(sp["id"], sp["coding_type"], threshold, results, errors),
        )
        for sp in subprojects
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    if errors:
        # Sección 2.5: cualquier subproyecto que falle debe tumbar toda la ronda
        # (mismo comportamiento que la versión secuencial) — se relanza la
        # primera excepción encontrada, scheduler._mark_round_failed la captura.
        raise next(iter(errors.values()))

    ordered = [results[sp["id"]] for sp in subprojects]
    result = {
        "run_id": ordered[0]["run_id"],
        "llm_run_id": ordered[0]["llm_run_id"],
        "groups_classified": sum(r["groups_classified"] for r in ordered),
        "anomalies": sum(r["anomalies"] for r in ordered),
        "total": sum(r["total"] for r in ordered),
    }

    db.execute(
        text("update rounds set status = 'preliminary_ready', updated_at = now() where id = :id"),
        {"id": round_id},
    )
    db.commit()
    return result

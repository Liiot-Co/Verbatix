import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.llm.client import classify_batch
from app.pipeline.fuzzy.catalog import promote_llm_result_to_alias
from app.pipeline.normalize import normalize
from app.pipeline.semantic.cache import write as write_reason_cache
from app.core.config import settings

logger = logging.getLogger(__name__)

_RETRY_DELAY_SECONDS = 2.0


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _classify_batch_with_retry(codebook: list[dict], payload: list[dict], coding_type: str) -> list[dict]:
    """Un reintento ante fallo transitorio (red/timeout/JSON malformado) antes de
    rendir el batch: sin esto, un blip puntual mandaba 20 grupos a revisión humana."""
    try:
        return classify_batch(codebook, payload, coding_type)
    except Exception:
        logger.warning("Batch LLM falló (%d verbatims); reintentando una vez", len(payload))
        time.sleep(_RETRY_DELAY_SECONDS)
        return classify_batch(codebook, payload, coding_type)


def classify_round(db: Session, subproject_id: uuid.UUID) -> dict:
    """Classifies pending mention_groups of a subproject against its codebook using the local LLM.

    Reads the exact-match dedup groups that import already built (build_mention_groups),
    then resolves whatever's still 'pending_review' — the same engine serves reasons
    subprojects (all groups, triggered automatically after import) and the brand
    fuzzy-match leftovers (whatever a future alias-matching pass doesn't resolve), per
    docs/ideas/verbatix-sharpen.md.
    """
    run_id = uuid.uuid4()
    db.execute(
        text("""
            insert into processing_runs (id, subproject_id, run_type, algorithm, status, started_at)
            values (:id, :sp, 'initial', 'llm_structured_output', 'running', now())
        """),
        {"id": run_id, "sp": subproject_id},
    )
    db.commit()

    coding_type = db.execute(
        text("select coding_type from subprojects where id = :sp"),
        {"sp": subproject_id},
    ).scalar()

    # Solo el codebook del subproyecto (ya resuelto, sin necesidad de "latest
    # version" — subprojects.codebook_id apunta directo al vigente).
    codes = db.execute(
        text("""
            select c.id, c.code_number, c.label, n.name as net_name, c.system_type,
                   array(
                       select alias_sample from code_aliases a
                       where a.code_id = c.id and a.alias_sample is not null
                   ) as aliases
            from codes c
            join subprojects sp on sp.codebook_id = c.codebook_id
            left join net_codes nc on nc.code_id = c.id
            left join nets n on n.id = nc.net_id
            where sp.id = :sp and c.is_active
            order by c.code_number
        """),
        {"sp": subproject_id},
    ).mappings().all()
    codes_by_number = {c["code_number"]: c["id"] for c in codes}
    # system_type 'anomaly' (code 95, "Menciones confusas/Incorrectas") means the LLM itself
    # isn't sure the mention belongs to this question — that's exactly the case that needs a
    # human to confirm, so it must never auto-code no matter how confident the model claims to be.
    anomaly_code_ids = {c["id"] for c in codes if c.get("system_type") == "anomaly"}
    codebook_payload = [
        {
            "code_number": c["code_number"], 
            "label": c["label"], 
            "net": c["net_name"],
            "aliases": c["aliases"],
            "system_type": c["system_type"],
        } for c in codes
    ]

    groups = db.execute(
        text("""
            select id, sample_text from mention_groups
            where subproject_id = :sp and status = 'pending_review'
        """),
        {"sp": subproject_id},
    ).mappings().all()
    groups_by_id = {str(g["id"]): g for g in groups}

    auto_coded = 0
    anomalies = 0

    update_groups_params = []
    insert_verbatim_codes_params = []
    update_verbatims_params = []
    update_anomalies_groups = []
    update_anomalies_verbatims = []
    promotions = []
    reason_promotions = []

    # Los batches son independientes entre sí (cada uno lleva el codebook completo
    # y sus propios grupos), así que van al LLM en paralelo: el cuello de botella
    # es puro I/O de red (~20-25s por llamada). Los hilos SOLO hacen HTTP; toda la
    # decisión y escritura a DB queda en este hilo (la Session no es thread-safe).
    batches = list(_chunks(groups, settings.classification_batch_size))
    with ThreadPoolExecutor(max_workers=settings.llm_parallel_requests) as pool:
        futures = {
            pool.submit(
                _classify_batch_with_retry,
                codebook_payload,
                [{"id": str(g["id"]), "text": g["sample_text"]} for g in batch],
                coding_type,
            ): batch
            for batch in batches
        }
        batch_results: list[tuple[list, list[dict] | None]] = []
        for future in as_completed(futures):
            try:
                batch_results.append((futures[future], future.result()))
            except Exception:
                # Un batch que falla (aun tras el retry) no puede tumbar el run
                # entero: sus grupos van a revisión humana (anomaly) y seguimos con
                # el resto. Así la ronda siempre llega a un estado terminal, nunca
                # se queda "procesando" por un fallo del LLM.
                logger.exception("Batch LLM falló; %d grupos van a revisión", len(futures[future]))
                batch_results.append((futures[future], None))

    for batch, results in batch_results:
        if results is None:
            for g in batch:
                update_anomalies_groups.append({"run": run_id, "id": g["id"]})
                update_anomalies_verbatims.append({"id": g["id"]})
                anomalies += 1
            continue

        for result in results:
            group = groups_by_id.get(result["verbatim_id"])
            if group is None:
                continue
            group_id = group["id"]
            matched_code_ids = [codes_by_number[n] for n in result["code_numbers"] if n in codes_by_number]
            confidence = result.get("confidence")
            confidence_threshold = (
                settings.llm_confidence_threshold_brands
                if coding_type == "brands"
                else settings.llm_confidence_threshold_reasons
            )
            # No confidence in the response is treated as low confidence, not high — a case
            # the LLM won't rate shouldn't get auto-coded any more than one it rates poorly.
            below_threshold = confidence is None or confidence < confidence_threshold
            is_anomaly = any(cid in anomaly_code_ids for cid in matched_code_ids)

            if not matched_code_ids or below_threshold or is_anomaly:
                update_anomalies_groups.append({"run": run_id, "id": group_id})
                update_anomalies_verbatims.append({"id": group_id})
                anomalies += 1
                continue

            update_groups_params.append({"code": matched_code_ids[0], "run": run_id, "id": group_id})
            for idx, code_id in enumerate(matched_code_ids, start=1):
                insert_verbatim_codes_params.append({
                    "code": code_id,
                    "idx": idx,
                    "run": run_id,
                    "group_id": group_id
                })
            update_verbatims_params.append({"id": group_id})
            auto_coded += 1

            if confidence >= settings.llm_promotion_confidence_threshold:
                if coding_type == "brands":
                    # Para razones el fuzzy da falsos positivos (ver fuzzy/matcher.py)
                    # — esas van al caché semántico, no al catálogo fuzzy.
                    promotions.append({
                        "code_id": matched_code_ids[0],
                        "alias_normalized": normalize(group["sample_text"]),
                        "alias_sample": group["sample_text"],
                        "match_score": confidence,
                    })
                elif coding_type == "reasons":
                    reason_promotions.append({
                        "code_id": matched_code_ids[0],
                        "source_text": group["sample_text"],
                        "confidence": confidence,
                    })

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
                insert into verbatim_codes (id, verbatim_id, code_id, output_index, source, processing_run_id)
                select gen_random_uuid(), v.id, :code, :idx, 'llm_classified', :run
                from verbatims v where v.mention_group_id = :group_id
                on conflict (verbatim_id, code_id) do nothing
            """),
            insert_verbatim_codes_params,
        )
        db.execute(
            text("update verbatims set coding_status = 'auto_coded' where mention_group_id = :id"),
            update_verbatims_params,
        )

    if update_anomalies_groups:
        db.execute(
            text("update mention_groups set status = 'anomaly', created_by_run_id = :run where id = :id"),
            update_anomalies_groups,
        )
        db.execute(
            text("update verbatims set coding_status = 'needs_review' where mention_group_id = :id"),
            update_anomalies_verbatims,
        )

    for promotion in promotions:
        promote_llm_result_to_alias(
            db,
            code_id=promotion["code_id"],
            alias_normalized=promotion["alias_normalized"],
            alias_sample=promotion["alias_sample"],
            match_score=promotion["match_score"],
        )

    for reason_promotion in reason_promotions:
        write_reason_cache(
            db,
            code_id=reason_promotion["code_id"],
            source_text=reason_promotion["source_text"],
            confidence=reason_promotion["confidence"],
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

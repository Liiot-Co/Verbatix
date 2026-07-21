import logging
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.llm.client import PROMPT_VERSIONS, classify_batch
from app.pipeline.fuzzy.catalog import promote_llm_result_to_alias
from app.pipeline.normalize import normalize
from app.pipeline.question_controls import cap_codes_for_single_response
from app.pipeline.semantic.cache import write as write_reason_cache
from app.core.config import settings

logger = logging.getLogger(__name__)

_RETRY_DELAY_SECONDS = 2.0
POLICY_VERSION = "precision-v1-suggest-only"
PROMPT_VERSION = "classification-v2-generic"


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _classify_batch_with_retry(
    codebook: list[dict], payload: list[dict], coding_type: str,
    context: dict | None = None,
) -> list[dict]:
    """Un reintento ante fallo transitorio (red/timeout/JSON malformado) antes de
    rendir el batch: sin esto, un blip puntual mandaba 20 grupos a revisión humana."""
    try:
        return classify_batch(codebook, payload, coding_type, context)
    except Exception:
        logger.warning("Batch LLM falló (%d verbatims); reintentando una vez", len(payload))
        time.sleep(_RETRY_DELAY_SECONDS)
        return classify_batch(codebook, payload, coding_type, context)


def classify_round(db: Session, subproject_id: uuid.UUID) -> dict:
    """Classifies pending mention_groups of a subproject against its codebook using the local LLM.

    Reads the exact-match dedup groups that import already built (build_mention_groups),
    then resolves whatever's still 'pending_review' — the same engine serves reasons
    subprojects (all groups, triggered automatically after import) and the brand
    fuzzy-match leftovers (whatever a future alias-matching pass doesn't resolve), per
    docs/ideas/verbatix-sharpen.md.
    """
    started_monotonic = time.monotonic()
    run_id = uuid.uuid4()
    db.execute(
        text("""
            insert into processing_runs (
              id, subproject_id, run_type, algorithm, status, started_at,
              policy_version, prompt_version, model_name
            )
            values (
              :id, :sp, 'initial', 'deepseek_structured_suggestion', 'running', now(),
              :policy, :prompt, :model
            )
        """),
        {
            "id": run_id, "sp": subproject_id, "policy": POLICY_VERSION,
            "prompt": PROMPT_VERSION, "model": settings.llm_model,
        },
    )
    db.commit()

    coding_type = db.execute(
        text("select coding_type from subprojects where id = :sp"),
        {"sp": subproject_id},
    ).scalar()
    db.execute(
        text("update processing_runs set prompt_version = :prompt where id = :id"),
        {"prompt": PROMPT_VERSIONS.get(coding_type, PROMPT_VERSION), "id": run_id},
    )
    context_row = db.execute(
        text("""
            select p.name as study, p.external_code,
                   cat.name as product_category, sp.single_code_per_response
              from subprojects sp
              join rounds r on r.id = sp.round_id
              join projects p on p.id = r.project_id
              left join categories cat on cat.id = r.category_id
             where sp.id = :sp
        """),
        {"sp": subproject_id},
    ).mappings().first()
    study_context = dict(context_row) if context_row else {}

    # Solo el codebook del subproyecto (ya resuelto, sin necesidad de "latest
    # version" — subprojects.codebook_id apunta directo al vigente).
    codes = db.execute(
        text("""
            select c.id, c.code_number, c.label, c.definition,
                   c.inclusion_criteria, c.exclusion_criteria, c.examples,
                   c.is_system, n.name as net_name, c.system_type,
                   array(
                       select alias_sample from code_aliases a
                       where a.code_id = c.id and a.alias_sample is not null
                         and a.status = 'approved' and a.alias_kind in ('positive', 'system')
                   ) as aliases
            from codes c
            join subprojects sp on sp.codebook_id = c.codebook_id
            join codebooks cb on cb.id = c.codebook_id
            left join net_codes nc on nc.code_id = c.id
            left join nets n on n.id = nc.net_id
            where sp.id = :sp and c.is_active and c.approval_status = 'approved'
              and cb.status in ('approved', 'exported')
            order by c.code_number
        """),
        {"sp": subproject_id},
    ).mappings().all()
    codes_by_number = {c["code_number"]: c["id"] for c in codes}
    system_code_ids = {
        c["id"] for c in codes if c.get("is_system") or c.get("system_type")
    }
    # Códigos universales (95-99): el LLM puede auto-cerrarlos cuando declara
    # confianza alta — "no se"→96, teclazo→95, "otros"→97. Antes se abstenían
    # o quedaban solo como sugerencia y el analista perdía tiempo en ruido.
    system_type_by_id = {
        c["id"]: c.get("system_type") for c in codes if c.get("system_type")
    }
    codebook_payload = [
        {
            "code_number": c["code_number"], 
            "label": c["label"], 
            "net": c["net_name"],
            "aliases": c["aliases"],
            "system_type": c["system_type"],
            "definition": c.get("definition"),
            "inclusion_criteria": c.get("inclusion_criteria") or [],
            "exclusion_criteria": c.get("exclusion_criteria") or [],
            "examples": c.get("examples") or [],
        } for c in codes
    ]

    groups = db.execute(
        text("""
            select mg.id, mg.sample_text, mg.frequency_count,
                   array(
                     select distinct coalesce(q.display_label, q.question_key)
                     from verbatims v join questions q on q.id = v.question_id
                     where v.mention_group_id = mg.id
                   ) as questions,
                   array(
                     select distinct v.original_text from verbatims v
                     where v.mention_group_id = mg.id limit 5
                   ) as surface_forms
            from mention_groups mg
            where mg.subproject_id = :sp and mg.status = 'pending_review'
        """),
        {"sp": subproject_id},
    ).mappings().all()
    groups_by_id = {str(g["id"]): g for g in groups}
    single_code = bool(db.execute(
        text("select single_code_per_response from subprojects where id = :sp"),
        {"sp": subproject_id},
    ).scalar())

    suggestions = 0
    auto_coded = 0
    abstentions = 0
    engine_errors = 0

    update_groups_params = []
    insert_verbatim_codes_params = []
    update_verbatims_params = []
    update_abstained_groups = []
    update_abstained_verbatims = []
    update_error_groups = []
    update_error_verbatims = []
    promotions = []
    reason_promotions = []
    structured_decisions: list[dict] = []

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
                [{
                    "id": str(g["id"]), "text": g["sample_text"],
                    "frequency": g.get("frequency_count"),
                    "questions": g.get("questions") or [],
                    "surface_forms": g.get("surface_forms") or [],
                } for g in batch],
                coding_type,
                study_context,
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
                update_error_groups.append({"run": run_id, "id": g["id"]})
                update_error_verbatims.append({"id": g["id"]})
                engine_errors += 1
                structured_decisions.append({
                    "group_id": str(g["id"]), "decision": "engine_error",
                    "code_numbers": [], "confidence": None,
                })
            continue

        for result in results:
            group = groups_by_id.get(result["verbatim_id"])
            if group is None:
                continue
            group_id = group["id"]
            structured_decisions.append({
                "group_id": result["verbatim_id"],
                "decision": result.get("decision"),
                "code_numbers": result.get("code_numbers") or [],
                "ordered_ideas": result.get("ordered_ideas") or [],
                "evidence": result.get("evidence") or "",
                "ambiguity_reason": result.get("ambiguity_reason"),
                "confidence": result.get("confidence"),
            })
            matched_code_ids = [codes_by_number[n] for n in result["code_numbers"] if n in codes_by_number]
            matched_rows = [
                {"id": cid, "is_system": cid in system_code_ids}
                for cid in matched_code_ids
            ]
            matched_rows = cap_codes_for_single_response(
                matched_rows,
                single_code=single_code,
            )
            matched_code_ids = [row["id"] for row in matched_rows]
            confidence = result.get("confidence")
            confidence_threshold = (
                settings.llm_confidence_threshold_brands
                if coding_type == "brands"
                else settings.llm_confidence_threshold_reasons
            )
            # Sin confianza declarada = baja confianza: no auto-cerrar.
            below_threshold = confidence is None or confidence < confidence_threshold
            # Sin códigos → abstención (revisión humana / residual).
            # Con códigos de sistema (95-99) o de contenido: auto-cierre si la
            # confianza supera el umbral. Los universales son deterministas
            # cuando el modelo está seguro (ahorra cola en Resolución).
            if not matched_code_ids:
                update_abstained_groups.append({
                    "run": run_id,
                    "code": None,
                    "id": group_id,
                })
                update_abstained_verbatims.append({"id": group_id})
                abstentions += 1
                continue

            auto_commit = (
                settings.auto_commit_llm
                and not below_threshold
            )
            state = "auto_coded" if auto_commit else "suggested"
            update_groups_params.append({
                "code": matched_code_ids[0], "run": run_id, "id": group_id,
                "confidence": confidence, "below_threshold": below_threshold,
                "state": state,
            })
            for idx, code_id in enumerate(matched_code_ids, start=1):
                insert_verbatim_codes_params.append({
                    "code": code_id,
                    "idx": idx,
                    "run": run_id,
                    "group_id": group_id,
                    "confidence": confidence,
                    "active": auto_commit,
                })
            update_verbatims_params.append({"id": group_id, "state": state})
            if auto_commit:
                auto_coded += 1
            else:
                suggestions += 1

            # No promover aliases fuzzy desde códigos de sistema (ruido → 95, etc.).
            only_system = all(
                system_type_by_id.get(cid) is not None for cid in matched_code_ids
            )
            if (
                confidence is not None
                and confidence >= settings.llm_promotion_confidence_threshold
                and not only_system
            ):
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
                set status = :state, suggested_code_id = :code, created_by_run_id = :run
                where id = :id
            """),
            update_groups_params,
        )
        db.execute(
            text("""
                insert into verbatim_codes (
                  id, verbatim_id, code_id, output_index, source,
                  confidence_score, processing_run_id, is_active
                )
                select gen_random_uuid(), v.id, :code, :idx, 'llm_suggestion',
                       :confidence, :run, :active
                from verbatims v where v.mention_group_id = :group_id
                on conflict (verbatim_id, code_id) do update set
                  confidence_score = excluded.confidence_score,
                  processing_run_id = excluded.processing_run_id,
                  is_active = excluded.is_active
            """),
            insert_verbatim_codes_params,
        )
        db.execute(
            text("update verbatims set coding_status = :state where mention_group_id = :id"),
            update_verbatims_params,
        )

    if update_abstained_groups:
        db.execute(
            text("""
                update mention_groups
                   set status = 'abstained', suggested_code_id = :code,
                       created_by_run_id = :run
                 where id = :id
            """),
            update_abstained_groups,
        )
        db.execute(
            text("update verbatims set coding_status = 'abstained' where mention_group_id = :id"),
            update_abstained_verbatims,
        )

    if update_error_groups:
        db.execute(
            text("""
                update mention_groups
                   set status = 'engine_error', created_by_run_id = :run
                 where id = :id
            """),
            update_error_groups,
        )
        db.execute(
            text("update verbatims set coding_status = 'engine_error' where mention_group_id = :id"),
            update_error_verbatims,
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
                total_verbatims = :verbatims, total_groups = :groups,
                auto_coded_count = :auto, anomalies_count = :abstained,
                metrics = jsonb_build_object(
                  'suggestions', :suggestions,
                  'auto_coded', :auto,
                  'abstentions', :abstained,
                  'engine_errors', :errors,
                  'latency_ms', :latency_ms,
                  'structured_decisions', cast(:decisions as jsonb)
                )
            where id = :id
        """),
        {
            "verbatims": sum(g.get("frequency_count", 1) for g in groups),
            "groups": len(groups),
            "auto": auto_coded,
            "suggestions": suggestions, "abstained": abstentions,
            "errors": engine_errors,
            "latency_ms": round((time.monotonic() - started_monotonic) * 1000),
            "decisions": json.dumps(structured_decisions, ensure_ascii=False),
            "id": run_id,
        },
    )
    db.commit()

    return {
        "run_id": str(run_id), "groups_classified": auto_coded,
        "suggestions": suggestions, "anomalies": abstentions,
        "engine_errors": engine_errors, "total": len(groups),
    }

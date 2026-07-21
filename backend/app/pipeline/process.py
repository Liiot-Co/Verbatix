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

import logging
import threading
import uuid
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.pipeline.fuzzy import (
    discover_catalog_from_frequency,
    discover_new_brands,
    load_catalog_aliases,
)
from app.pipeline.fuzzy.models import SCORE_THRESHOLD, SYSTEM_ALIAS_VARIANTS
from app.pipeline.fuzzy.scoring import best_brand_candidate, is_safe_brand_autocommit
from app.pipeline.llm import classify_round
from app.pipeline.llm.client import propose_brand_codes
from app.pipeline.normalize import normalize, strip_leading_article
from app.pipeline.semantic import cache as semantic_cache
from app.pipeline.semantic.cluster import discover_reason_catalog

logger = logging.getLogger(__name__)


def _canonicalize_brand_draft(db: Session, subproject_id: uuid.UUID) -> int:
    """Enriquece códigos de Marca pendientes; DeepSeek propone y el humano decide.

    Si el LLM falla, se conservan las semillas por frecuencia y la ronda sigue a
    codebook_review: la canonización es mejora, no requisito del bootstrap.
    """
    rows = db.execute(
        text("""
            select c.id, c.label, c.examples,
                   coalesce(sum(mg.frequency_count), 0) as mentions
              from subprojects sp
              join codes c on c.codebook_id = sp.codebook_id
              left join mention_groups mg on mg.suggested_code_id = c.id
             where sp.id = :sp and c.is_active and not c.is_system
               and c.approval_status = 'pending'
             group by c.id
             order by mentions desc, c.code_number
        """),
        {"sp": subproject_id},
    ).mappings().all()
    if not rows:
        return 0
    context_row = db.execute(
        text("""
            select p.name as study, p.external_code, cat.name as product_category
              from subprojects sp
              join rounds r on r.id = sp.round_id
              join projects p on p.id = r.project_id
              left join categories cat on cat.id = r.category_id
             where sp.id = :sp
        """),
        {"sp": subproject_id},
    ).mappings().first()
    summaries = [
        f"Etiqueta observada: {row['label']}. Variantes: {'; '.join(row['examples'] or [])}. "
        f"Frecuencia: {int(row['mentions'] or 0)}."
        for row in rows
    ]
    try:
        proposals = propose_brand_codes(summaries, dict(context_row) if context_row else {})
    except Exception:
        logger.exception(
            "Canonización DeepSeek falló para subproyecto %s; se usan semillas por frecuencia",
            subproject_id,
        )
        return len(rows)
    winner_by_label: dict[str, uuid.UUID] = {}
    for row, proposal in zip(rows, proposals, strict=True):
        normalized_label = normalize(proposal["label"])
        winner_id = winner_by_label.get(normalized_label)
        if winner_id is not None:
            # DeepSeek puede reconocer que dos clusters conservadores son la
            # misma marca (p.ej. cinco variantes de Gloria). Se fusionan solo
            # cuando propuso exactamente el mismo label canónico; los códigos
            # descartados quedan revocados, nunca se borran ni renumeran.
            db.execute(
                text("update mention_groups set suggested_code_id = :winner where suggested_code_id = :loser"),
                {"winner": winner_id, "loser": row["id"]},
            )
            db.execute(
                text("""
                    insert into code_aliases (
                      id, codebook_id, code_id, alias_normalized, alias_sample,
                      occurrences, origin, match_score, alias_kind, status,
                      normalization_version, evidence
                    )
                    select gen_random_uuid(), a.codebook_id, :winner,
                           a.alias_normalized, a.alias_sample, a.occurrences,
                           a.origin, a.match_score, a.alias_kind, a.status,
                           a.normalization_version, a.evidence
                      from code_aliases a where a.code_id = :loser
                    on conflict (codebook_id, alias_normalized, code_id) do update
                      set occurrences = greatest(code_aliases.occurrences, excluded.occurrences),
                          evidence = code_aliases.evidence || excluded.evidence
                """),
                {"winner": winner_id, "loser": row["id"]},
            )
            db.execute(
                text("update code_aliases set status = 'revoked', revoked_at = now() where code_id = :loser"),
                {"loser": row["id"]},
            )
            db.execute(
                text("update codes set approval_status = 'revoked', is_active = false where id = :loser"),
                {"loser": row["id"]},
            )
            continue
        winner_by_label[normalized_label] = row["id"]
        db.execute(
            text("""
                update codes
                   set label = :label,
                       definition = :definition,
                       inclusion_criteria = cast(:inclusions as jsonb),
                       exclusion_criteria = cast(:exclusions as jsonb)
                 where id = :id and approval_status = 'pending'
            """),
            {
                "id": row["id"], "label": proposal["label"],
                "definition": (
                    f"Canonización DeepSeek pendiente de aprobación. "
                    f"Ajuste de categoría: {proposal['category_fit']}. {proposal['rationale']}"
                ),
                "inclusions": '["Variantes confirmadas de esta marca dentro de la categoría del estudio"]',
                "exclusions": '["Palabras solo parecidas, otras marcas o pertenencia de categoría no confirmada"]',
            },
        )
    return len(winner_by_label)


def _process_brands(db: Session, subproject_id: uuid.UUID, threshold: float) -> dict:
    groups = db.execute(
        text("""
            select id, normalized_text, frequency_count from mention_groups
            where subproject_id = :sp and status = 'pending_review'
        """),
        {"sp": subproject_id},
    ).mappings().all()
    negative_rows = db.execute(
        text("""
            select a.alias_normalized, a.code_id::text as code_id
              from code_aliases a
              join subprojects sp on sp.codebook_id = a.codebook_id
             where sp.id = :sp and a.alias_kind = 'negative'
               and a.status = 'approved'
        """),
        {"sp": subproject_id},
    ).mappings().all()
    negative_targets: dict[str, set[str]] = {}
    for row in negative_rows:
        negative_targets.setdefault(row["alias_normalized"], set()).add(row["code_id"])

    # El catálogo ya debe estar aprobado. El bootstrap corre exclusivamente en
    # process_round antes de la barrera humana; esta etapa nunca crea códigos.
    catalog = load_catalog_aliases(db, subproject_id)
    min_mentions = None

    run_id = uuid.uuid4()
    db.execute(
        text("""
            insert into processing_runs (
              id, subproject_id, run_type, algorithm, min_mentions_threshold,
              status, started_at, policy_version
            )
            values (:id, :sp, 'initial', :algo, :thr, 'running', now(), :policy)
        """),
        {
            "id": run_id,
            "sp": subproject_id,
            "algo": "exact_then_brand_multisignal_suggest_v1",
            "thr": min_mentions,
            "policy": "brand-multisignal-suggest-v1",
        },
    )
    db.commit()

    aliases_by_text: dict[str, str] = {}
    for alias in catalog:
        aliases_by_text[alias.alias_normalized] = alias.code_id

    matched_by_group: dict[str, dict] = {}
    for group in groups:
        normalized = group["normalized_text"]
        # 'el paira'/'el prado': se prueba también la forma sin artículo inicial
        # para que calce con el código 'Paira'/'El Prado' aunque difiera el 'el'.
        stripped = strip_leading_article(normalized)
        exact_code = aliases_by_text.get(normalized)
        if exact_code is None and stripped != normalized:
            exact_code = aliases_by_text.get(stripped)
        if exact_code:
            matched_by_group[str(group["id"])] = {
                "code_id": exact_code, "score": 100.0,
                "matched_alias": normalized, "source": "engine_exact",
            }
            continue
        candidate = best_brand_candidate(normalized, catalog)
        used_stripped_form = False
        if candidate is None and stripped != normalized:
            candidate = best_brand_candidate(stripped, catalog)
            used_stripped_form = candidate is not None
        if candidate:
            matched_by_group[str(group["id"])] = {
                "code_id": candidate.code_id, "score": candidate.score,
                "matched_alias": candidate.alias, "source": "engine_fuzzy",
                "margin": candidate.margin,
                "candidate": candidate,
                "used_stripped_form": used_stripped_form,
            }

    auto_coded = 0
    suggestions = 0
    anomalies = 0

    update_groups_params = []
    insert_verbatim_codes_params = []
    update_verbatims_params = []

    for g in groups:
        gid = g["id"]
        match = matched_by_group.get(str(gid))
        if match and str(match["code_id"]) in negative_targets.get(g["normalized_text"], set()):
            match = None
        if match:
            is_exact = match["source"] == "engine_exact"
            if is_exact:
                auto_commit = settings.auto_commit_exact_approved
            else:
                # Auto-cierre de fuzzy solo si pasa el gate calibrado (score +
                # margen top1-top2), o la recuperación ortográfica conservadora
                # de un solo token. Se evalúa el texto ORIGINAL para que quitar
                # un artículo no habilite falsos positivos multipalabra.
                auto_commit = (
                    settings.auto_commit_brand_fuzzy
                    and is_safe_brand_autocommit(
                        g["normalized_text"],
                        match["candidate"],
                        score_threshold=settings.brand_fuzzy_autocommit_score,
                        margin_threshold=settings.brand_fuzzy_autocommit_margin,
                        used_stripped_form=match["used_stripped_form"],
                    )
                )
            state = "auto_coded" if auto_commit else "suggested"
            update_groups_params.append({
                "code": match["code_id"], "run": run_id, "id": gid, "status": state,
            })
            insert_verbatim_codes_params.append({
                "code": match["code_id"],
                "score": match["score"] / 100,
                "alias": match["matched_alias"],
                "source": match["source"],
                "run": run_id,
                "gid": gid,
                "active": auto_commit,
            })
            update_verbatims_params.append({"gid": gid, "status": state})
            if auto_commit:
                auto_coded += 1
            else:
                suggestions += 1
        else:
            anomalies += 1

    if update_groups_params:
        db.execute(
            text("""
                update mention_groups
                set status = :status, suggested_code_id = :code, created_by_run_id = :run
                where id = :id
            """),
            update_groups_params,
        )
        db.execute(
            text("""
                insert into verbatim_codes (id, verbatim_id, code_id, output_index, source,
                                            confidence_score, matched_alias, processing_run_id, is_active)
                select gen_random_uuid(), v.id, :code, 1, :source, :score,
                       :alias, :run, :active
                from verbatims v where v.mention_group_id = :gid
                on conflict (verbatim_id, code_id) do update set
                  confidence_score = excluded.confidence_score,
                  matched_alias = excluded.matched_alias,
                  processing_run_id = excluded.processing_run_id,
                  is_active = excluded.is_active
            """),
            insert_verbatim_codes_params,
        )
        db.execute(
            text("update verbatims set coding_status = :status where mention_group_id = :gid"),
            update_verbatims_params,
        )

    db.commit()

    db.execute(
        text("""
            update processing_runs
            set status = 'completed', finished_at = now(),
                total_verbatims = :verbatims, total_groups = :groups,
                auto_coded_count = :auto, anomalies_count = :anom,
                metrics = jsonb_build_object('suggestions', :suggestions)
            where id = :id
        """),
        {
            "verbatims": sum(g.get("frequency_count", 1) for g in groups),
            "groups": len(groups),
            "auto": auto_coded, "anom": anomalies, "suggestions": suggestions,
            "id": run_id,
        },
    )
    db.commit()

    return {
        "run_id": str(run_id), "groups_classified": auto_coded,
        "suggestions": suggestions, "anomalies": anomalies, "total": len(groups),
    }


def _apply_semantic_cache(db: Session, subproject_id: uuid.UUID, coding_type: str) -> dict:
    """Antes de mandar razones al LLM, busca cada mention_group pendiente en el
    caché semántico aprobado. Un hit solo genera una sugerencia inactiva; nunca
    auto-cierra mientras no exista una política temporalmente calibrada. Solo
    aplica a razones; Marcas usa su motor de candidatos especializado.
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

    # Todo hit que llega aquí ya superó semantic_cache_similarity_threshold
    # (semantic_cache.lookup lo filtra). Con auto_commit_semantic activo eso
    # basta para auto-cerrar; si no, queda como sugerencia inactiva.
    auto_commit = settings.auto_commit_semantic
    state = "auto_coded" if auto_commit else "suggested"

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
            set status = :state, suggested_code_id = :code, created_by_run_id = :run
            where id = :id
        """),
        [{"code": h["code"], "run": run_id, "id": h["id"], "state": state} for h in hits],
    )
    db.execute(
        text("""
            insert into verbatim_codes (id, verbatim_id, code_id, output_index, source,
                                        confidence_score, processing_run_id, is_active)
            select gen_random_uuid(), v.id, :code, 1, 'semantic_cache', :score, :run, :active
            from verbatims v where v.mention_group_id = :id
            on conflict (verbatim_id, code_id) do update set
              confidence_score = excluded.confidence_score,
              processing_run_id = excluded.processing_run_id,
              is_active = excluded.is_active
        """),
        [{"code": h["code"], "score": h["score"], "run": run_id, "id": h["id"], "active": auto_commit} for h in hits],
    )
    db.execute(
        text("update verbatims set coding_status = :state where mention_group_id = :id"),
        [{"id": h["id"], "state": state} for h in hits],
    )
    db.execute(
        text("""
            update processing_runs
            set status = 'completed', finished_at = now(), total_groups = :total,
                auto_coded_count = :auto, metrics = jsonb_build_object('suggestions', :suggestions)
            where id = :id
        """),
        {
            "total": len(groups),
            "auto": len(hits) if auto_commit else 0,
            "suggestions": 0 if auto_commit else len(hits),
            "id": run_id,
        },
    )
    db.commit()

    return {"groups_classified": 0, "suggestions": len(hits)}


def _contains_brand(text_value: str, approved_aliases: list[str]) -> bool:
    """Coincidencia por tokens completos; evita substrings tipo aro/huarochirano."""
    return any(
        len(alias) >= 4
        and re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text_value) is not None
        for alias in approved_aliases
    )


def _apply_brand_in_reason_rule(db: Session, subproject_id: uuid.UUID) -> dict:
    """Propone la categoría Marca/Nombre si una razón menciona una marca aprobada."""
    target = db.execute(
        text("""
            select c.id
              from subprojects rsp
              join codes c on c.codebook_id = rsp.codebook_id
             where rsp.id = :sp and c.is_active and c.approval_status = 'approved'
               and not c.is_system
               and (lower(c.label) like '%marca%' or lower(c.label) like '%nombre%')
             order by c.code_number
             limit 2
        """),
        {"sp": subproject_id},
    ).scalars().all()
    # Ambigüedad en el propio libro: no elige por orden accidental.
    if len(target) != 1:
        return {"groups_classified": 0, "suggestions": 0}

    aliases = db.execute(
        text("""
            select distinct a.alias_normalized
              from subprojects rsp
              join subprojects bsp on bsp.round_id = rsp.round_id and bsp.coding_type = 'brands'
              join codebooks bcb on bcb.id = bsp.codebook_id
              join code_aliases a on a.codebook_id = bcb.id
              join codes c on c.id = a.code_id
             where rsp.id = :sp and bcb.status in ('approved','exported')
               and a.status = 'approved' and a.alias_kind = 'positive'
               and c.is_active and c.approval_status = 'approved'
        """),
        {"sp": subproject_id},
    ).scalars().all()
    if not aliases:
        return {"groups_classified": 0, "suggestions": 0}

    groups = db.execute(
        text("""
            select id, normalized_text from mention_groups
             where subproject_id = :sp and status = 'pending_review'
        """),
        {"sp": subproject_id},
    ).mappings().all()
    hits = [group for group in groups if _contains_brand(group["normalized_text"], list(aliases))]
    if not hits:
        return {"groups_classified": 0, "suggestions": 0}

    code_id = target[0]
    db.execute(
        text("""
            update mention_groups set status = 'suggested', suggested_code_id = :code
             where id = :id
        """),
        [{"code": code_id, "id": group["id"]} for group in hits],
    )
    db.execute(
        text("""
            insert into verbatim_codes (
              id, verbatim_id, code_id, output_index, source, is_active
            )
            select gen_random_uuid(), v.id, :code, 1, 'rule_brand_in_reason', false
              from verbatims v where v.mention_group_id = :id
            on conflict (verbatim_id, code_id) do update set
              source = 'rule_brand_in_reason', is_active = false
        """),
        [{"code": code_id, "id": group["id"]} for group in hits],
    )
    db.execute(
        text("update verbatims set coding_status = 'suggested' where mention_group_id = :id"),
        [{"id": group["id"]} for group in hits],
    )
    return {"groups_classified": 0, "suggestions": len(hits)}


_VOWELS = set("aeiouáéíóúü")


def _token_letter_stats(token: str) -> tuple[float, int, int]:
    """(vowel_ratio, max_consonant_run, letter_count) de un token alfabético."""
    letters = [ch for ch in token if ch.isalpha()]
    if not letters:
        return 1.0, 0, 0
    vowel_ratio = sum(1 for ch in letters if ch in _VOWELS) / len(letters)
    max_run = run = 0
    for ch in letters:
        run = 0 if ch in _VOWELS else run + 1
        max_run = max(max_run, run)
    return vowel_ratio, max_run, len(letters)


def _is_gibberish(text_value: str) -> bool:
    """Teclazos aleatorios / cadenas sin estructura de palabra.

    Cubre tanto una sola palabra ('lñksadjfdshwhef', 'lkjfksdñajfdsk') como
    mash multi-token ('kjsdañfdsk jdsfj n a'). Conservador: no marca marcas
    reales ni typos normales (schugur, gloriq, queso paira).
    """
    t = (text_value or "").strip().lower()
    if not t:
        return False

    tokens = [tok for tok in t.split() if tok]
    # Respuestas tipo "n a" / "a b c": ruido sin contenido, no una marca.
    if tokens and all(len(tok) <= 1 for tok in tokens):
        return True

    # Analizar letras ignorando espacios (el mash multi-palabra suele llevarlos).
    compact = "".join(ch for ch in t if not ch.isspace())
    vowel_ratio, max_run, n_letters = _token_letter_stats(compact)
    if n_letters < 6:
        return False

    # Si hay ≥2 tokens con pinta de palabra real (vocales + longitud), no es basura.
    realish = 0
    for tok in tokens:
        vr, run, n = _token_letter_stats(tok)
        if n >= 3 and vr >= 0.28 and run < 5:
            realish += 1
    if realish >= 2:
        return False

    return vowel_ratio < 0.22 or max_run >= 5


def _prefilter_garbage(db: Session, subproject_id: uuid.UUID) -> int:
    # "ninguna"/"no sabe"/"otros"/"no recuerda" y sus variantes (SYSTEM_ALIAS_VARIANTS)
    # sí dicen algo: van directo a su código de sistema (96/97/98/99), auto_coded.
    resolved = 0
    cb_id = db.execute(
        text("select codebook_id from subprojects where id = :sp"),
        {"sp": subproject_id},
    ).scalar()
    if cb_id is None:
        return 0

    system_codes = db.execute(
        text("select id, system_type from codes where codebook_id = :cb and is_system = true"),
        {"cb": cb_id},
    ).mappings().all()
    code_by_type = {c["system_type"]: c["id"] for c in system_codes}
    anomaly_code_id = code_by_type.get("anomaly")

    # Ruido corto (largo <= 2 o números sueltos): si hay código 95, auto-codificar;
    # si no, marcar anomaly para que el residual/humano lo vea.
    if anomaly_code_id is not None:
        short_groups = db.execute(
            text("""
                select id from mention_groups
                where subproject_id = :sp
                  and status = 'pending_review'
                  and (
                    length(normalized_text) <= 2
                    or normalized_text in ('uno', 'dos', 'tres')
                  )
            """),
            {"sp": subproject_id},
        ).mappings().all()
        short_ids = [g["id"] for g in short_groups]
        if short_ids:
            db.execute(
                text("""
                    update mention_groups
                    set status = 'auto_coded', suggested_code_id = :code
                    where id = any(:ids)
                """),
                {"code": anomaly_code_id, "ids": short_ids},
            )
            db.execute(
                text("""
                    insert into verbatim_codes (id, verbatim_id, code_id, output_index, source, confidence_score, matched_alias, is_active)
                    select gen_random_uuid(), v.id, :code, 1, 'engine_rule', 1.0, v.normalized_text, true
                    from verbatims v where v.mention_group_id = any(:ids)
                    on conflict (verbatim_id, code_id) do update set is_active = true
                """),
                {"code": anomaly_code_id, "ids": short_ids},
            )
            db.execute(
                text("update verbatims set coding_status = 'auto_coded' where mention_group_id = any(:ids)"),
                {"ids": short_ids},
            )
            resolved += len(short_ids)
    else:
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
        resolved += garbage_res.rowcount or 0

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

    # Typos/variantes partidas de respuestas de sistema que el match exacto no
    # pesca ('ni guno' -> ninguno, 'no se ' partido): match difuso conservador
    # (sin espacios) contra las variantes canónicas. Bar alto y textos cortos
    # para no arrastrar marcas reales al 96/97/98/99.
    variant_to_code = [
        (variant.replace(" ", ""), code_by_type[system_type])
        for system_type, variants in SYSTEM_ALIAS_VARIANTS.items()
        if code_by_type.get(system_type)
        for variant in variants
    ]
    if variant_to_code:
        from rapidfuzz.distance import DamerauLevenshtein
        pending_sys = db.execute(
            text("""
                select id, normalized_text from mention_groups
                where subproject_id = :sp and status = 'pending_review'
                  and normalized_text <> '' and length(normalized_text) <= 15
            """),
            {"sp": subproject_id},
        ).mappings().all()
        fuzzy_sys: dict[object, list] = {}
        for g in pending_sys:
            despaced = g["normalized_text"].replace(" ", "")
            if len(despaced) < 4:
                continue
            best_code, best_sim = None, 0.0
            for variant_ds, code_id in variant_to_code:
                sim = DamerauLevenshtein.normalized_similarity(despaced, variant_ds)
                if sim > best_sim:
                    best_sim, best_code = sim, code_id
            if best_code is not None and best_sim >= 0.85:
                fuzzy_sys.setdefault(best_code, []).append(g["id"])
        for code_id, ids in fuzzy_sys.items():
            db.execute(
                text("update mention_groups set status = 'auto_coded', suggested_code_id = :code where id = any(:ids)"),
                {"code": code_id, "ids": ids},
            )
            db.execute(
                text("""
                    insert into verbatim_codes (id, verbatim_id, code_id, output_index, source, confidence_score, matched_alias)
                    select gen_random_uuid(), v.id, :code, 1, 'engine_fuzzy', 0.9, v.normalized_text
                    from verbatims v where v.mention_group_id = any(:ids)
                    on conflict (verbatim_id, code_id) do nothing
                """),
                {"code": code_id, "ids": ids},
            )
            db.execute(
                text("update verbatims set coding_status = 'auto_coded' where mention_group_id = any(:ids)"),
                {"ids": ids},
            )
            resolved += len(ids)

    # Basura evidente (teclazos aleatorios) -> código 95 "Menciones confusas/
    # Incorrectas" (system_type 'anomaly'), auto_coded, para que el analista no
    # pierda tiempo con ruido. Si el libro no tiene el código 95 (p.ej. razones
    # con solo 96-99), se deja pasar a fuzzy/LLM/residual sin tocar.
    if anomaly_code_id is not None:
        pending = db.execute(
            text("""
                select id, normalized_text from mention_groups
                where subproject_id = :sp and status = 'pending_review'
                  and normalized_text <> ''
            """),
            {"sp": subproject_id},
        ).mappings().all()
        gibberish_ids = [g["id"] for g in pending if _is_gibberish(g["normalized_text"])]
        if gibberish_ids:
            db.execute(
                text("""
                    update mention_groups
                    set status = 'auto_coded', suggested_code_id = :code
                    where id = any(:ids)
                """),
                {"code": anomaly_code_id, "ids": gibberish_ids},
            )
            db.execute(
                text("""
                    insert into verbatim_codes (id, verbatim_id, code_id, output_index, source, confidence_score, matched_alias, is_active)
                    select gen_random_uuid(), v.id, :code, 1, 'engine_rule', 1.0, v.normalized_text, true
                    from verbatims v where v.mention_group_id = any(:ids)
                    on conflict (verbatim_id, code_id) do update set is_active = true
                """),
                {"code": anomaly_code_id, "ids": gibberish_ids},
            )
            db.execute(
                text("update verbatims set coding_status = 'auto_coded' where mention_group_id = any(:ids)"),
                {"ids": gibberish_ids},
            )
            resolved += len(gibberish_ids)

    return resolved


def _apply_residual_confuso_bucket(
    db: Session, subproject_id: uuid.UUID, coding_type: str,
) -> int:
    """Bucket residual estilo Ascribe (última etapa, tras fuzzy/caché/LLM).

    Todo grupo que quedó SIN decisión — `pending_review`, `anomaly`, `abstained` o
    `engine_error`, y **sin** una sugerencia de código real — se cierra al código de
    sistema universal del estudio: Marcas → 95 "Menciones confusas/Incorrectas",
    Razones → 97 "Otras menciones". Así la ronda no deja verbatims sin clasificar
    (cobertura ~100%) y el analista solo reclasifica en Resolución lo que sea una
    marca real poco frecuente. Los grupos `suggested` NO se tocan: conservan la
    sugerencia real para que el humano la confirme, en vez de perderla en el 95.
    """
    if not settings.residual_to_confuso:
        return 0
    system_type = (
        settings.residual_brand_system_type
        if coding_type == "brands"
        else settings.residual_reason_system_type
    )
    code_id = db.execute(
        text("""
            select c.id from codes c
              join subprojects sp on sp.codebook_id = c.codebook_id
             where sp.id = :sp and c.is_system = true and c.system_type = :st
             limit 1
        """),
        {"sp": subproject_id, "st": system_type},
    ).scalar()
    if code_id is None:
        return 0

    groups = db.execute(
        text("""
            select id from mention_groups
             where subproject_id = :sp
               and status in ('pending_review', 'anomaly', 'abstained', 'engine_error')
               and suggested_code_id is null
        """),
        {"sp": subproject_id},
    ).scalars().all()
    if not groups:
        return 0
    group_ids = list(groups)

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
            insert into verbatim_codes (id, verbatim_id, code_id, output_index, source,
                                        confidence_score, matched_alias, is_active)
            select gen_random_uuid(), v.id, :code, 1, 'engine_rule', 1.0, v.normalized_text, true
            from verbatims v where v.mention_group_id = any(:ids)
            on conflict (verbatim_id, code_id) do update set is_active = true
        """),
        {"code": code_id, "ids": group_ids},
    )
    db.execute(
        text("update verbatims set coding_status = 'auto_coded' where mention_group_id = any(:ids)"),
        {"ids": group_ids},
    )
    return len(group_ids)


def _process_subproject(db: Session, subproject_id: uuid.UUID, coding_type: str, threshold: float) -> dict:
    """Un subproyecto (Marcas o Razones) de punta a punta: prefiltro -> motor
    correspondiente a su propio coding_type -> lo que quede pending_review al LLM."""
    _prefilter_garbage(db, subproject_id)

    if coding_type == "brands":
        # Marcas primero: fuzzy puro, determinista (ver docstring del módulo).
        # Para razones el fuzzy da falsos positivos (ver fuzzy/matcher.py) — esas
        # van directo al caché semántico + LLM, nunca al catálogo fuzzy.
        fuzzy_result = _process_brands(db, subproject_id, threshold)
        # Sobre lo que el catálogo heredado NO reconoció, proponer marcas nuevas por
        # frecuencia (wong 4>=3): nacen como código 'pending' a confirmar, no caen
        # al 95. En rondas scratch es no-op (ya descubrieron su catálogo).
        if settings.discover_new_brands_in_inherited_rounds:
            min_mentions = db.execute(
                text("select min_mentions_threshold from subprojects where id = :sp"),
                {"sp": subproject_id},
            ).scalar()
            new_brand_suggestions = discover_new_brands(db, subproject_id, min_mentions or 2)
            fuzzy_result["suggestions"] = (
                fuzzy_result.get("suggestions", 0) + new_brand_suggestions
            )
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
        discover_reason_catalog(db, subproject_id, min_mentions or 2)
        fuzzy_result = {
            "run_id": None, "groups_classified": 0, "suggestions": 0,
            "anomalies": 0, "total": 0,
        }

    brand_rule_result = (
        _apply_brand_in_reason_rule(db, subproject_id)
        if coding_type == "reasons"
        else {"groups_classified": 0, "suggestions": 0}
    )
    cache_result = _apply_semantic_cache(db, subproject_id, coding_type)

    # Lo que no matcheó por fuzzy/caché sigue 'pending_review'. Al LLM.
    llm_result = classify_round(db, subproject_id)

    # Última red de seguridad: lo que quedó sin decisión ni sugerencia real se cierra
    # al código universal de confuso (95 marcas / 97 razones). Garantiza cobertura.
    residual = _apply_residual_confuso_bucket(db, subproject_id, coding_type)
    db.commit()

    return {
        "run_id": fuzzy_result["run_id"] or llm_result["run_id"],
        "llm_run_id": llm_result["run_id"],
        "groups_classified": (
            fuzzy_result["groups_classified"] + cache_result["groups_classified"]
            + llm_result["groups_classified"] + residual
        ),
        "suggestions": (
            fuzzy_result.get("suggestions", 0)
            + brand_rule_result.get("suggestions", 0)
            + cache_result.get("suggestions", 0)
            + llm_result.get("suggestions", 0)
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
        text("""
            select sp.id, sp.coding_type, sp.min_mentions_threshold,
                   cb.status as codebook_status, cb.origin as codebook_origin
              from subprojects sp
              join codebooks cb on cb.id = sp.codebook_id
             where sp.round_id = :round
        """),
        {"round": round_id},
    ).mappings().all()
    if not subprojects:
        raise LookupError(f"Ronda no encontrada o sin subproyectos: {round_id}")

    unavailable_catalogs = [
        sp for sp in subprojects
        if sp["codebook_origin"] != "scratch"
        and sp["codebook_status"] not in ("approved", "exported")
    ]
    if unavailable_catalogs:
        db.execute(
            text("update rounds set status = 'files_uploaded', updated_at = now() where id = :id"),
            {"id": round_id},
        )
        db.commit()
        return {
            "run_id": None, "llm_run_id": None, "groups_classified": 0,
            "suggestions": 0, "anomalies": 0, "total": 0,
            "awaiting_client_catalog_confirmation": True,
        }

    # Un catálogo nuevo no se puede usar para clasificarse y validarse a sí
    # mismo. Primero construimos una propuesta trazable y detenemos la ronda;
    # solo una aprobación humana explícita vuelve a habilitar el motor.
    draft_scratch = [
        sp for sp in subprojects
        if sp["codebook_origin"] == "scratch"
        and sp["codebook_status"] not in ("approved", "exported")
    ]
    if draft_scratch:
        proposed = 0
        for sp in draft_scratch:
            minimum = sp["min_mentions_threshold"] or 2
            if sp["coding_type"] == "brands":
                discover_catalog_from_frequency(db, sp["id"], minimum, threshold)
                proposed += _canonicalize_brand_draft(db, sp["id"])
            else:
                proposed += discover_reason_catalog(db, sp["id"], minimum)

        if not settings.auto_approve_scratch_codebook:
            # Gate humano: se detiene la ronda hasta que un analista apruebe el
            # borrador (POST .../codebook-draft/approve reanuda el scheduler).
            db.execute(
                text("""
                    update subprojects
                       set status = 'codebook_review', updated_at = now()
                     where round_id = :round
                       and id = any(:ids)
                """),
                {"round": round_id, "ids": [sp["id"] for sp in draft_scratch]},
            )
            db.execute(
                text("update rounds set status = 'codebook_review', updated_at = now() where id = :id"),
                {"id": round_id},
            )
            db.commit()
            return {
                "run_id": None,
                "llm_run_id": None,
                "groups_classified": 0,
                "anomalies": 0,
                "total": 0,
                "proposed_codes": proposed,
                "awaiting_codebook_approval": True,
            }

        # Auto-aprobar la propuesta del bootstrap y seguir de corrido a la
        # clasificación (el analista corrige en Resolución). La cascada re-toma
        # los grupos ahora con el libro aprobado.
        from app.repositories import auto_approve_scratch_codebooks
        auto_approve_scratch_codebooks(
            db, round_id, [sp["id"] for sp in draft_scratch],
        )
        db.commit()

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
        "suggestions": sum(r.get("suggestions", 0) for r in ordered),
        "anomalies": sum(r["anomalies"] for r in ordered),
        "total": sum(r["total"] for r in ordered),
    }

    db.execute(
        text("update rounds set status = 'preliminary_ready', updated_at = now() where id = :id"),
        {"id": round_id},
    )
    db.commit()
    return result

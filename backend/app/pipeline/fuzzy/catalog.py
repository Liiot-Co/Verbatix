"""Arma el catálogo de aliases contra el que corre el matcher, leyendo el
codebook más reciente de la ronda (aliases explícitos + labels normalizados
como fallback).
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.normalize import normalize

from .models import (
    SCORE_THRESHOLD,
    SYSTEM_ALIAS_VARIANTS,
    CodeAlias,
)
from .scoring import best_brand_candidate


def load_catalog_aliases(db: Session, subproject_id: uuid.UUID) -> list[CodeAlias]:
    alias_rows = db.execute(
        text("""
            select ca.code_id::text as code_id, ca.alias_normalized
            from code_aliases ca
            join codes c on c.id = ca.code_id
            join codebooks cb on cb.id = ca.codebook_id
            join subprojects sp on sp.codebook_id = ca.codebook_id
            where sp.id = :sp
              and cb.status in ('approved', 'exported')
              and c.is_active and c.approval_status = 'approved'
              and ca.status = 'approved' and ca.alias_kind in ('positive', 'system')
              and ca.alias_normalized is not null and ca.alias_normalized <> ''
        """),
        {"sp": subproject_id},
    ).mappings().all()

    label_rows = db.execute(
        text("""
            select c.id::text as code_id, c.label
            from codes c
            join codebooks cb on cb.id = c.codebook_id
            join subprojects sp on sp.codebook_id = c.codebook_id
            where sp.id = :sp
              and cb.status in ('approved', 'exported')
              and c.approval_status = 'approved'
              and c.is_active
              and coalesce(c.is_system, false) = false
              and c.label is not null
              and trim(c.label) <> ''
        """),
        {"sp": subproject_id},
    ).mappings().all()

    seen: set[tuple[str, str]] = set()
    catalog: list[CodeAlias] = []

    def _add(code_id: str, alias: str) -> None:
        alias = (alias or "").strip()
        if not alias or (code_id, alias) in seen:
            return
        seen.add((code_id, alias))
        catalog.append(CodeAlias(code_id=code_id, alias_normalized=alias))

    for r in alias_rows:
        _add(r["code_id"], r["alias_normalized"])
    for r in label_rows:
        _add(r["code_id"], normalize(r["label"]))
    return catalog


def promote_llm_result_to_alias(
    db: Session,
    code_id: str,
    alias_normalized: str,
    alias_sample: str | None,
    match_score: float,
) -> None:
    """Promociona una marca clasificada por LLM sobre el umbral de promoción a
    alias fuzzy reutilizable, para que rondas futuras la capturen sin volver a
    tocar el LLM. codebook_id se resuelve desde code_id (no se pide al caller)
    porque classify.py ya conoce el code_id pero no arrastra codebook_id.
    Reprocesar el mismo texto no duplica fila: incrementa occurrences.
    """
    alias_normalized = (alias_normalized or "").strip()
    if not alias_normalized:
        return
    db.execute(
        text("""
            insert into code_aliases (id, codebook_id, code_id, alias_normalized,
                                      alias_sample, occurrences, origin, match_score,
                                      status, evidence)
            select gen_random_uuid(), c.codebook_id, :code, :norm, :sample, 1,
                   'llm_promoted', :score, 'pending',
                   jsonb_build_object('source', 'deepseek', 'self_confidence', :score)
            from codes c where c.id = :code
            on conflict (codebook_id, alias_normalized, code_id) do update
              set occurrences = code_aliases.occurrences + 1,
                  evidence = excluded.evidence
        """),
        {"code": code_id, "norm": alias_normalized, "sample": alias_sample, "score": match_score},
    )


def _brand_code_numbers(start: int, occupied: set[int] | None = None):
    """Genera números nuevos sin reciclar ni colisionar con filas existentes."""
    used = occupied or set()
    n = start
    while True:
        while n in used or 95 <= n <= 99:
            n += 1
        yield n
        n += 1


def discover_catalog_from_frequency(
    db: Session,
    subproject_id: uuid.UUID,
    min_mentions: int,
    threshold: float = SCORE_THRESHOLD,
) -> list[CodeAlias]:
    """Fallback cuando la ronda no trae codebook: deriva las marcas 'semilla'
    de la frecuencia.

    El mínimo de menciones se evalúa por CLUSTER, no por texto individual:
    variantes/typos de una misma marca se agrupan primero por similitud fuzzy
    entre sí (sin importar la frecuencia de cada una por separado) y luego se
    suman sus frecuencias. Sin esto, una marca real dicha de dos formas
    distintas (p.ej. 'kraf' 1 mención + 'kraft' 1 mención) se perdía entera:
    ninguna de las dos individualmente alcanzaba el mínimo, y al no compararse
    entre sí tampoco se detectaban como la misma marca — quedaban ambas sin
    código, en vez de una sola marca con 2 menciones.

    Filtros de precisión sobre el cluster ya formado:

    - Respuestas de sistema ("no se", "ninguna"...) no se promueven como marcas:
      se vuelven aliases del código de sistema (96/98/99) y el fuzzy las codifica
      directo ahí. Sin esto, al ser de los textos más frecuentes, terminaban como
      marcas falsas en el codebook.
    - Las variantes se agrupan con el scorer multiseñal conservador; WRatio
      aislado no une clusters y los textos de hasta cuatro caracteres quedan
      separados para evitar casos como Bone -> Bonlé.

    Con ese catálogo el fuzzy arrastra los typos poco frecuentes hacia las
    semillas; lo que no se parezca a ninguna sigue al LLM (flujo normal).

    Escribe codes/code_aliases pero no hace commit: el caller confirma junto con
    el resto del run. Idempotente por construcción — una vez creadas las semillas,
    load_catalog_aliases ya devuelve catálogo y este fallback no se vuelve a tomar.
    """
    codebook_id = db.execute(
        text("select codebook_id from subprojects where id = :sp"),
        {"sp": subproject_id},
    ).scalar()
    if codebook_id is None:
        return []

    has_candidates = db.execute(
        text("""
            select exists(
              select 1 from codes
               where codebook_id = :cb and not is_system and is_active
            )
        """),
        {"cb": codebook_id},
    ).scalar()
    if has_candidates:
        return []

    # Sin el corte por frequency_count aquí: se necesita ver TODOS los
    # candidatos para poder agruparlos entre sí antes de decidir qué cluster
    # alcanza el mínimo (ver docstring).
    candidates = db.execute(
        text("""
            select id, normalized_text, sample_text, frequency_count
            from mention_groups
            where subproject_id = :sp
              and status = 'pending_review'
              and normalized_text <> ''
            order by frequency_count desc, normalized_text
        """),
        {"sp": subproject_id},
    ).mappings().all()
    if not candidates:
        return []

    def _persist_alias(
        code_id,
        alias_normalized: str,
        alias_sample: str | None,
        occurrences: int | None,
        *,
        approved_system: bool = False,
    ) -> None:
        db.execute(
            text("""
                insert into code_aliases (id, codebook_id, code_id, alias_normalized,
                                          alias_sample, occurrences, origin,
                                          alias_kind, status, evidence, approved_at)
                values (:id, :cb, :code, :norm, :sample, :occ, 'engine_fuzzy',
                        :kind, :status, cast(:evidence as jsonb),
                        case when :status = 'approved' then now() else null end)
                on conflict (codebook_id, alias_normalized, code_id) do nothing
            """),
            {
                "id": uuid.uuid4(), "cb": codebook_id, "code": code_id,
                "norm": alias_normalized, "sample": alias_sample, "occ": occurrences,
                "kind": "system" if approved_system else "positive",
                "status": "approved" if approved_system else "pending",
                "evidence": '{"source":"bootstrap_frequency"}',
            },
        )

    catalog: list[CodeAlias] = []
    alias_to_code: dict[str, str] = {}

    # Aliases de los códigos de sistema del codebook (96/98/99): capturan las
    # respuestas "no sabe"/"ninguna"/"no recuerda" y sus variantes.
    system_rows = db.execute(
        text("""
            select id::text as code_id, system_type from codes
            where codebook_id = :cb and is_system and system_type is not null
        """),
        {"cb": codebook_id},
    ).mappings().all()
    system_aliases: list[str] = []
    for row in system_rows:
        for variant in SYSTEM_ALIAS_VARIANTS.get(row["system_type"], ()):
            _persist_alias(row["code_id"], variant, None, None, approved_system=True)
            catalog.append(CodeAlias(code_id=row["code_id"], alias_normalized=variant))
            alias_to_code[variant] = row["code_id"]
            system_aliases.append(variant)

    # Numeración correlativa a partir del último code de marca no-system,
    # respetando cualquier código ya presente en el libro.
    next_number = db.execute(
        text("""
            select coalesce(max(code_number), 0) + 1 from codes
            where codebook_id = :cb and coalesce(is_system, false) = false
        """),
        {"cb": codebook_id},
    ).scalar()
    occupied_rows = db.execute(
        text("select code_number from codes where codebook_id = :cb"),
        {"cb": codebook_id},
    ).mappings().all()
    occupied = {row["code_number"] for row in occupied_rows}
    numbers = _brand_code_numbers(next_number, occupied)

    # Fase 1: agrupar candidatos por similitud fuzzy entre sí, sin filtrar
    # todavía por mínimo de menciones. Recorridos en orden de frecuencia desc.
    # (ya viene así de la query) para que el representante de cada cluster sea
    # su miembro más frecuente.
    cluster_reprs: list[str] = []
    clusters: dict[str, list] = {}
    for cand in candidates:
        norm = cand["normalized_text"]

        # Respuesta de sistema disfrazada de marca -> alias de 96/98/99, nunca
        # entra al clustering de marcas.
        if norm in alias_to_code and norm in system_aliases:
            code_id = alias_to_code[norm]
            _persist_alias(
                code_id, norm, cand["sample_text"], cand["frequency_count"],
                approved_system=True,
            )
            catalog.append(CodeAlias(code_id=code_id, alias_normalized=norm))
            continue

        cluster_hit = best_brand_candidate(
            norm,
            [CodeAlias(code_id=representative, alias_normalized=representative) for representative in cluster_reprs],
        )
        if cluster_hit:
            clusters[cluster_hit.code_id].append(cand)
        else:
            clusters[norm] = [cand]
            cluster_reprs.append(norm)

    # Fase 2: solo se promueven a code nuevo los clusters cuya frecuencia
    # SUMADA alcanza el mínimo — el resto sigue como pending_review para el LLM.
    for representative, members in clusters.items():
        total = sum(m["frequency_count"] for m in members)
        if total < min_mentions:
            continue

        code_id = str(uuid.uuid4())
        raw_label = representative
        for m in members:
            if m["normalized_text"] == representative and m["sample_text"]:
                raw_label = m["sample_text"]
                break
        formatted_label = raw_label.strip().capitalize() if raw_label else raw_label
        db.execute(
            text("""
                insert into codes (
                  id, codebook_id, code_number, label, definition, examples,
                  origin, approval_status
                )
                values (
                  :id, :cb, :n, :label, :definition, cast(:examples as jsonb),
                  'engine_auto', 'pending'
                )
            """),
            {
                "id": code_id, "cb": codebook_id, "n": next(numbers),
                "label": formatted_label,
                "definition": f"Categoría candidata agrupada desde {total} menciones del DAU.",
                "examples": json.dumps(
                    [m["sample_text"] or m["normalized_text"] for m in members[:5]]
                ),
            },
        )
        for m in members:
            norm = m["normalized_text"]
            _persist_alias(code_id, norm, m["sample_text"], m["frequency_count"])
            catalog.append(CodeAlias(code_id=code_id, alias_normalized=norm))
            alias_to_code[norm] = code_id
        db.execute(
            text("""
                update mention_groups
                   set status = 'suggested', suggested_code_id = :code
                 where id = any(:ids)
            """),
            {"code": code_id, "ids": [m["id"] for m in members]},
        )

    return catalog

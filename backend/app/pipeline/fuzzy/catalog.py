"""Arma el catálogo de aliases contra el que corre el matcher, leyendo el
codebook más reciente de la ronda (aliases explícitos + labels normalizados
como fallback).
"""
from __future__ import annotations

import uuid

from rapidfuzz import fuzz, process as rf_process
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.normalize import normalize

from .models import (
    SCORE_THRESHOLD,
    SHORT_TEXT_EXACT_MAX_LEN,
    SYSTEM_ALIAS_VARIANTS,
    CodeAlias,
)


def load_catalog_aliases(db: Session, subproject_id: uuid.UUID) -> list[CodeAlias]:
    alias_rows = db.execute(
        text("""
            select ca.code_id::text as code_id, ca.alias_normalized
            from code_aliases ca
            join subprojects sp on sp.codebook_id = ca.codebook_id
            where sp.id = :sp
              and ca.alias_normalized is not null and ca.alias_normalized <> ''
        """),
        {"sp": subproject_id},
    ).mappings().all()

    label_rows = db.execute(
        text("""
            select c.id::text as code_id, c.label
            from codes c
            join subprojects sp on sp.codebook_id = c.codebook_id
            where sp.id = :sp
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
                                      alias_sample, occurrences, origin, match_score)
            select gen_random_uuid(), c.codebook_id, :code, :norm, :sample, 1, 'llm_promoted', :score
            from codes c where c.id = :code
            on conflict (codebook_id, alias_normalized, code_id) do update
              set occurrences = code_aliases.occurrences + 1
        """),
        {"code": code_id, "norm": alias_normalized, "sample": alias_sample, "score": match_score},
    )


def _brand_code_numbers(start: int):
    """Genera code_numbers correlativos saltando el rango 95-99 (reservado
    para códigos de sistema: colisionar ahí viola el unique del codebook)."""
    n = start
    while True:
        if 95 <= n <= 99:
            n = 100
        yield n
        n += 1


def _best_match(text_value: str, aliases: list[str], threshold: float):
    """extractOne con la misma guarda de texto corto que el matcher: un texto
    de <= SHORT_TEXT_EXACT_MAX_LEN chars solo se acepta por match exacto."""
    if not aliases:
        return None
    cutoff = 100.0 if len(text_value) <= SHORT_TEXT_EXACT_MAX_LEN else threshold
    return rf_process.extractOne(text_value, aliases, scorer=fuzz.WRatio, score_cutoff=cutoff)


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
    - Un candidato que ya matchea (>= threshold) contra el representante de un
      cluster existente es un typo de esa marca: se une a ese cluster en vez de
      abrir uno nuevo.

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

    # Sin el corte por frequency_count aquí: se necesita ver TODOS los
    # candidatos para poder agruparlos entre sí antes de decidir qué cluster
    # alcanza el mínimo (ver docstring).
    candidates = db.execute(
        text("""
            select normalized_text, sample_text, frequency_count
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

    def _persist_alias(code_id, alias_normalized: str, alias_sample: str | None, occurrences: int | None) -> None:
        db.execute(
            text("""
                insert into code_aliases (id, codebook_id, code_id, alias_normalized,
                                          alias_sample, occurrences, origin)
                values (:id, :cb, :code, :norm, :sample, :occ, 'engine_fuzzy')
                on conflict (codebook_id, alias_normalized, code_id) do nothing
            """),
            {
                "id": uuid.uuid4(), "cb": codebook_id, "code": code_id,
                "norm": alias_normalized, "sample": alias_sample, "occ": occurrences,
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
            _persist_alias(row["code_id"], variant, None, None)
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
    numbers = _brand_code_numbers(next_number)

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
        sys_hit = _best_match(norm, system_aliases, threshold)
        if sys_hit:
            code_id = alias_to_code[sys_hit[0]]
            _persist_alias(code_id, norm, cand["sample_text"], cand["frequency_count"])
            catalog.append(CodeAlias(code_id=code_id, alias_normalized=norm))
            continue

        cluster_hit = _best_match(norm, cluster_reprs, threshold)
        if cluster_hit:
            clusters[cluster_hit[0]].append(cand)
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
                insert into codes (id, codebook_id, code_number, label, origin)
                values (:id, :cb, :n, :label, 'engine_auto')
            """),
            {
                "id": code_id, "cb": codebook_id, "n": next(numbers),
                "label": formatted_label,
            },
        )
        for m in members:
            norm = m["normalized_text"]
            _persist_alias(code_id, norm, m["sample_text"], m["frequency_count"])
            catalog.append(CodeAlias(code_id=code_id, alias_normalized=norm))
            alias_to_code[norm] = code_id

    return catalog

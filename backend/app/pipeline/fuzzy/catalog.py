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


def load_catalog_aliases(db: Session, round_id: uuid.UUID) -> list[CodeAlias]:
    alias_rows = db.execute(
        text("""
            with latest as (
              select id from codebooks
              where round_id = :round
              order by version desc
              limit 1
            )
            select ca.code_id::text as code_id, ca.alias_normalized
            from code_aliases ca
            join latest l on l.id = ca.codebook_id
            where ca.alias_normalized is not null and ca.alias_normalized <> ''
        """),
        {"round": round_id},
    ).mappings().all()

    label_rows = db.execute(
        text("""
            with latest as (
              select id from codebooks
              where round_id = :round
              order by version desc
              limit 1
            )
            select c.id::text as code_id, c.label
            from codes c
            join latest l on l.id = c.codebook_id
            where c.is_active
              and coalesce(c.is_system, false) = false
              and c.label is not null
              and trim(c.label) <> ''
        """),
        {"round": round_id},
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
    round_id: uuid.UUID,
    min_mentions: int,
    threshold: float = SCORE_THRESHOLD,
) -> list[CodeAlias]:
    """Fallback cuando la ronda no trae codebook: deriva las marcas 'semilla'
    de la frecuencia.

    Cada mention_group cuyo frequency_count alcanza el mínimo de la ronda se
    promueve a un code nuevo (origin engine_auto) y su texto normalizado queda
    como alias, con dos filtros de precisión:

    - Respuestas de sistema ("no se", "ninguna"...) no se promueven como marcas:
      se vuelven aliases del código de sistema (96/98/99) y el fuzzy las codifica
      directo ahí. Sin esto, al ser de los textos más frecuentes, terminaban como
      marcas falsas en el codebook.
    - Un candidato que ya matchea (>= threshold) contra una semilla aceptada es
      un typo de esa marca: se agrega como alias del code existente en vez de
      crear un code duplicado.

    Con ese catálogo el fuzzy arrastra los typos poco frecuentes hacia las
    semillas; lo que no se parezca a ninguna sigue al LLM (flujo normal).

    Escribe codes/code_aliases pero no hace commit: el caller confirma junto con
    el resto del run. Idempotente por construcción — una vez creadas las semillas,
    load_catalog_aliases ya devuelve catálogo y este fallback no se vuelve a tomar.
    """
    codebook_id = db.execute(
        text("select id from codebooks where round_id = :round order by version desc limit 1"),
        {"round": round_id},
    ).scalar()
    if codebook_id is None:
        return []

    seeds = db.execute(
        text("""
            select normalized_text, sample_text, frequency_count
            from mention_groups
            where round_id = :round
              and status = 'pending_review'
              and normalized_text <> ''
              and frequency_count >= :min
            order by frequency_count desc, normalized_text
        """),
        {"round": round_id, "min": min_mentions},
    ).mappings().all()
    if not seeds:
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

    seed_aliases: list[str] = []
    for seed in seeds:
        norm = seed["normalized_text"]

        # Respuesta de sistema disfrazada de marca frecuente -> alias de 96/98/99.
        sys_hit = _best_match(norm, system_aliases, threshold)
        if sys_hit:
            code_id = alias_to_code[sys_hit[0]]
            _persist_alias(code_id, norm, seed["sample_text"], seed["frequency_count"])
            catalog.append(CodeAlias(code_id=code_id, alias_normalized=norm))
            continue

        # Typo de una semilla ya aceptada -> alias del code existente.
        seed_hit = _best_match(norm, seed_aliases, threshold)
        if seed_hit:
            code_id = alias_to_code[seed_hit[0]]
        else:
            code_id = str(uuid.uuid4())
            raw_label = seed["sample_text"] or norm
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
        _persist_alias(code_id, norm, seed["sample_text"], seed["frequency_count"])
        catalog.append(CodeAlias(code_id=code_id, alias_normalized=norm))
        alias_to_code[norm] = code_id
        seed_aliases.append(norm)

    return catalog

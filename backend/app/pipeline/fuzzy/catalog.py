"""Arma el catálogo de aliases contra el que corre el matcher, leyendo el
codebook más reciente del studio (aliases explícitos + labels normalizados
como fallback).
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.normalize import normalize

from .models import CodeAlias


def load_catalog_aliases(db: Session, studio_id: uuid.UUID) -> list[CodeAlias]:
    alias_rows = db.execute(
        text("""
            with latest as (
              select id from codebooks
              where studio_id = :studio
              order by version desc
              limit 1
            )
            select ca.code_id::text as code_id, ca.alias_normalized
            from code_aliases ca
            join latest l on l.id = ca.codebook_id
            where ca.alias_normalized is not null and ca.alias_normalized <> ''
        """),
        {"studio": studio_id},
    ).mappings().all()

    label_rows = db.execute(
        text("""
            with latest as (
              select id from codebooks
              where studio_id = :studio
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
        {"studio": studio_id},
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


def discover_catalog_from_frequency(
    db: Session, studio_id: uuid.UUID, min_mentions: int
) -> list[CodeAlias]:
    """Fallback cuando el studio no trae codebook: deriva las marcas 'semilla'
    de la frecuencia.

    Cada mention_group cuyo frequency_count alcanza el mínimo del studio se
    promueve a un code nuevo (origin engine_auto) y su texto normalizado queda
    como alias. Con ese catálogo el fuzzy arrastra los typos poco frecuentes
    hacia las semillas; lo que no se parezca a ninguna sigue al LLM (flujo normal).

    Escribe codes/code_aliases pero no hace commit: el caller confirma junto con
    el resto del run. Idempotente por construcción — una vez creadas las semillas,
    load_catalog_aliases ya devuelve catálogo y este fallback no se vuelve a tomar.
    """
    codebook_id = db.execute(
        text("select id from codebooks where studio_id = :studio order by version desc limit 1"),
        {"studio": studio_id},
    ).scalar()
    if codebook_id is None:
        return []

    seeds = db.execute(
        text("""
            select normalized_text, sample_text, frequency_count
            from mention_groups
            where studio_id = :studio
              and status = 'pending_review'
              and normalized_text <> ''
              and frequency_count >= :min
            order by frequency_count desc, normalized_text
        """),
        {"studio": studio_id, "min": min_mentions},
    ).mappings().all()
    if not seeds:
        return []

    # Numeración correlativa a partir del último code de marca no-system (los
    # system ocupan 95-99), respetando cualquier código ya presente en el libro.
    next_number = db.execute(
        text("""
            select coalesce(max(code_number), 0) + 1 from codes
            where codebook_id = :cb and coalesce(is_system, false) = false
        """),
        {"cb": codebook_id},
    ).scalar()

    catalog: list[CodeAlias] = []
    for offset, seed in enumerate(seeds):
        code_id = uuid.uuid4()
        label = seed["sample_text"] or seed["normalized_text"]
        db.execute(
            text("""
                insert into codes (id, codebook_id, code_number, label, origin)
                values (:id, :cb, :n, :label, 'engine_auto')
            """),
            {"id": code_id, "cb": codebook_id, "n": next_number + offset, "label": label},
        )
        db.execute(
            text("""
                insert into code_aliases (id, codebook_id, code_id, alias_normalized,
                                          alias_sample, occurrences, origin)
                values (:id, :cb, :code, :norm, :sample, :occ, 'engine_fuzzy')
            """),
            {
                "id": uuid.uuid4(),
                "cb": codebook_id,
                "code": code_id,
                "norm": seed["normalized_text"],
                "sample": seed["sample_text"],
                "occ": seed["frequency_count"],
            },
        )
        catalog.append(CodeAlias(code_id=str(code_id), alias_normalized=seed["normalized_text"]))

    return catalog

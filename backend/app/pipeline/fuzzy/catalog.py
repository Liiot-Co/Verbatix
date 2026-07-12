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

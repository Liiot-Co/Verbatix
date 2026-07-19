"""Bootstrap del codebook de razones cuando arranca vacío (from_scratch, sin
codebook importado ni homologado).

Sin esto, classify_round (pipeline/llm/classify.py) solo puede elegir entre
los 5 códigos de sistema — ninguna categoría real ("sabor", "precio"...)
existe todavía — y el prompt termina metiendo casi todo en 97 "Otras
menciones" porque, literalmente, nada tiene su propio código.

Marcas resuelve esto agrupando por frecuencia exacta/fuzzy (ver
pipeline/fuzzy/catalog.discover_catalog_from_frequency): funciona porque una
marca repetida se escribe casi igual cada vez ("gloria", "glorea"). Una razón
casi nunca se repite palabra por palabra ("es rico" vs "tiene buen sabor"), así
que el agrupamiento tiene que ser semántico (embeddings + similitud coseno) en
vez de por texto.

Este módulo solo POBLA el codebook con categorías candidatas — no decide qué
mention_group va en cuál. La asignación real la sigue haciendo classify_round,
con su propia pasada LLM por texto (más precisa que los bordes de un cluster
por embeddings), ahora contra un codebook que ya tiene contenido real.
"""
from __future__ import annotations

import uuid

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.pipeline.llm.client import name_clusters

from .embed import embed


def cluster_by_similarity(
    items: list[tuple[str, list[float], int]], threshold: float
) -> list[dict]:
    """Greedy single-link: cada item se compara contra el representante
    (primer miembro, el de mayor frecuencia si `items` ya viene ordenado desc)
    de los clusters abiertos y se une al primero que supere el umbral de
    similitud coseno, o abre uno nuevo. O(n*k) — de sobra para los cientos de
    mention_groups únicos que trae una ronda; no hay sklearn en el stack y no
    hace falta uno para este volumen.

    `items`: (representative_text, embedding, frequency). Devuelve
    [{"representative": str, "total_frequency": int}], sin trackear membresía
    individual (no la necesita el caller, ver docstring del módulo).
    """
    reprs: list[np.ndarray] = []
    clusters: list[dict] = []
    for text_, vector, freq in items:
        v = np.array(vector, dtype=float)
        norm = np.linalg.norm(v)
        if norm > 0:
            v = v / norm

        best_idx, best_sim = None, threshold
        for idx, r in enumerate(reprs):
            sim = float(np.dot(v, r))
            if sim >= best_sim:
                best_idx, best_sim = idx, sim

        if best_idx is not None:
            clusters[best_idx]["total_frequency"] += freq
        else:
            clusters.append({"representative": text_, "total_frequency": freq})
            reprs.append(v)
    return clusters


def discover_reason_catalog(db: Session, subproject_id: uuid.UUID, min_mentions: int) -> int:
    """Idempotente: si el codebook ya tiene algún code propio (no-system) no
    hace nada, igual que discover_catalog_from_frequency para marcas — una vez
    poblado, no se vuelve a tomar. Devuelve cuántos codes creó."""
    codebook_id = db.execute(
        text("select codebook_id from subprojects where id = :sp"),
        {"sp": subproject_id},
    ).scalar()
    if codebook_id is None:
        return 0

    has_own_codes = db.execute(
        text("select exists(select 1 from codes where codebook_id = :cb and not is_system)"),
        {"cb": codebook_id},
    ).scalar()
    if has_own_codes:
        return 0

    candidates = db.execute(
        text("""
            select normalized_text, sample_text, frequency_count
            from mention_groups
            where subproject_id = :sp and status = 'pending_review' and normalized_text <> ''
            order by frequency_count desc, normalized_text
        """),
        {"sp": subproject_id},
    ).mappings().all()
    if not candidates:
        return 0

    items = [
        (c["sample_text"] or c["normalized_text"], embed(c["normalized_text"]), c["frequency_count"])
        for c in candidates
    ]
    clusters = cluster_by_similarity(items, settings.reason_cluster_similarity_threshold)
    big_clusters = [c for c in clusters if c["total_frequency"] >= min_mentions]
    if not big_clusters:
        return 0

    labels = name_clusters([c["representative"] for c in big_clusters])

    next_number = db.execute(
        text("""
            select coalesce(max(code_number), 0) + 1 from codes
            where codebook_id = :cb and coalesce(is_system, false) = false
        """),
        {"cb": codebook_id},
    ).scalar()

    for label in labels:
        # 'engine_auto' (no 'engine_semantic'): mismo origin que
        # discover_catalog_from_frequency usa para marcas — el check constraint
        # de `codes` (001_schema_v8.sql) no tiene un valor separado para
        # "generado por clustering semántico" y no hace falta uno nuevo, el
        # significado ("lo creó el motor, no un analista") es el mismo.
        db.execute(
            text("""
                insert into codes (id, codebook_id, code_number, label, origin)
                values (:id, :cb, :n, :label, 'engine_auto')
            """),
            {"id": uuid.uuid4(), "cb": codebook_id, "n": next_number, "label": label},
        )
        next_number += 1

    return len(labels)

"""Semantic cache for reasons: written when classify_round auto-codes a
reason above the promotion threshold (this module); read by Task C3 before
dispatching new reasons to the LLM.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

from .embed import embed


def _to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in vector) + "]"


def lookup(db: Session, codebook_ids, normalized_text: str) -> dict | None:
    """Busca el vecino más cercano en reason_embeddings por similitud coseno,
    acotado a uno o varios codebook_id (Task C4: homologación busca también en
    el codebook de la ronda origen vía source_round_id). None si no hay filas
    o el mejor match no supera semantic_cache_similarity_threshold.

    Devuelve también de qué codebook_id vino el match: si no es el propio de
    la ronda, el caller debe remapear code_id al code inherited_from_code_id
    equivalente en su propio codebook antes de usarlo (los ids de code no se
    comparten entre codebooks clonados, ver repositories.clone_codebook).
    """
    ids = codebook_ids if isinstance(codebook_ids, (list, tuple)) else [codebook_ids]
    vector = _to_pgvector(embed(normalized_text))
    row = db.execute(
        text("""
            select code_id, codebook_id, 1 - (embedding <=> :vec) as similarity
            from reason_embeddings
            where codebook_id = any(:cbs)
            order by embedding <=> :vec
            limit 1
        """),
        {"vec": vector, "cbs": ids},
    ).mappings().first()
    if row is None or row["similarity"] < settings.semantic_cache_similarity_threshold:
        return None
    return {"code_id": row["code_id"], "codebook_id": row["codebook_id"], "similarity": row["similarity"]}


def write(db: Session, code_id: str, source_text: str, confidence: float) -> None:
    """Cachea el embedding de una razón LLM-aprobada. codebook_id se resuelve
    desde code_id (no se pide al caller) — mismo patrón que
    promote_llm_result_to_alias en fuzzy/catalog.py."""
    vector = embed(source_text)
    db.execute(
        text("""
            insert into reason_embeddings (id, codebook_id, code_id, source_text, embedding, confidence)
            select gen_random_uuid(), c.codebook_id, :code, :text, :embedding, :conf
            from codes c where c.id = :code
        """),
        {
            "code": code_id,
            "text": source_text,
            "embedding": _to_pgvector(vector),
            "conf": confidence,
        },
    )

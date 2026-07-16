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


def lookup(db: Session, codebook_id, normalized_text: str) -> dict | None:
    """Busca el vecino más cercano en reason_embeddings por similitud coseno,
    acotado al mismo codebook_id. None si no hay filas o el mejor match no
    supera semantic_cache_similarity_threshold.
    """
    vector = _to_pgvector(embed(normalized_text))
    row = db.execute(
        text("""
            select code_id, 1 - (embedding <=> :vec) as similarity
            from reason_embeddings
            where codebook_id = :cb
            order by embedding <=> :vec
            limit 1
        """),
        {"vec": vector, "cb": codebook_id},
    ).mappings().first()
    if row is None or row["similarity"] < settings.semantic_cache_similarity_threshold:
        return None
    return {"code_id": row["code_id"], "similarity": row["similarity"]}


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

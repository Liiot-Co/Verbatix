"""Semantic cache for reasons: written when classify_round auto-codes a
reason above the promotion threshold (this module); read by Task C3 before
dispatching new reasons to the LLM.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from .embed import embed


def _to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in vector) + "]"


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

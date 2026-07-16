"""Wraps the embedding library so the rest of the pipeline never imports it
directly — fastembed (ONNX-only, no torch) chosen over sentence-transformers
for dependency weight; swapping models/libraries later stays contained here.
Multilingual model (not the English-only default) since verbatims are
Spanish.
"""
from functools import lru_cache

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=EMBEDDING_MODEL)


def embed(text: str) -> list[float]:
    return list(_model().embed([text]))[0].tolist()

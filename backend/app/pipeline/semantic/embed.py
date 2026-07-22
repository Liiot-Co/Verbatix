"""Wraps the embedding library so the rest of the pipeline never imports it
directly — fastembed (ONNX-only, no torch) chosen over sentence-transformers
for dependency weight; swapping models/libraries later stays contained here.
Multilingual model (not the English-only default) since verbatims are
Spanish.

fastembed pinned to 0.5.1 in requirements.txt: 0.6+ switched this model from
CLS to mean pooling, silently changing the embedding vectors. The cosine
thresholds calibrated against this pipeline (semantic_cache_similarity_threshold,
reason_cluster_similarity_threshold in core/config.py) assume CLS pooling —
upgrading without recalibrating would shift similarity scores with no error,
just quietly worse clustering/cache hits.
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


def embed_many(texts: list[str]) -> list[list[float]]:
    """Igual que ``embed`` pero para una lista, en UNA sola pasada del modelo.

    fastembed batchea internamente, así que embeber N textos de golpe evita el
    overhead por-llamada de embeber uno a uno (crítico en el bootstrap de Razones,
    que embebe cientos de grupos). Los vectores son idénticos a llamar ``embed``
    por texto — mismo modelo, mismos textos. Preserva el orden de entrada.
    """
    if not texts:
        return []
    return [vector.tolist() for vector in _model().embed(list(texts))]

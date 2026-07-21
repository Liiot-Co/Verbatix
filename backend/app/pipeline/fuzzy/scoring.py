"""Candidate scoring de Marcas. Ningún score de este módulo autoriza autocierre."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from rapidfuzz import fuzz
from rapidfuzz.distance import DamerauLevenshtein

from .models import CodeAlias


COMMON_WORDS = {
    "a", "al", "de", "del", "dos", "el", "en", "la", "las", "lo", "los",
    "no", "se", "si", "sin", "tres", "un", "una", "uno", "y",
}
FUZZY_MIN_LENGTH = 5


@dataclass(frozen=True)
class BrandCandidate:
    code_id: str
    alias: str
    score: float
    margin: float
    damerau_similarity: float
    ratio: float
    wratio: float
    ngram_jaccard: float
    token_jaccard: float
    length_ratio: float

    def as_dict(self) -> dict:
        return asdict(self)


def _ngrams(value: str, size: int = 2) -> set[str]:
    padded = f" {value} "
    return {padded[index:index + size] for index in range(len(padded) - size + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _signals(value: str, alias: str) -> dict[str, float]:
    length_ratio = min(len(value), len(alias)) / max(len(value), len(alias))
    damerau = DamerauLevenshtein.normalized_similarity(value, alias)
    ratio = fuzz.ratio(value, alias) / 100
    wratio = fuzz.WRatio(value, alias) / 100
    ngram = _jaccard(_ngrams(value), _ngrams(alias))
    token = _jaccard(set(value.split()), set(alias.split()))
    # token_jaccard es estructuralmente 0 para un typo de marca de UNA sola
    # palabra: los conjuntos de tokens son disjuntos salvo coincidencia exacta,
    # que ya la resuelve el match exacto (score 100). Dejar su peso fijo (0.12)
    # capaba el score de esas marcas en 88 — justo el umbral de auto-cierre —, así
    # que un typo de una palabra jamás podía auto-cerrarse (schugur->chugur,
    # gloriq->gloria, etc. solo se sugerían). Cuando ambos lados son de una sola
    # palabra ese peso se redistribuye a las señales de carácter, que sí
    # discriminan al typo del falso positivo; multipalabra conserva la fórmula.
    multiword = (" " in value.strip()) or (" " in alias.strip())
    if multiword:
        score = 100 * (
            0.34 * damerau
            + 0.24 * ratio
            + 0.20 * ngram
            + 0.12 * token
            + 0.10 * length_ratio
        )
    else:
        score = 100 * (
            0.40 * damerau
            + 0.28 * ratio
            + 0.22 * ngram
            + 0.10 * length_ratio
        )
    return {
        "score": score,
        "damerau_similarity": damerau,
        "ratio": ratio,
        "wratio": wratio,
        "ngram_jaccard": ngram,
        "token_jaccard": token,
        "length_ratio": length_ratio,
    }


def rank_brand_candidates(value: str, catalog: list[CodeAlias]) -> list[BrandCandidate]:
    """Devuelve el mejor alias por código, ya filtrado por bloqueos de precisión."""
    value = (value or "").strip()
    if len(value) < FUZZY_MIN_LENGTH or value in COMMON_WORDS:
        return []

    best_by_code: dict[str, tuple[str, dict[str, float]]] = {}
    for item in catalog:
        alias = item.alias_normalized.strip()
        if len(alias) < FUZZY_MIN_LENGTH or alias in COMMON_WORDS or alias == value:
            continue
        signals = _signals(value, alias)
        # Bloquea recuperación basada solo en substring o con longitudes
        # incompatibles. WRatio queda como señal de recall, nunca como decisión.
        substring_only = (
            (value in alias or alias in value)
            and signals["ratio"] < 0.86
            and signals["token_jaccard"] == 0
        )
        enough_shape = (
            signals["damerau_similarity"] >= 0.72
            or signals["ngram_jaccard"] >= 0.45
            or signals["token_jaccard"] >= 0.5
        )
        if (
            substring_only
            or not enough_shape
            or signals["wratio"] < 0.78
            or signals["length_ratio"] < 0.60
        ):
            continue
        current = best_by_code.get(item.code_id)
        if current is None or signals["score"] > current[1]["score"]:
            best_by_code[item.code_id] = (alias, signals)

    ranked = sorted(best_by_code.items(), key=lambda item: item[1][1]["score"], reverse=True)
    if not ranked:
        return []
    top_score = ranked[0][1][1]["score"]
    second_score = ranked[1][1][1]["score"] if len(ranked) > 1 else 0.0
    margin = top_score - second_score
    if len(ranked) > 1 and margin < 5.0:
        return []

    results = []
    for code_id, (alias, signals) in ranked[:2]:
        results.append(BrandCandidate(
            code_id=code_id,
            alias=alias,
            margin=margin if code_id == ranked[0][0] else 0.0,
            **signals,
        ))
    return results


def best_brand_candidate(value: str, catalog: list[CodeAlias]) -> BrandCandidate | None:
    ranked = rank_brand_candidates(value, catalog)
    return ranked[0] if ranked else None

import pandas as pd
from collections import Counter
from rapidfuzz import fuzz, process
from typing import Optional

MARKETING_STOPWORDS: set[str] = {
    "precio",
    "calidad",
    "servicio",
    "producto",
    "marca",
    "tienda",
    "compra",
    "envio",
    "envío",
    "rapido",
    "rápido",
    "barato",
    "caro",
    "bueno",
    "malo",
    "online",
    "app",
    "delivery",
    "importante",
    "lo",
}

GENERAL_STOPWORDS: set[str] = {
    "el", "la", "los", "las", "lo", "le", "les",
    "un", "una", "unos", "unas",
    "y", "e", "o", "u", "pero", "sino",
    "de", "del", "en", "con", "sin", "por", "para", "a", "ante", "bajo",
    "que", "como", "cuando", "donde", "cual", "quien",
    "se", "su", "sus", "tu", "te", "mi", "mis",
    "es", "son", "fue", "era", "ser", "estar", "está", "esta",
    "no", "si", "sí", "ya", "también", "tan", "tanto",
    "más", "menos", "muy", "mucho", "poco",
    "todo", "toda", "todos", "todas",
    "al", "del", "entre", "hacia", "hasta",
    "porque", "pues", "bien",
}


def filter_stopwords(
    counter: Counter,
    additional_stopwords: Optional[set[str]] = None,
) -> Counter:
    stopwords = GENERAL_STOPWORDS | MARKETING_STOPWORDS
    if additional_stopwords:
        stopwords |= additional_stopwords
    return Counter(
        {k: v for k, v in counter.items() if k not in stopwords and len(k) > 1}
    )


def apply_threshold(
    counter: Counter,
    min_freq: int = 50,
    min_df: Optional[Counter] = None,
    min_df_threshold: int = 30,
) -> Counter:
    filtered = Counter({k: v for k, v in counter.items() if v >= min_freq})
    if min_df is not None:
        filtered = Counter(
            {
                k: v
                for k, v in filtered.items()
                if min_df.get(k, 0) >= min_df_threshold
            }
        )
    return filtered


def cluster_variants(
    ngrams: list[str],
    auto_threshold: int = 95,
    review_threshold: int = 88,
) -> dict[str, dict]:
    clusters: dict[str, dict] = {}
    assigned = set()

    for ngram in ngrams:
        if ngram in assigned:
            continue
        cluster_key = ngram
        clusters[cluster_key] = {
            "canonical": ngram,
            "variants": [ngram],
            "auto": [],
            "review": [],
        }
        assigned.add(ngram)

        for other in ngrams:
            if other in assigned:
                continue
            score = fuzz.token_sort_ratio(ngram, other)
            if score >= auto_threshold:
                clusters[cluster_key]["auto"].append(other)
                clusters[cluster_key]["variants"].append(other)
                assigned.add(other)
            elif score >= review_threshold:
                clusters[cluster_key]["review"].append(other)

    return clusters


def run_clustering(
    freq_counter: Counter,
    df_counter: Optional[Counter] = None,
    min_freq: int = 50,
    min_df: int = 30,
    auto_threshold: int = 95,
    review_threshold: int = 88,
    additional_stopwords: Optional[set[str]] = None,
) -> dict:
    filtered = filter_stopwords(freq_counter, additional_stopwords)
    filtered = apply_threshold(filtered, min_freq, df_counter, min_df)
    ngrams = list(filtered.keys())
    clusters = cluster_variants(ngrams, auto_threshold, review_threshold)
    return {
        "clusters": clusters,
        "total_candidates": len(ngrams),
        "total_clusters": len(clusters),
        "thresholds": {
            "min_freq": min_freq,
            "min_df": min_df,
            "auto": auto_threshold,
            "review": review_threshold,
        },
    }

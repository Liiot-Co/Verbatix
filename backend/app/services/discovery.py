from pathlib import Path

import pandas as pd

from discovery.clustering import cluster_variants, filter_stopwords, apply_threshold
from discovery.pipeline import clean_column, compute_document_frequency, drop_empty, extract_all_ngrams


def _thresholds(n_responses: int) -> tuple[int, int]:
    if n_responses < 5_000:
        return 2, 1
    return 50, 30


def run_discovery(
    file_path: str | Path,
    answer_column: str,
) -> dict:
    df = pd.read_excel(file_path, engine="openpyxl")
    if answer_column not in df.columns:
        raise ValueError(f"column {answer_column!r} not in dataframe")

    working = df[[answer_column]].rename(columns={answer_column: "respuesta_original"})
    working = clean_column(working)
    working = drop_empty(working)

    if working.empty:
        return {"entities": [], "clusters": {}, "total": 0}

    min_freq, min_df_thr = _thresholds(len(working))
    series = working["respuesta_limpia"]
    freq_by_n = extract_all_ngrams(series, max_n=3)
    df_by_n = compute_document_frequency(series, max_n=3)

    entities: list[dict] = []
    seen: set[str] = set()
    for ngram_size, counter in freq_by_n.items():
        filtered = filter_stopwords(counter)
        filtered = apply_threshold(filtered, min_freq=min_freq, min_df=df_by_n[ngram_size], min_df_threshold=min_df_thr)
        for term, frequency in filtered.most_common():
            if term in seen:
                continue
            seen.add(term)
            entities.append({
                "term": term,
                "frequency": frequency,
                "document_frequency": df_by_n[ngram_size].get(term, 0),
                "ngram": ngram_size,
            })

    entities.sort(key=lambda r: (-r["frequency"], r["term"]))
    ngrams_list = [e["term"] for e in entities]
    clusters = cluster_variants(ngrams_list)

    return {"entities": entities, "clusters": clusters, "total": len(entities)}


def run_discovery_from_df(df: pd.DataFrame, answer_column: str) -> dict:
    if answer_column not in df.columns:
        raise ValueError(f"column {answer_column!r} not in dataframe")

    working = df[[answer_column]].rename(columns={answer_column: "respuesta_original"})
    working = clean_column(working)
    working = drop_empty(working)

    if working.empty:
        return {"entities": [], "clusters": {}, "total": 0}

    min_freq, min_df_thr = _thresholds(len(working))
    series = working["respuesta_limpia"]
    freq_by_n = extract_all_ngrams(series, max_n=3)
    df_by_n = compute_document_frequency(series, max_n=3)

    entities: list[dict] = []
    seen: set[str] = set()
    for ngram_size, counter in freq_by_n.items():
        filtered = filter_stopwords(counter)
        filtered = apply_threshold(filtered, min_freq=min_freq, min_df=df_by_n[ngram_size], min_df_threshold=min_df_thr)
        for term, frequency in filtered.most_common():
            if term in seen:
                continue
            seen.add(term)
            entities.append({
                "term": term,
                "frequency": frequency,
                "document_frequency": df_by_n[ngram_size].get(term, 0),
                "ngram": ngram_size,
            })

    entities.sort(key=lambda r: (-r["frequency"], r["term"]))
    ngrams_list = [e["term"] for e in entities]
    clusters = cluster_variants(ngrams_list)

    return {"entities": entities, "clusters": clusters, "total": len(entities)}

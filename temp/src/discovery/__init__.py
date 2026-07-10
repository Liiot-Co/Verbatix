"""Discovery engine — Excel ingest through candidate term extraction.

Wires opencode's modules into the entrypoint expected by the Streamlit UI::

    discover(df, answer_column, round_name) -> list[dict]

Each dict has: term, frequency, document_frequency, ngram.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

from discovery.clustering import apply_threshold, filter_stopwords
from discovery.pipeline import (
    clean_column,
    compute_document_frequency,
    drop_empty,
    extract_all_ngrams,
)


def _thresholds(n_responses: int) -> tuple[int, int]:
    """§7.6: lower thresholds for small survey rounds."""
    if n_responses < 5_000:
        return 2, 1
    return 50, 30


def discover(df: "pd.DataFrame", answer_column: str, round_name: str) -> list[dict]:
    """Run the full discovery pipeline on an uploaded survey frame.

    Parameters
    ----------
    df:
        Raw Excel data (already loaded).
    answer_column:
        Column with open-ended answers.
    round_name:
        Label for the survey round (stored separately in the catalog).

    Returns
    -------
    list[dict]
        Candidate terms ready for ``CatalogStore.bulk_add_candidates``.
    """
    del round_name  # round id is assigned by the UI / store

    if answer_column not in df.columns:
        raise ValueError(f"column {answer_column!r} not in dataframe")

    working = df[[answer_column]].rename(columns={answer_column: "respuesta_original"})
    working = clean_column(working)
    working = drop_empty(working)

    if working.empty:
        return []

    min_freq, min_df_thr = _thresholds(len(working))
    series = working["respuesta_limpia"]
    freq_by_n = extract_all_ngrams(series, max_n=3)
    df_by_n = compute_document_frequency(series, max_n=3)

    rows: list[dict] = []
    seen: set[str] = set()
    for ngram_size, counter in freq_by_n.items():
        filtered = filter_stopwords(counter)
        filtered = apply_threshold(
            filtered,
            min_freq=min_freq,
            min_df=df_by_n[ngram_size],
            min_df_threshold=min_df_thr,
        )
        for term, frequency in filtered.most_common():
            if term in seen:
                continue
            seen.add(term)
            rows.append(
                {
                    "term": term,
                    "frequency": frequency,
                    "document_frequency": df_by_n[ngram_size].get(term, 0),
                    "ngram": ngram_size,
                }
            )

    rows.sort(key=lambda r: (-r["frequency"], r["term"]))
    return rows


__all__ = ["discover"]

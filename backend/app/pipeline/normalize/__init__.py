"""Stage 2 — normaliza texto crudo a la forma que consume el fuzzy/LLM."""

from .dataframe import CodingType, normalization_stats, rows_to_normalized_df
from .text import normalize, strip_leading_article

__all__ = [
    "CodingType",
    "normalize",
    "normalization_stats",
    "rows_to_normalized_df",
    "strip_leading_article",
]

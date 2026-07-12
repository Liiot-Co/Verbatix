"""
Orquestación del módulo. Decide qué se somete a fuzzy y arma los dos
DataFrames de salida (clasificados / no clasificados).

Es la única capa que conoce la regla de negocio "fuzzy solo para marcas".
El matcher es agnóstico; el router es transporte. Esta capa es el pegamento.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from .matcher import match_against_catalog
from .models import (
    FUZZY_CODING_TYPE,
    SCORE_THRESHOLD,
    SOURCE_FUZZY,
    CodeAlias,
    Cols,
)

_CLASSIFIED_COLS = [
    Cols.RESPONDENT_ID,
    Cols.QUESTION_KEY,
    Cols.NORMALIZED_TEXT,
    Cols.CODE_ID,
    Cols.MATCHED_ALIAS,
    Cols.SCORE,
    Cols.SOURCE,
]
_UNMATCHED_COLS = [
    Cols.RESPONDENT_ID,
    Cols.QUESTION_KEY,
    Cols.NORMALIZED_TEXT,
    Cols.CODING_TYPE,
]


@dataclass(frozen=True)
class MatchResult:
    """Resultado del módulo: lo que se guarda vs. lo que sigue al LLM."""

    classified: pl.DataFrame  # superaron el umbral -> persistir en verbatim_codes
    unmatched: pl.DataFrame   # razones + marcas bajo umbral -> siguiente módulo


def run_fuzzy_matching(
    df: pl.DataFrame,
    catalog: list[CodeAlias],
    threshold: float = SCORE_THRESHOLD,
) -> MatchResult:
    """
    Aplica fuzzy matching al lote y separa clasificados de no clasificados.

    Solo las filas cuyo coding_type es de marcas pasan por el algoritmo; las de
    razones se derivan enteras a `unmatched` (su equivalencia es semántica, no
    ortográfica, y el fuzzy generaría falsos positivos).
    """
    df = _ensure_question_key(df)
    empty_classified = pl.DataFrame(schema={c: _schema_for(c) for c in _CLASSIFIED_COLS})

    is_brand = pl.col(Cols.CODING_TYPE) == FUZZY_CODING_TYPE
    brands = df.filter(is_brand)
    non_brands = df.filter(~is_brand).select(_UNMATCHED_COLS)

    if brands.height == 0 or not catalog:
        return MatchResult(
            classified=empty_classified,
            unmatched=pl.concat(
                [non_brands, brands.select(_UNMATCHED_COLS)],
                how="vertical",
            ) if brands.height else non_brands,
        )

    scored = match_against_catalog(brands, catalog, threshold)

    classified = (
        scored.filter(pl.col("_is_match"))
        .with_columns(pl.lit(SOURCE_FUZZY).alias(Cols.SOURCE))
        .select(_CLASSIFIED_COLS)
    )

    brands_unmatched = scored.filter(~pl.col("_is_match")).select(_UNMATCHED_COLS)
    unmatched = pl.concat([non_brands, brands_unmatched], how="vertical")

    return MatchResult(classified=classified, unmatched=unmatched)


def _ensure_question_key(df: pl.DataFrame) -> pl.DataFrame:
    if Cols.QUESTION_KEY in df.columns:
        return df.with_columns(pl.col(Cols.QUESTION_KEY).cast(pl.Utf8))
    return df.with_columns(pl.lit(None).cast(pl.Utf8).alias(Cols.QUESTION_KEY))


def _schema_for(col: str) -> pl.DataType:
    """Tipo de cada columna de salida para construir un DataFrame vacío válido."""
    if col == Cols.SCORE:
        return pl.Float64
    return pl.String

"""
Núcleo del fuzzy matching. Función pura: DataFrame + catálogo -> DataFrame.

No conoce FastAPI, Supabase ni razones/marcas. Solo compara textos contra un
catálogo de aliases y devuelve el mejor match con su score. La decisión de
"qué se clasifica y qué no" vive en el service, no aquí.
"""

from __future__ import annotations

import polars as pl
from rapidfuzz import fuzz, process

from .models import SHORT_TEXT_EXACT_MAX_LEN, CodeAlias, Cols

# WRatio es el scorer elegido tras comparar contra ratio/token_sort/token_set
# sobre los datos reales: es el único que maneja bien tanto typos de token único
# (ottokunk->otto kunz) como diferencias de longitud (san fernando queso->san fernando).
_SCORER = fuzz.WRatio


def match_against_catalog(
    df: pl.DataFrame,
    catalog: list[CodeAlias],
    threshold: float,
) -> pl.DataFrame:
    """
    Asocia cada fila de `df` con su mejor alias del catálogo por similitud.

    Args:
        df: DataFrame con al menos la columna NORMALIZED_TEXT.
        catalog: aliases contra los que comparar (un alias puede repetir code_id).
        threshold: score mínimo (0-100) para marcar la fila como clasificada.

    Returns:
        El mismo `df` con cuatro columnas añadidas: CODE_ID, MATCHED_ALIAS,
        SCORE y un booleano `_is_match`. Las filas por debajo del umbral traen
        code_id/alias en null y _is_match=False.
    """
    aliases = [c.alias_normalized for c in catalog]
    alias_to_code = {c.alias_normalized: c.code_id for c in catalog}

    # Trabajamos solo sobre los textos únicos: colapsa 1.283 filas a ~279
    # comparaciones. El resultado se re-une por texto al final.
    unique_texts = df.get_column(Cols.NORMALIZED_TEXT).unique().to_list()

    # cdist calcula toda la matriz textos x aliases en C++ y extraemos, por fila,
    # el índice del mejor alias. Un solo cómputo vectorizado, sin loop en Python.
    scores = process.cdist(unique_texts, aliases, scorer=_SCORER, workers=-1)

    best_records = []
    for i, text in enumerate(unique_texts):
        row = scores[i]
        best_j = int(row.argmax())
        best_score = float(row[best_j])
        best_alias = aliases[best_j]
        best_records.append(
            {
                Cols.NORMALIZED_TEXT: text,
                Cols.CODE_ID: alias_to_code[best_alias],
                Cols.MATCHED_ALIAS: best_alias,
                Cols.SCORE: best_score,
            }
        )

    best_df = pl.DataFrame(best_records) if best_records else pl.DataFrame(
        schema={
            Cols.NORMALIZED_TEXT: pl.String,
            Cols.CODE_ID: pl.String,
            Cols.MATCHED_ALIAS: pl.String,
            Cols.SCORE: pl.Float64,
        }
    )

    # Textos cortos solo pasan con match exacto: WRatio escala partial_ratio y
    # un substring corto puntúa alto contra aliases largos ('uno' -> 'ninguno' 90).
    return df.join(best_df, on=Cols.NORMALIZED_TEXT, how="left").with_columns(
        (
            (pl.col(Cols.SCORE) >= threshold)
            & (
                (pl.col(Cols.NORMALIZED_TEXT).str.len_chars() > SHORT_TEXT_EXACT_MAX_LEN)
                | (pl.col(Cols.SCORE) >= 100.0)
            )
        ).alias("_is_match")
    )

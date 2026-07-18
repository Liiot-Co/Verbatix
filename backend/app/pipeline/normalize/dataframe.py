"""Pipeline Polars: filas del Excel -> DataFrame normalizado.

Columnas de salida:
    respondent_external_id  — ID del encuestado
    question_key            — pregunta (para reexportar / join a verbatims)
    normalized_text         — verbatim limpio (input del fuzzy)
    coding_type              — "brands" | "reasons" (del subproyecto que recibe este batch)

Marcas vs razones
-----------------
Un archivo puede mezclar ambos coding_types (sección 2.5 del documento v8):
insert_verbatims (repositories.py) reparte cada fila a su subproject_id según
questions.coding_type y llama esta función una vez por coding_type, con el
subconjunto de filas ya homogéneo. El paso 2 lee coding_type del DataFrame y decide:

  brands  → fuzzy (pipeline.fuzzy) asigna como máximo 1 código por fila
  reasons → se derivan enteras a unmatched para el módulo LLM

Normalización de razones con varias palabras
--------------------------------------------
NO se parte el verbatim en normalización. Una fila = un encuestado = un texto completo:

    "Es rico y barato"  →  "es rico y barato"
"""
from __future__ import annotations

from typing import Literal

import polars as pl

from .text import normalize

CodingType = Literal["brands", "reasons"]
OUTPUT_COLUMNS = (
    "respondent_external_id",
    "question_key",
    "normalized_text",
    "coding_type",
)


def rows_to_normalized_df(rows: list[dict], coding_type: str) -> pl.DataFrame:
    """Excel parseado → DataFrame listo para el paso 2 (fuzzy)."""
    if coding_type not in ("brands", "reasons"):
        raise ValueError(f"coding_type debe ser 'brands' o 'reasons', recibido: {coding_type}")

    if not rows:
        return pl.DataFrame(schema={c: pl.Utf8 for c in OUTPUT_COLUMNS})

    df = pl.from_dicts(rows, infer_schema_length=len(rows))
    if "original_text" not in df.columns:
        raise ValueError("Faltan filas con columna original_text")

    if "question_key" not in df.columns:
        df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("question_key"))

    df = (
        df.with_columns(
            pl.col("respondent_external_id").cast(pl.Utf8),
            pl.col("question_key").cast(pl.Utf8),
            pl.col("original_text").cast(pl.Utf8),
        )
        .filter(
            pl.col("respondent_external_id").is_not_null()
            & (pl.col("respondent_external_id").str.strip_chars() != "")
        )
        .with_columns(
            pl.col("original_text")
            .map_elements(normalize, return_dtype=pl.Utf8)
            .alias("normalized_text"),
        )
        .filter(pl.col("normalized_text").str.len_chars() > 0)
        .select(
            pl.col("respondent_external_id"),
            pl.col("question_key"),
            pl.col("normalized_text"),
            pl.lit(coding_type).alias("coding_type"),
        )
    )
    return df


def normalization_stats(df: pl.DataFrame, source_rows: int, coding_type: str) -> dict:
    """Resumen para API. source_rows = filas crudas del Excel antes de filtros."""
    return {
        "coding_type": coding_type,
        "source_rows": source_rows,
        "parsed_rows": df.height,
        "empty_skipped": max(source_rows - df.height, 0),
        "unique_normalized": int(df.select("normalized_text").unique().height) if df.height else 0,
    }

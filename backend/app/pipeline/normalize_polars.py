"""Pipeline Polars: filas del Excel → DataFrame normalizado.

HANDOFF PASO 2 (fuzzy matching)
------------------------------
Parquet en Storage (un archivo por estudio, nunca mezcla marcas y razones):

    uploads/{studio_id}/{file_id}/normalized.parquet

Cargar:

    from app.pipeline.normalize_polars import load_normalized_df
    df = load_normalized_df(studio_id, file_id)

Columnas del Parquet:
    respondent_external_id  — ID del encuestado
    question_key            — pregunta (para reexportar / join a verbatims)
    normalized_text         — verbatim limpio (input del fuzzy)
    coding_type             — "brands" | "reasons" (del studio, constante en el archivo)

Marcas vs razones
-----------------
Cada studio tiene UN coding_type. El Parquet de Marcas y el de Razones son archivos
distintos bajo distinto studio_id. El paso 2 lee coding_type del DataFrame y decide:

  brands  → fuzzy (pipeline.fuzzy) asigna como máximo 1 código por fila
  reasons → se derivan enteras a unmatched para el módulo LLM

Normalización de razones con varias palabras
--------------------------------------------
NO se parte el verbatim en normalización. Una fila = un encuestado = un texto completo:

    "Es rico y barato"  →  "es rico y barato"
"""
from __future__ import annotations

import io
import uuid
from typing import Literal

import polars as pl

from app.core import storage
from app.pipeline.normalize import normalize

CodingType = Literal["brands", "reasons"]
BUCKET = "uploads"
OUTPUT_COLUMNS = (
    "respondent_external_id",
    "question_key",
    "normalized_text",
    "coding_type",
)


def normalized_parquet_path(studio_id: uuid.UUID, file_id: uuid.UUID) -> str:
    return f"{studio_id}/{file_id}/normalized.parquet"


def rows_to_normalized_df(rows: list[dict], coding_type: str) -> pl.DataFrame:
    """Excel parseado → DataFrame listo para Parquet y paso 2 (fuzzy)."""
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


def preview_rows(df: pl.DataFrame, limit: int = 5) -> list[dict]:
    if df.is_empty():
        return []
    return [dict(r) for r in df.head(limit).iter_rows(named=True)]


def save_normalized_df(studio_id: uuid.UUID, file_id: uuid.UUID, df: pl.DataFrame) -> str:
    buf = io.BytesIO()
    df.write_parquet(buf)
    path = normalized_parquet_path(studio_id, file_id)
    return storage.upload(BUCKET, path, buf.getvalue(), content_type="application/octet-stream")


def load_normalized_df(studio_id: uuid.UUID, file_id: uuid.UUID) -> pl.DataFrame:
    path = normalized_parquet_path(studio_id, file_id)
    content = storage.download(BUCKET, path)
    df = pl.read_parquet(io.BytesIO(content))
    if "question_key" not in df.columns:
        df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("question_key"))
    return df

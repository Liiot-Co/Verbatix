"""Pipeline Polars: filas del Excel → DataFrame normalizado.

HANDOFF PASO 2 (fuzzy matching)
------------------------------
Parquet en Storage (un archivo por estudio, nunca mezcla marcas y razones):

    uploads/{studio_id}/{file_id}/normalized.parquet

Cargar:

    from app.services.normalize_pipeline import load_normalized_df
    df = load_normalized_df(studio_id, file_id)

Columnas del Parquet (solo 3):
    respondent_external_id  — ID del encuestado
    normalized_text         — verbatim limpio (input del fuzzy)
    coding_type             — "brands" | "reasons" (del studio, constante en el archivo)

Marcas vs razones
-----------------
Cada studio tiene UN coding_type. El Parquet de Marcas y el de Razones son archivos
distintos bajo distinto studio_id. El paso 2 lee coding_type del DataFrame y decide:

  brands  → fuzzy devuelve como máximo 1 código por fila
  reasons → fuzzy puede devolver N códigos por fila (varias palabras/alias en el texto)

Normalización de razones con varias palabras
--------------------------------------------
NO se parte el verbatim en normalización. Una fila = un encuestado = un texto completo:

    "Es rico y barato"  →  "es rico y barato"

El paso 2 busca cada alias del codebook DENTRO del normalized_text (substring/fuzzy)
y puede asignar varios códigos a la misma fila. Eso no es trabajo del paso 1.
"""
from __future__ import annotations

import io
import uuid
from typing import Literal

import polars as pl

from app.services import storage
from app.services.normalize import normalize

CodingType = Literal["brands", "reasons"]
BUCKET = "uploads"
OUTPUT_COLUMNS = ("respondent_external_id", "normalized_text", "coding_type")


def normalized_parquet_path(studio_id: uuid.UUID, file_id: uuid.UUID) -> str:
    return f"{studio_id}/{file_id}/normalized.parquet"


def rows_to_normalized_df(rows: list[dict], coding_type: str) -> pl.DataFrame:
    """Excel parseado → DataFrame slim listo para Parquet y paso 2."""
    if coding_type not in ("brands", "reasons"):
        raise ValueError(f"coding_type debe ser 'brands' o 'reasons', recibido: {coding_type}")

    if not rows:
        return pl.DataFrame(schema={c: pl.Utf8 for c in OUTPUT_COLUMNS})

    df = pl.from_dicts(rows, infer_schema_length=len(rows))
    if "original_text" not in df.columns:
        raise ValueError("Faltan filas con columna original_text")

    df = (
        df.with_columns(
            pl.col("respondent_external_id").cast(pl.Utf8),
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
    return [
        dict(r)
        for r in df.head(limit).iter_rows(named=True)
    ]


def save_normalized_df(studio_id: uuid.UUID, file_id: uuid.UUID, df: pl.DataFrame) -> str:
    buf = io.BytesIO()
    df.write_parquet(buf)
    path = normalized_parquet_path(studio_id, file_id)
    return storage.upload(BUCKET, path, buf.getvalue(), content_type="application/octet-stream")


def load_normalized_df(studio_id: uuid.UUID, file_id: uuid.UUID) -> pl.DataFrame:
    path = normalized_parquet_path(studio_id, file_id)
    content = storage.download(BUCKET, path)
    return pl.read_parquet(io.BytesIO(content))

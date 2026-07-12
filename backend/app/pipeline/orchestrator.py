"""Flujo pedido: archivo en Supabase → normalizar → fuzzy → CSV (sin persistir)."""
from __future__ import annotations

import io
import uuid

import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import storage
from app.pipeline import excel
from app.pipeline.normalize import normalize
from app.pipeline.normalize_polars import rows_to_normalized_df
from app.pipeline.fuzzy import CodeAlias, run_fuzzy_matching
from app.pipeline.fuzzy.models import Cols, SCORE_THRESHOLD


def _split_storage_path(storage_path: str) -> tuple[str, str]:
    bucket, _, path = storage_path.partition("/")
    if not path:
        raise ValueError(f"storage_path inválido: {storage_path}")
    return bucket, path


def load_catalog_aliases(db: Session, studio_id: uuid.UUID) -> list[CodeAlias]:
    alias_rows = db.execute(
        text("""
            with latest as (
              select id from codebooks
              where studio_id = :studio
              order by version desc
              limit 1
            )
            select ca.code_id::text as code_id, ca.alias_normalized
            from code_aliases ca
            join latest l on l.id = ca.codebook_id
            where ca.alias_normalized is not null and ca.alias_normalized <> ''
        """),
        {"studio": studio_id},
    ).mappings().all()

    label_rows = db.execute(
        text("""
            with latest as (
              select id from codebooks
              where studio_id = :studio
              order by version desc
              limit 1
            )
            select c.id::text as code_id, c.label
            from codes c
            join latest l on l.id = c.codebook_id
            where c.is_active
              and coalesce(c.is_system, false) = false
              and c.label is not null
              and trim(c.label) <> ''
        """),
        {"studio": studio_id},
    ).mappings().all()

    seen: set[tuple[str, str]] = set()
    catalog: list[CodeAlias] = []

    def _add(code_id: str, alias: str) -> None:
        alias = (alias or "").strip()
        if not alias or (code_id, alias) in seen:
            return
        seen.add((code_id, alias))
        catalog.append(CodeAlias(code_id=code_id, alias_normalized=alias))

    for r in alias_rows:
        _add(r["code_id"], r["alias_normalized"])
    for r in label_rows:
        _add(r["code_id"], normalize(r["label"]))
    return catalog


def _pick_verbatims_sheet(content: bytes, preferred: str | None) -> str:
    if preferred:
        return preferred
    sheets = excel.detect_sheets(content)
    for s in sheets:
        if s["guessed_as"] == "verbatims":
            return s["name"]
    raise ValueError(
        "No se detectó hoja de verbatims. Pasa ?verbatims_sheet=NombreHoja. "
        f"Hojas: {[s['name'] for s in sheets]}"
    )


def results_to_combined_df(
    classified: pl.DataFrame,
    unmatched: pl.DataFrame,
) -> pl.DataFrame:
    classified_out = classified.with_columns(
        pl.lit("classified").alias("status"),
        pl.lit(None).cast(pl.Utf8).alias(Cols.CODING_TYPE),
    ).select(
        Cols.RESPONDENT_ID,
        Cols.QUESTION_KEY,
        Cols.NORMALIZED_TEXT,
        Cols.CODE_ID,
        Cols.MATCHED_ALIAS,
        Cols.SCORE,
        Cols.SOURCE,
        "status",
        Cols.CODING_TYPE,
    )
    unmatched_out = unmatched.with_columns(
        pl.lit(None).cast(pl.Utf8).alias(Cols.CODE_ID),
        pl.lit(None).cast(pl.Utf8).alias(Cols.MATCHED_ALIAS),
        pl.lit(None).cast(pl.Float64).alias(Cols.SCORE),
        pl.lit(None).cast(pl.Utf8).alias(Cols.SOURCE),
        pl.lit("unmatched").alias("status"),
    ).select(
        Cols.RESPONDENT_ID,
        Cols.QUESTION_KEY,
        Cols.NORMALIZED_TEXT,
        Cols.CODE_ID,
        Cols.MATCHED_ALIAS,
        Cols.SCORE,
        Cols.SOURCE,
        "status",
        Cols.CODING_TYPE,
    )
    return pl.concat([classified_out, unmatched_out], how="vertical")


def classify_file_to_csv(
    db: Session,
    file_id: uuid.UUID,
    *,
    verbatims_sheet: str | None = None,
    threshold: float = SCORE_THRESHOLD,
) -> tuple[bytes, dict]:
    """
    1. Lee imported_files por id
    2. Descarga el Excel de Supabase Storage
    3. Normaliza verbatims
    4. Fuzzy contra el codebook del studio
    5. Devuelve CSV (sin persistir clasificaciones)
    """
    meta = db.execute(
        text("""
            select f.id, f.studio_id, f.storage_path, f.original_filename,
                   s.coding_type
            from imported_files f
            join studio s on s.id = f.studio_id
            where f.id = :id
        """),
        {"id": file_id},
    ).mappings().first()
    if not meta:
        raise LookupError(f"Archivo no encontrado: {file_id}")

    bucket, path = _split_storage_path(meta["storage_path"])
    content = storage.download(bucket, path)

    sheet = _pick_verbatims_sheet(content, verbatims_sheet)
    rows = excel.parse_verbatims(content, sheet)
    df = rows_to_normalized_df(rows, meta["coding_type"])

    catalog = load_catalog_aliases(db, meta["studio_id"])
    if not catalog and meta["coding_type"] == "brands":
        raise ValueError(
            "El studio no tiene aliases/códigos en el codebook. "
            "Carga el LC antes de clasificar."
        )

    result = run_fuzzy_matching(df, catalog, threshold=threshold)
    combined = results_to_combined_df(result.classified, result.unmatched)

    buf = io.BytesIO()
    combined.write_csv(buf)
    metrics = {
        "file_id": str(file_id),
        "studio_id": str(meta["studio_id"]),
        "original_filename": meta["original_filename"],
        "verbatims_sheet": sheet,
        "coding_type": meta["coding_type"],
        "input_rows": df.height,
        "catalog_aliases": len(catalog),
        "classified": result.classified.height,
        "unmatched": result.unmatched.height,
        "auto_rate": (result.classified.height / df.height) if df.height else 0.0,
        "threshold": threshold,
        "persisted": False,
    }
    return buf.getvalue(), metrics

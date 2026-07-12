"""Prueba local del pipeline de normalización con el Excel de Gloria (sin servidor ni BD).

Uso:
  cd backend
  python scripts/test_normalize_excel.py
  python scripts/test_normalize_excel.py --sheet Verbatims_Razones --type reasons
  python scripts/test_normalize_excel.py --export salida/normalizado.csv
"""
import argparse
import sys
import time
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import excel
from app.services.normalize_pipeline import normalization_stats, preview_rows, rows_to_normalized_df

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XLSX = ROOT / "LC 32406432 TRACK MULTICATEGORY GLORIA QUESO - RONDA 4 2026.xlsx"


def main() -> None:
    parser = argparse.ArgumentParser(description="Probar normalización con Excel real")
    parser.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX, help="Ruta al Excel")
    parser.add_argument("--sheet", default="Verbatims_Marcas", help="Hoja de verbatims")
    parser.add_argument("--type", default="brands", choices=["brands", "reasons"], help="coding_type")
    parser.add_argument(
        "--export",
        type=Path,
        default=None,
        help="Guardar TODAS las filas normalizadas en CSV (ábrelo en Excel)",
    )
    parser.add_argument("--head", type=int, default=15, help="Cuántas filas mostrar en consola")
    args = parser.parse_args()

    if not args.xlsx.exists():
        raise SystemExit(f"No encontré el Excel: {args.xlsx}")

    content = args.xlsx.read_bytes()
    rows = excel.parse_verbatims(content, args.sheet)

    t0 = time.perf_counter()
    df = rows_to_normalized_df(rows, args.type)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    stats = normalization_stats(df, source_rows=len(rows), coding_type=args.type)

    print(f"Excel:          {args.xlsx.name}")
    print(f"Hoja:           {args.sheet}")
    print(f"Tipo:           {args.type}")
    print(f"Filas Excel:    {len(rows)}")
    print(f"Pipeline:       {elapsed_ms:.1f} ms")
    print(f"Stats:          {stats}")
    print()
    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        df.write_csv(args.export)
        print(f"CSV completo ({df.height} filas): {args.export.resolve()}")
        print()

    print(f"Primeras {args.head} filas normalizadas:")
    for row in df.head(args.head).iter_rows(named=True):
        print(f"  {row['respondent_external_id']:12} | {row['normalized_text']} | {row['coding_type']}")

    top = (
        df.group_by("normalized_text")
        .len()
        .sort("len", descending=True)
        .head(10)
    )
    print()
    print("Top 10 menciones (conteo):")
    for row in top.iter_rows(named=True):
        print(f"  {row['len']:4d}  {row['normalized_text']}")


if __name__ == "__main__":
    main()

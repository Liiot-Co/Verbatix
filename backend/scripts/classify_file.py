"""Prueba local: clasifica el archivo ya subido en Supabase → CSV.

  cd backend
  ./env/bin/python scripts/classify_file.py 0c32c523-6370-4506-b777-dbc889a648f6
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

for line in (BACKEND / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.services.classify_pipeline import classify_file_to_csv  # noqa: E402


def main() -> None:
    file_id = uuid.UUID(sys.argv[1] if len(sys.argv) > 1 else "0c32c523-6370-4506-b777-dbc889a648f6")
    sheet = sys.argv[2] if len(sys.argv) > 2 else "Verbatims_Marcas"

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    db = sessionmaker(bind=create_engine(url, pool_pre_ping=True))()

    csv_bytes, metrics = classify_file_to_csv(
        db, file_id, verbatims_sheet=sheet
    )
    out = BACKEND / "outputs" / f"classifications_{file_id}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(csv_bytes)
    print(metrics)
    print(f"CSV → {out} ({len(csv_bytes)} bytes)")
    db.close()


if __name__ == "__main__":
    main()

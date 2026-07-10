import sqlite3
from pathlib import Path


SEED_TERMS: list[tuple[str, str]] = [
    ("queso", "generico"),
    ("leche", "generico"),
    ("yogur", "generico"),
    ("cereales", "generico"),
    ("pan", "generico"),
    ("aceite", "generico"),
    ("arroz", "generico"),
    ("pasta", "generico"),
    ("agua", "generico"),
    ("jugo", "generico"),
    ("cerveza", "generico"),
    ("vino", "generico"),
    ("cafe", "generico"),
    ("te", "generico"),
    ("chocolate", "generico"),
    ("galletas", "generico"),
    ("papas", "generico"),
    ("fideos", "generico"),
    ("pollo", "generico"),
    ("carne", "generico"),
    ("pescado", "generico"),
    ("jabon", "generico"),
    ("shampoo", "generico"),
    ("detergente", "generico"),
    ("crema", "generico"),
    ("pasta dental", "generico"),
    ("panales", "generico"),
    ("toallas", "generico"),
    ("papel higienico", "generico"),
    ("suavizante", "generico"),
    ("tienda", "lugar"),
    ("supermercado", "lugar"),
    ("mercado", "lugar"),
    ("farmacia", "lugar"),
    ("panaderia", "lugar"),
    ("carniceria", "lugar"),
    ("verduleria", "lugar"),
    ("local", "lugar"),
    ("negocio", "lugar"),
    ("marca", "meta"),
    ("producto", "meta"),
    ("otro", "meta"),
    ("ninguno", "meta"),
    ("varios", "meta"),
    ("diversas marcas", "meta"),
    ("no recuerda", "meta"),
    ("no sabe", "meta"),
    ("generico", "meta"),
    ("compre en", "accion"),
    ("compra", "accion"),
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS generics (
    id       INTEGER PRIMARY KEY,
    term     TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'generico'
);
"""


def _get_conn(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def ensure_generics(db_path: str | Path) -> None:
    conn = _get_conn(db_path)
    try:
        existing = {row["term"] for row in conn.execute("SELECT term FROM generics")}
        to_insert = [(t, c) for t, c in SEED_TERMS if t not in existing]
        if to_insert:
            conn.executemany(
                "INSERT OR IGNORE INTO generics(term, category) VALUES (?, ?)",
                to_insert,
            )
            conn.commit()
    finally:
        conn.close()


def get_generics(db_path: str | Path) -> list[str]:
    conn = _get_conn(db_path)
    try:
        rows = conn.execute("SELECT term FROM generics ORDER BY term").fetchall()
        return [row["term"] for row in rows]
    finally:
        conn.close()

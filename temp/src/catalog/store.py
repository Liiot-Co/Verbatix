"""C1 — SQLite living-catalog store (OWNER: cursor).

Persists the products / aliases discovered from surveys plus the human-review
workflow that promotes discovery *candidates* into the approved catalog.

The store is intentionally dependency-free (stdlib ``sqlite3`` only) so it can
be built and tested independently of the discovery lane (``src/discovery/*``,
owned by opencode).

Tables
------
rounds        survey rounds (a named import of answers)
candidates    discovered terms awaiting human review
products      approved products
aliases       approved spellings/variants pointing at a product

Candidate states  : pending_review, approved_product, alias_of_existing,
                    rejected_noise, ambiguous
Product states    : approved (default), ambiguous, retired
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional

CANDIDATE_STATES = (
    "pending_review",
    "approved_product",
    "alias_of_existing",
    "rejected_noise",
    "ambiguous",
)
PRODUCT_STATES = ("approved", "ambiguous", "retired")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rounds (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'approved',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS aliases (
    id          INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL UNIQUE,
    source      TEXT NOT NULL DEFAULT 'human',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS candidates (
    id                  INTEGER PRIMARY KEY,
    term                TEXT NOT NULL,
    frequency           INTEGER NOT NULL DEFAULT 0,
    document_frequency  INTEGER NOT NULL DEFAULT 0,
    ngram               INTEGER NOT NULL DEFAULT 1,
    round_id            INTEGER REFERENCES rounds(id) ON DELETE SET NULL,
    status              TEXT NOT NULL DEFAULT 'pending_review',
    product_id          INTEGER REFERENCES products(id) ON DELETE SET NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(term, round_id)
);

CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_aliases_product ON aliases(product_id);
"""


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    status: str


@dataclass(frozen=True)
class Candidate:
    id: int
    term: str
    frequency: int
    document_frequency: int
    ngram: int
    round_id: Optional[int]
    status: str
    product_id: Optional[int]


@dataclass
class CatalogEntry:
    """One product together with all of its approved aliases."""

    product: str
    aliases: list[str] = field(default_factory=list)


class CatalogStore:
    """Thin, transactional wrapper over the SQLite living catalog."""

    def __init__(self, db_path: str | Path = "catalog.sqlite") -> None:
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "CatalogStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -- rounds -------------------------------------------------------------
    def add_round(self, name: str) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO rounds(name) VALUES (?)", (name,)
            )
            if cur.lastrowid and cur.rowcount:
                return int(cur.lastrowid)
        row = self._conn.execute(
            "SELECT id FROM rounds WHERE name = ?", (name,)
        ).fetchone()
        return int(row["id"])

    # -- candidates ---------------------------------------------------------
    def add_candidate(
        self,
        term: str,
        *,
        frequency: int = 0,
        document_frequency: int = 0,
        ngram: int = 1,
        round_id: Optional[int] = None,
    ) -> int:
        with self._tx() as c:
            cur = c.execute(
                """INSERT INTO candidates
                       (term, frequency, document_frequency, ngram, round_id)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(term, round_id) DO UPDATE SET
                       frequency = excluded.frequency,
                       document_frequency = excluded.document_frequency,
                       ngram = excluded.ngram""",
                (term, frequency, document_frequency, ngram, round_id),
            )
            if cur.lastrowid:
                return int(cur.lastrowid)
        row = self._conn.execute(
            "SELECT id FROM candidates WHERE term = ? AND round_id IS ?",
            (term, round_id),
        ).fetchone()
        return int(row["id"])

    def bulk_add_candidates(self, rows: Iterable[dict], round_id: Optional[int] = None) -> int:
        n = 0
        for r in rows:
            self.add_candidate(
                r["term"],
                frequency=int(r.get("frequency", 0)),
                document_frequency=int(r.get("document_frequency", 0)),
                ngram=int(r.get("ngram", 1)),
                round_id=round_id if round_id is not None else r.get("round_id"),
            )
            n += 1
        return n

    def list_candidates(self, status: Optional[str] = None) -> list[Candidate]:
        if status is not None and status not in CANDIDATE_STATES:
            raise ValueError(f"unknown candidate status: {status!r}")
        sql = "SELECT * FROM candidates"
        args: tuple = ()
        if status:
            sql += " WHERE status = ?"
            args = (status,)
        sql += " ORDER BY frequency DESC, term ASC"
        return [_candidate(r) for r in self._conn.execute(sql, args).fetchall()]

    # -- review workflow ----------------------------------------------------
    def approve_candidate_as_product(
        self, candidate_id: int, product_name: Optional[str] = None
    ) -> int:
        """Promote a candidate to a brand-new product; its term becomes alias #1."""
        cand = self._require_candidate(candidate_id)
        name = (product_name or cand.term).strip()
        with self._tx() as c:
            pid = self._upsert_product(c, name)
            self._add_alias(c, pid, cand.term, source="discovery")
            c.execute(
                "UPDATE candidates SET status='approved_product', product_id=? WHERE id=?",
                (pid, candidate_id),
            )
        return pid

    def approve_candidate_as_alias(self, candidate_id: int, product_id: int) -> None:
        """Attach a misspelled/variant candidate to an existing product."""
        cand = self._require_candidate(candidate_id)
        self._require_product(product_id)
        with self._tx() as c:
            self._add_alias(c, product_id, cand.term, source="discovery")
            c.execute(
                "UPDATE candidates SET status='alias_of_existing', product_id=? WHERE id=?",
                (product_id, candidate_id),
            )

    def reject_candidate(self, candidate_id: int) -> None:
        self._set_candidate_status(candidate_id, "rejected_noise")

    def mark_candidate_ambiguous(self, candidate_id: int) -> None:
        self._set_candidate_status(candidate_id, "ambiguous")

    # -- products / aliases -------------------------------------------------
    def add_product(self, name: str, status: str = "approved") -> int:
        if status not in PRODUCT_STATES:
            raise ValueError(f"unknown product status: {status!r}")
        with self._tx() as c:
            pid = self._upsert_product(c, name.strip())
            c.execute("UPDATE products SET status=? WHERE id=?", (status, pid))
        return pid

    def add_alias(self, product_id: int, alias: str, source: str = "human") -> None:
        self._require_product(product_id)
        with self._tx() as c:
            self._add_alias(c, product_id, alias, source=source)

    def list_products(self) -> list[Product]:
        rows = self._conn.execute(
            "SELECT * FROM products ORDER BY name"
        ).fetchall()
        return [Product(int(r["id"]), r["name"], r["status"]) for r in rows]

    def catalog(self) -> list[CatalogEntry]:
        """The approved catalog as product -> aliases, ready for the classifier."""
        rows = self._conn.execute(
            """SELECT p.name AS product, a.alias AS alias
               FROM products p
               LEFT JOIN aliases a ON a.product_id = p.id
               WHERE p.status != 'retired'
               ORDER BY p.name, a.alias"""
        ).fetchall()
        by_product: dict[str, CatalogEntry] = {}
        for r in rows:
            entry = by_product.setdefault(r["product"], CatalogEntry(r["product"]))
            if r["alias"]:
                entry.aliases.append(r["alias"])
        return list(by_product.values())

    def alias_map(self) -> dict[str, str]:
        """Flat ``alias -> product`` mapping (the classifier's input)."""
        out: dict[str, str] = {}
        for entry in self.catalog():
            for alias in entry.aliases:
                out[alias] = entry.product
        return out

    # -- internals ----------------------------------------------------------
    def _upsert_product(self, c: sqlite3.Connection, name: str) -> int:
        c.execute("INSERT OR IGNORE INTO products(name) VALUES (?)", (name,))
        row = c.execute("SELECT id FROM products WHERE name=?", (name,)).fetchone()
        return int(row["id"])

    def _add_alias(
        self, c: sqlite3.Connection, product_id: int, alias: str, *, source: str
    ) -> None:
        c.execute(
            "INSERT OR IGNORE INTO aliases(product_id, alias, source) VALUES (?, ?, ?)",
            (product_id, alias.strip().lower(), source),
        )

    def _set_candidate_status(self, candidate_id: int, status: str) -> None:
        self._require_candidate(candidate_id)
        with self._tx() as c:
            c.execute(
                "UPDATE candidates SET status=? WHERE id=?", (status, candidate_id)
            )

    def _require_candidate(self, candidate_id: int) -> Candidate:
        row = self._conn.execute(
            "SELECT * FROM candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"candidate {candidate_id} not found")
        return _candidate(row)

    def _require_product(self, product_id: int) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM products WHERE id=?", (product_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"product {product_id} not found")


def _candidate(row: sqlite3.Row) -> Candidate:
    return Candidate(
        id=int(row["id"]),
        term=row["term"],
        frequency=int(row["frequency"]),
        document_frequency=int(row["document_frequency"]),
        ngram=int(row["ngram"]),
        round_id=row["round_id"],
        status=row["status"],
        product_id=row["product_id"],
    )

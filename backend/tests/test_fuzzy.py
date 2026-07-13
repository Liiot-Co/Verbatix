"""Tests unitarios del fuzzy matching (pipeline.fuzzy)."""
import uuid

import polars as pl

from app.pipeline.fuzzy import (
    CodeAlias,
    discover_catalog_from_frequency,
    run_fuzzy_matching,
)
from app.pipeline.fuzzy.models import Cols


CATALOG = [
    CodeAlias(code_id="c-gloria", alias_normalized="gloria"),
    CodeAlias(code_id="c-gloria", alias_normalized="fresco gloria"),
    CodeAlias(code_id="c-laive", alias_normalized="laive"),
    CodeAlias(code_id="c-bonle", alias_normalized="bonle"),
    CodeAlias(code_id="c-otto", alias_normalized="otto kunz"),
]


def _df(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def test_fuzzy_classifies_typos_and_exact():
    df = _df(
        [
            {
                "respondent_external_id": "1",
                "question_key": "q1",
                "normalized_text": "gloria",
                "coding_type": "brands",
            },
            {
                "respondent_external_id": "2",
                "question_key": "q1",
                "normalized_text": "glorai",
                "coding_type": "brands",
            },
            {
                "respondent_external_id": "3",
                "question_key": "q1",
                "normalized_text": "layve",
                "coding_type": "brands",
            },
            {
                "respondent_external_id": "4",
                "question_key": "q1",
                "normalized_text": "xyzmarca",
                "coding_type": "brands",
            },
        ]
    )
    res = run_fuzzy_matching(df, CATALOG)
    assert res.classified.height >= 2
    assert "xyzmarca" in res.unmatched[Cols.NORMALIZED_TEXT].to_list()
    assert set(res.classified[Cols.SOURCE].unique().to_list()) == {"engine_fuzzy"}


def test_reasons_all_go_unmatched():
    df = _df(
        [
            {
                "respondent_external_id": "1",
                "question_key": "q2",
                "normalized_text": "es rico y barato",
                "coding_type": "reasons",
            },
            {
                "respondent_external_id": "2",
                "question_key": "q2",
                "normalized_text": "gloria",
                "coding_type": "reasons",
            },
        ]
    )
    res = run_fuzzy_matching(df, CATALOG)
    assert res.classified.height == 0
    assert res.unmatched.height == 2


def test_empty_catalog_all_unmatched():
    df = _df(
        [
            {
                "respondent_external_id": "1",
                "question_key": "q1",
                "normalized_text": "gloria",
                "coding_type": "brands",
            },
        ]
    )
    res = run_fuzzy_matching(df, [])
    assert res.classified.height == 0
    assert res.unmatched.height == 1


# --------------------------------------------------------------------------- #
# Catálogo derivado de frecuencia (fallback sin codebook)
# --------------------------------------------------------------------------- #
class _FreqResult:
    def __init__(self, rows=None, scalar=None):
        self._rows, self._scalar = rows or [], scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class _FreqSession:
    """FakeSession que sirve el codebook, las semillas y captura los inserts."""

    def __init__(self, codebook_id, seeds):
        self._codebook_id = codebook_id
        self._seeds = seeds
        self.inserted_codes = []
        self.inserted_aliases = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "from codebooks" in sql:
            return _FreqResult(scalar=self._codebook_id)
        if "from mention_groups" in sql:
            return _FreqResult(rows=self._seeds)
        if "max(code_number)" in sql:
            return _FreqResult(scalar=1)
        if "insert into codes" in sql:
            self.inserted_codes.append(params)
        elif "insert into code_aliases" in sql:
            self.inserted_aliases.append(params)
        return _FreqResult()


def test_discover_catalog_promotes_frequent_groups_to_seeds():
    seeds = [
        {"normalized_text": "bonle", "sample_text": "Bonle", "frequency_count": 10},
        {"normalized_text": "gloria", "sample_text": "Gloria", "frequency_count": 7},
    ]
    db = _FreqSession(codebook_id=uuid.uuid4(), seeds=seeds)

    catalog = discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=5)

    # Cada semilla -> un code nuevo + un alias, y el catálogo apunta a esos codes.
    assert [c.alias_normalized for c in catalog] == ["bonle", "gloria"]
    assert len(db.inserted_codes) == 2
    assert len(db.inserted_aliases) == 2
    # Numeración correlativa desde el siguiente code libre.
    assert [c["n"] for c in db.inserted_codes] == [1, 2]
    # El alias del code apunta al mismo code_id que se persistió.
    assert db.inserted_aliases[0]["code"] == db.inserted_codes[0]["id"]
    assert str(db.inserted_codes[0]["id"]) == catalog[0].code_id


def test_discover_catalog_empty_when_no_group_reaches_minimum():
    db = _FreqSession(codebook_id=uuid.uuid4(), seeds=[])

    catalog = discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=10)

    assert catalog == []
    assert db.inserted_codes == []

"""Tests unitarios del fuzzy matching (pipeline.fuzzy)."""
import uuid

import polars as pl

from app.pipeline.fuzzy import (
    CodeAlias,
    discover_catalog_from_frequency,
    run_fuzzy_matching,
)
from app.pipeline.fuzzy.catalog import promote_llm_result_to_alias
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


def test_short_text_requires_exact_match():
    # WRatio escala partial_ratio: 'uno' contra 'ninguno' da 90 por substring.
    # Un texto corto solo debe clasificar por match exacto.
    df = _df(
        [
            {"respondent_external_id": "1", "question_key": "q1",
             "normalized_text": "uno", "coding_type": "brands"},
            {"respondent_external_id": "2", "question_key": "q1",
             "normalized_text": "ninguno", "coding_type": "brands"},
        ]
    )
    res = run_fuzzy_matching(df, [CodeAlias(code_id="c-98", alias_normalized="ninguno")])
    classified = {r[Cols.NORMALIZED_TEXT] for r in res.classified.iter_rows(named=True)}
    assert classified == {"ninguno"}  # exacto pasa; 'uno' va al LLM


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
    """FakeSession que sirve el codebook, las semillas, los códigos de sistema
    y captura los inserts."""

    def __init__(self, codebook_id, seeds, system_codes=None, next_number=1):
        self._codebook_id = codebook_id
        self._seeds = seeds
        self._system_codes = system_codes or []
        self._next_number = next_number
        self.inserted_codes = []
        self.inserted_aliases = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "codebook_id from subprojects" in sql:
            return _FreqResult(scalar=self._codebook_id)
        if "select exists" in sql and "from codes" in sql:
            return _FreqResult(scalar=False)
        if "from mention_groups" in sql:
            return _FreqResult(rows=self._seeds)
        if "is_system and system_type is not null" in sql:
            return _FreqResult(rows=self._system_codes)
        if "max(code_number)" in sql:
            return _FreqResult(scalar=self._next_number)
        if "insert into codes" in sql:
            self.inserted_codes.append(params)
        elif "insert into code_aliases" in sql:
            self.inserted_aliases.append(params)
        return _FreqResult()


def test_discover_catalog_promotes_frequent_groups_to_seeds():
    seeds = [
        {"id": uuid.uuid4(), "normalized_text": "bonle", "sample_text": "Bonle", "frequency_count": 10},
        {"id": uuid.uuid4(), "normalized_text": "gloria", "sample_text": "Gloria", "frequency_count": 7},
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


def test_discover_catalog_routes_system_responses_to_system_codes():
    # "no se" es de los textos más frecuentes: no debe volverse una marca falsa,
    # sino alias del código de sistema 96 para que el fuzzy lo codifique ahí.
    code_96 = str(uuid.uuid4())
    seeds = [
        {"id": uuid.uuid4(), "normalized_text": "bonle", "sample_text": "Bonle", "frequency_count": 12},
        {"id": uuid.uuid4(), "normalized_text": "no se", "sample_text": "No se", "frequency_count": 10},
    ]
    db = _FreqSession(
        codebook_id=uuid.uuid4(),
        seeds=seeds,
        system_codes=[{"code_id": code_96, "system_type": "no_answer"}],
    )

    catalog = discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=10)

    # Solo 'bonle' se promueve a code nuevo; 'no se' apunta al code de sistema.
    assert len(db.inserted_codes) == 1
    assert db.inserted_codes[0]["label"] == "Bonle"
    by_alias = {c.alias_normalized: c.code_id for c in catalog}
    assert by_alias["no se"] == code_96
    assert by_alias["no sabe"] == code_96  # variantes canónicas también en catálogo
    assert by_alias["bonle"] == db.inserted_codes[0]["id"]


def test_discover_catalog_clusters_typo_seeds_as_aliases():
    seeds = [
        {"id": uuid.uuid4(), "normalized_text": "gloria", "sample_text": "Gloria", "frequency_count": 20},
        {"id": uuid.uuid4(), "normalized_text": "gloriaa", "sample_text": "GLORIAA", "frequency_count": 6},
    ]
    db = _FreqSession(codebook_id=uuid.uuid4(), seeds=seeds)

    catalog = discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=5)

    # 'gloriaa' es typo de 'gloria': un solo code, dos aliases al mismo code_id.
    assert len(db.inserted_codes) == 1
    by_alias = {c.alias_normalized: c.code_id for c in catalog}
    assert by_alias["gloriaa"] == by_alias["gloria"]


def test_discover_catalog_numbering_skips_system_range():
    seeds = [
        {"id": uuid.uuid4(), "normalized_text": "bonle", "sample_text": "Bonle", "frequency_count": 10},
        {"id": uuid.uuid4(), "normalized_text": "gloria", "sample_text": "Gloria", "frequency_count": 8},
    ]
    # El siguiente número libre cae en el rango de sistema (95-99): debe saltarlo.
    db = _FreqSession(codebook_id=uuid.uuid4(), seeds=seeds, next_number=95)

    discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=5)

    assert [c["n"] for c in db.inserted_codes] == [100, 101]


class _PromoteSession:
    """Captura el INSERT ... ON CONFLICT de promote_llm_result_to_alias."""

    def __init__(self):
        self.executed = []

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        return _FreqResult()


def test_promote_llm_result_to_alias_inserts_with_llm_promoted_origin():
    db = _PromoteSession()
    code_id = str(uuid.uuid4())

    promote_llm_result_to_alias(db, code_id, "gloria", "Gloria!", 0.95)

    sql, params = db.executed[0]
    assert "llm_promoted" in sql
    assert "on conflict" in sql
    assert "occurrences = code_aliases.occurrences + 1" in sql
    assert params == {"code": code_id, "norm": "gloria", "sample": "Gloria!", "score": 0.95}


def test_promote_llm_result_to_alias_skips_blank_alias():
    db = _PromoteSession()

    promote_llm_result_to_alias(db, str(uuid.uuid4()), "   ", "sample", 0.95)

    assert db.executed == []


def test_discover_catalog_clusters_sub_threshold_typos_by_combined_frequency():
    """Regresión: 'kraf' (1 mención) y 'kraft' (1 mención) son la misma marca
    real, pero ninguna por separado alcanza min_mentions=3. Antes se perdían
    ambas (nunca se comparaban entre sí porque el filtro de frecuencia las
    excluía de la query antes de intentar agruparlas). Ahora se agrupan primero
    por similitud y el mínimo se evalúa sobre la suma del cluster."""
    seeds = [
        {"normalized_text": "kraft", "sample_text": "Kraft", "frequency_count": 1},
        {"normalized_text": "kraf", "sample_text": "Kraf", "frequency_count": 1},
    ]
    db = _FreqSession(codebook_id=uuid.uuid4(), seeds=seeds)

    catalog = discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=3)

    # Un solo code para ambas variantes: la suma (1+1=2) alcanza el mínimo...
    assert len(db.inserted_codes) == 0  # 1+1=2 < 3: no alcanza ni sumado, sigue sin code (correcto)


def test_discover_catalog_promotes_cluster_when_combined_frequency_reaches_minimum():
    seeds = [
        {"id": uuid.uuid4(), "normalized_text": "kraft", "sample_text": "Kraft", "frequency_count": 2},
        {"id": uuid.uuid4(), "normalized_text": "kraftt", "sample_text": "Kraftt", "frequency_count": 1},
    ]
    db = _FreqSession(codebook_id=uuid.uuid4(), seeds=seeds)

    catalog = discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=3)

    # 2+1=3 alcanza el mínimo: un solo code para ambas variantes (antes se
    # perdían las dos por no comparase entre sí al ser individualmente < 3).
    assert len(db.inserted_codes) == 1
    assert db.inserted_codes[0]["label"] == "Kraft"
    by_alias = {c.alias_normalized: c.code_id for c in catalog}
    assert by_alias["kraft"] == by_alias["kraftt"] == db.inserted_codes[0]["id"]


def test_discover_catalog_never_clusters_bone_into_bonle():
    seeds = [
        {"id": uuid.uuid4(), "normalized_text": "bonle", "sample_text": "Bonlé", "frequency_count": 5},
        {"id": uuid.uuid4(), "normalized_text": "bone", "sample_text": "Bone", "frequency_count": 5},
    ]
    db = _FreqSession(codebook_id=uuid.uuid4(), seeds=seeds)

    discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=5)

    assert len(db.inserted_codes) == 2

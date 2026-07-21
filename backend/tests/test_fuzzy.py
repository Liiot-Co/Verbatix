"""Tests unitarios del fuzzy matching (pipeline.fuzzy)."""
import uuid

import polars as pl

from app.pipeline.fuzzy import (
    CodeAlias,
    discover_catalog_from_frequency,
    discover_new_brands,
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


def test_discover_catalog_merges_edan_into_frequent_edam_seed():
    seeds = [
        {"id": uuid.uuid4(), "normalized_text": "edam", "sample_text": "Edam", "frequency_count": 30},
        {"id": uuid.uuid4(), "normalized_text": "edan", "sample_text": "Edan", "frequency_count": 10},
    ]
    db = _FreqSession(codebook_id=uuid.uuid4(), seeds=seeds)

    catalog = discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=2)

    assert len(db.inserted_codes) == 1
    assert db.inserted_codes[0]["label"] == "Edam"
    by_alias = {item.alias_normalized: item.code_id for item in catalog}
    assert by_alias["edan"] == by_alias["edam"] == db.inserted_codes[0]["id"]


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


def test_is_junk_brand_seed_helper():
    from app.pipeline.fuzzy.catalog import _is_junk_brand_seed

    for junk in ["a", "no", "el", "la", "de", "xy", "  "]:
        assert _is_junk_brand_seed(junk) is True
    for real in ["gloria", "bonle", "wong", "otto kunz", "kfc"]:
        assert _is_junk_brand_seed(real) is False


def test_discover_catalog_skips_junk_stopword_seeds():
    # 'no' es frecuente pero es stopword: NO debe volverse el código basura 'No'.
    seeds = [
        {"id": uuid.uuid4(), "normalized_text": "no", "sample_text": "No", "frequency_count": 10},
        {"id": uuid.uuid4(), "normalized_text": "gloria", "sample_text": "Gloria", "frequency_count": 8},
    ]
    db = _FreqSession(codebook_id=uuid.uuid4(), seeds=seeds)

    discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=3)

    labels = [c["label"] for c in db.inserted_codes]
    assert labels == ["Gloria"]


def test_looks_like_multiple_brands_helper():
    from app.pipeline.fuzzy.catalog import _looks_like_multiple_brands

    known = {"edam", "laive", "gloria", "wong"}
    # Dos marcas conocidas juntas -> respuesta multi-marca (no se fusiona).
    assert _looks_like_multiple_brands("edam laive", known) is True
    assert _looks_like_multiple_brands("gloria wong", known) is True
    # Marca legítima de dos palabras cuyos tokens NO son marcas sueltas -> se crea.
    assert _looks_like_multiple_brands("otto kunz", known) is False
    # Una sola palabra, o solo un token que es marca -> no dispara.
    assert _looks_like_multiple_brands("gloria", known) is False
    assert _looks_like_multiple_brands("laive natural", known) is False


def test_discover_catalog_does_not_merge_two_brand_answer_into_one_code():
    # 'edam' y 'laive' son marcas distintas; una respuesta 'edam laive' NO debe
    # volverse un código fusionado 'Edam Laive' — se deja para revisión humana.
    seeds = [
        {"id": uuid.uuid4(), "normalized_text": "edam", "sample_text": "Edam", "frequency_count": 6},
        {"id": uuid.uuid4(), "normalized_text": "laive", "sample_text": "Laive", "frequency_count": 5},
        {"id": uuid.uuid4(), "normalized_text": "edam laive", "sample_text": "Edam Laive", "frequency_count": 4},
    ]
    db = _FreqSession(codebook_id=uuid.uuid4(), seeds=seeds)

    discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=3)

    labels = [c["label"] for c in db.inserted_codes]
    assert "Edam" in labels and "Laive" in labels
    # No hay código que combine ambas marcas.
    assert not any("edam" in l.lower() and "laive" in l.lower() for l in labels)
    assert len(db.inserted_codes) == 2


def test_discover_catalog_never_clusters_bone_into_bonle():
    seeds = [
        {"id": uuid.uuid4(), "normalized_text": "bonle", "sample_text": "Bonlé", "frequency_count": 5},
        {"id": uuid.uuid4(), "normalized_text": "bone", "sample_text": "Bone", "frequency_count": 5},
    ]
    db = _FreqSession(codebook_id=uuid.uuid4(), seeds=seeds)

    discover_catalog_from_frequency(db, uuid.uuid4(), min_mentions=5)

    assert len(db.inserted_codes) == 2


# --------------------------------------------------------------------------- #
# Marcas nuevas por frecuencia en rondas HEREDADAS (discover_new_brands)
# --------------------------------------------------------------------------- #
class _NBResult:
    def __init__(self, rows=None, scalar=None, mapping=None):
        self._rows, self._scalar, self._mapping = rows or [], scalar, mapping

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._mapping

    def scalar(self):
        return self._scalar


class _NewBrandSession:
    """Fake que sirve el subproyecto/origen, los candidatos pendientes y la
    numeración, y captura los inserts de discover_new_brands."""

    def __init__(self, origin, candidates):
        self.origin = origin
        self.candidates = candidates
        self.inserted_codes = []
        self.inserted_aliases = []
        self.suggested = []
        self.inserted_verbatim_codes = []
        self.coded_verbatims = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "sp.coding_type" in sql and "cb.origin" in sql:
            return _NBResult(mapping={
                "codebook_id": "cb-1", "coding_type": "brands",
                "codebook_origin": self.origin,
            })
        if "status = 'pending_review'" in sql and "frequency_count" in sql:
            return _NBResult(rows=self.candidates)
        if "max(code_number)" in sql:
            return _NBResult(scalar=1)
        if "select code_number from codes" in sql:
            return _NBResult(rows=[])
        if sql.strip().startswith("insert into codes"):
            self.inserted_codes.append(params)
        elif sql.strip().startswith("insert into code_aliases"):
            self.inserted_aliases.append(params)
        elif sql.strip().startswith("update mention_groups"):
            self.suggested.append(params)
        elif sql.strip().startswith("insert into verbatim_codes"):
            self.inserted_verbatim_codes.append(params)
        elif sql.strip().startswith("update verbatims"):
            self.coded_verbatims.append(params)
        return _NBResult()


def test_discover_new_brands_auto_codes_when_scratch_auto_approve_on(monkeypatch):
    # Paridad con el path DE CERO: con auto_approve_scratch_codebook (default) la
    # marca redescubierta nace 'approved' y sus menciones 'auto_coded' con
    # verbatim_codes activos — no queda como mera sugerencia.
    from app.core.config import settings
    monkeypatch.setattr(settings, "auto_approve_scratch_codebook", True)
    candidates = [
        {"id": uuid.uuid4(), "normalized_text": "wong", "sample_text": "Wong", "frequency_count": 4},
        {"id": uuid.uuid4(), "normalized_text": "metro", "sample_text": "Metro", "frequency_count": 1},
    ]
    db = _NewBrandSession(origin="inherited", candidates=candidates)

    grouped = discover_new_brands(db, uuid.uuid4(), min_mentions=3)

    # 'wong' (4 >= 3) nace como código; 'metro' (1 < 3) sigue pending_review al LLM.
    assert grouped == 1
    assert len(db.inserted_codes) == 1
    assert db.inserted_codes[0]["label"] == "Wong"
    assert db.inserted_codes[0]["approval"] == "approved"
    assert len(db.inserted_aliases) == 1  # un execute (lista de params) por code
    assert db.inserted_aliases[0][0]["status"] == "approved"
    assert db.suggested[0]["status"] == "auto_coded"
    # Escribe la clasificación activa (cuenta como auto-codificada, no cae al 95).
    assert len(db.inserted_verbatim_codes) == 1
    assert len(db.coded_verbatims) == 1


def test_discover_new_brands_stays_pending_when_human_gate(monkeypatch):
    # Sin auto-aprobación (gate humano): la marca nueva queda como propuesta
    # 'pending'/'suggested' para revisión, sin escribir clasificación activa.
    from app.core.config import settings
    monkeypatch.setattr(settings, "auto_approve_scratch_codebook", False)
    candidates = [
        {"id": uuid.uuid4(), "normalized_text": "wong", "sample_text": "Wong", "frequency_count": 4},
    ]
    db = _NewBrandSession(origin="inherited", candidates=candidates)

    grouped = discover_new_brands(db, uuid.uuid4(), min_mentions=3)

    assert grouped == 1
    assert db.inserted_codes[0]["approval"] == "pending"
    assert db.inserted_aliases[0][0]["status"] == "pending"
    assert db.suggested[0]["status"] == "suggested"
    assert db.inserted_verbatim_codes == []
    assert db.coded_verbatims == []


def test_discover_new_brands_is_noop_for_scratch_round():
    # En scratch ya descubrió su catálogo discover_catalog_from_frequency: no duplica.
    db = _NewBrandSession(
        origin="scratch",
        candidates=[{"id": uuid.uuid4(), "normalized_text": "wong", "sample_text": "Wong", "frequency_count": 9}],
    )

    assert discover_new_brands(db, uuid.uuid4(), min_mentions=3) == 0
    assert db.inserted_codes == []

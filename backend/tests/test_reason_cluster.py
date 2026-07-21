"""Bootstrap del codebook de razones (pipeline/semantic/cluster.py) — mocks
embed()/propose_reason_codes() para no pegarle al modelo real ni al LLM (mismo
criterio que test_semantic_cache.py)."""
import uuid
from unittest.mock import patch

from app.pipeline.semantic.cluster import cluster_by_similarity, discover_reason_catalog


def test_cluster_by_similarity_groups_near_duplicates_and_keeps_distinct_apart():
    items = [
        ("es rico", [1.0, 0.0], 5),
        ("tiene buen sabor", [0.99, 0.01], 3),  # casi idéntico al primero -> mismo cluster
        ("es barato", [0.0, 1.0], 2),  # ortogonal -> cluster propio
    ]

    clusters = cluster_by_similarity(items, threshold=0.9)

    assert len(clusters) == 2
    sabor = next(c for c in clusters if c["representative"] == "es rico")
    precio = next(c for c in clusters if c["representative"] == "es barato")
    assert sabor["total_frequency"] == 8  # 5 + 3
    assert precio["total_frequency"] == 2


def test_cluster_by_similarity_below_threshold_stays_separate():
    items = [("a", [1.0, 0.0], 1), ("b", [0.0, 1.0], 1)]

    clusters = cluster_by_similarity(items, threshold=0.9)

    assert len(clusters) == 2


def test_cluster_by_similarity_is_independent_of_input_order():
    items = [
        ("es rico", [1.0, 0.0], 5),
        ("tiene buen sabor", [0.99, 0.01], 3),
        ("es barato", [0.0, 1.0], 2),
    ]

    forward = cluster_by_similarity(items, threshold=0.9)
    reversed_order = cluster_by_similarity(list(reversed(items)), threshold=0.9)

    assert forward == reversed_order
    assert forward[0]["central_examples"]


class FakeResult:
    def __init__(self, scalar=None, mappings_list=None, rowcount=0):
        self._scalar = scalar
        self._mappings_list = mappings_list if mappings_list is not None else []
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def all(self):
        return self._mappings_list

    def first(self):
        return self._mappings_list[0] if self._mappings_list else None


class FakeSession:
    def __init__(self, codebook_id=None, has_own_codes=False, candidates=None):
        self.codebook_id = codebook_id
        self.has_own_codes = has_own_codes
        self.candidates = candidates or []
        self.inserted_codes: list[dict] = []
        self.group_updates: list[dict] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        if "select codebook_id from subprojects" in sql:
            return FakeResult(scalar=self.codebook_id)
        if "exists(select 1 from codes where codebook_id" in sql:
            return FakeResult(scalar=self.has_own_codes)
        if "from mention_groups" in sql:
            return FakeResult(mappings_list=self.candidates)
        if "coalesce(max(code_number), 0) + 1" in sql:
            return FakeResult(scalar=1)
        if "insert into codes" in sql:
            self.inserted_codes.append(params)
            return FakeResult()
        if "update mention_groups" in sql:
            self.group_updates.append(params)
            return FakeResult()
        return FakeResult()


def test_discover_reason_catalog_skips_when_codebook_already_has_own_codes():
    db = FakeSession(codebook_id=uuid.uuid4(), has_own_codes=True)

    n = discover_reason_catalog(db, uuid.uuid4(), min_mentions=3)

    assert n == 0
    assert db.inserted_codes == []


def test_discover_reason_catalog_creates_codes_only_for_clusters_above_threshold():
    candidates = [
        {"id": uuid.uuid4(), "normalized_text": "es rico", "sample_text": "Es rico", "frequency_count": 5},
        {"id": uuid.uuid4(), "normalized_text": "tiene buen sabor", "sample_text": "Tiene buen sabor", "frequency_count": 3},
        {"id": uuid.uuid4(), "normalized_text": "compro la", "sample_text": "Compro la", "frequency_count": 1},
    ]
    db = FakeSession(codebook_id=uuid.uuid4(), has_own_codes=False, candidates=candidates)

    def fake_embed_many(texts):
        # "sabor" cluster comparte vector; "compro la" queda aparte y bajo el umbral.
        return [
            [1.0, 0.0] if ("rico" in t or "sabor" in t) else [0.0, 1.0]
            for t in texts
        ]

    with (
        patch("app.pipeline.semantic.cluster.embed_many", side_effect=fake_embed_many),
        patch("app.pipeline.semantic.cluster.propose_reason_codes", return_value=[{
            "net": "Experiencia sensorial",
            "label": "Buen sabor",
            "definition": "Valora positivamente el sabor.",
            "inclusion_criteria": ["Expresa agrado por el sabor"],
            "exclusion_criteria": ["Solo menciona precio"],
            "examples": ["Es rico", "Tiene buen sabor"],
        }]),
    ):
        n = discover_reason_catalog(db, uuid.uuid4(), min_mentions=3)

    assert n == 1
    assert len(db.inserted_codes) == 1
    assert db.inserted_codes[0]["label"] == "Buen sabor"
    assert db.inserted_codes[0]["definition"] == "Valora positivamente el sabor."
    assert db.inserted_codes[0]["n"] == 1


def test_discover_reason_catalog_dedupes_codes_with_same_label():
    """DeepSeek puede etiquetar dos clusters distintos con la misma categoría
    ("Nutrición"). El bootstrap debe crear UN solo código y apuntar ambos
    clusters a él — no duplicar el código en el codebook."""
    candidates = [
        {"id": uuid.uuid4(), "normalized_text": "es nutritivo", "sample_text": "Es nutritivo", "frequency_count": 4},
        {"id": uuid.uuid4(), "normalized_text": "alimenta bien", "sample_text": "Alimenta bien", "frequency_count": 4},
    ]
    db = FakeSession(codebook_id=uuid.uuid4(), has_own_codes=False, candidates=candidates)

    def fake_embed_many(texts):
        # dos clusters ortogonales, ambos >= min_mentions.
        return [[1.0, 0.0] if "nutritivo" in t else [0.0, 1.0] for t in texts]

    same_label = {
        "net": "Nutrición",
        "label": "Nutrición",
        "definition": "Menciona aporte nutricional.",
        "inclusion_criteria": ["Habla de nutrición"],
        "exclusion_criteria": ["Solo precio"],
        "examples": ["Es nutritivo", "Alimenta bien"],
    }

    with (
        patch("app.pipeline.semantic.cluster.embed_many", side_effect=fake_embed_many),
        patch("app.pipeline.semantic.cluster.propose_reason_codes", return_value=[same_label, dict(same_label)]),
    ):
        n = discover_reason_catalog(db, uuid.uuid4(), min_mentions=3)

    # Un solo código creado pese a dos clusters con el mismo label.
    assert n == 1
    assert len(db.inserted_codes) == 1
    # Ambos clusters quedan apuntados a un único code_id.
    assigned_codes = {u["code"] for u in db.group_updates}
    assert len(assigned_codes) == 1
    assert assigned_codes == {db.inserted_codes[0]["id"]}


def test_discover_reason_catalog_noop_when_no_pending_candidates():
    db = FakeSession(codebook_id=uuid.uuid4(), has_own_codes=False, candidates=[])

    n = discover_reason_catalog(db, uuid.uuid4(), min_mentions=3)

    assert n == 0

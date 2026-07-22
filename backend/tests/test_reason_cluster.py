"""Bootstrap del codebook de razones (pipeline/semantic/cluster.py) — mocks
embed()/propose_reason_codes() para no pegarle al modelo real ni al LLM (mismo
criterio que test_semantic_cache.py)."""
import uuid
from unittest.mock import patch

from app.pipeline.semantic.cluster import (
    _propose_reason_codes_parallel,
    cluster_by_similarity,
    discover_new_reasons,
    discover_reason_catalog,
)


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
    def __init__(self, scalar=None, mappings_list=None, rowcount=0, scalars_list=None):
        self._scalar = scalar
        self._mappings_list = mappings_list if mappings_list is not None else []
        self._scalars_list = scalars_list if scalars_list is not None else []
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return self._mappings_list or self._scalars_list

    def first(self):
        return self._mappings_list[0] if self._mappings_list else None


class FakeSession:
    def __init__(self, codebook_id=None, has_own_codes=False, candidates=None, existing_nets=None):
        self.codebook_id = codebook_id
        self.has_own_codes = has_own_codes
        self.candidates = candidates or []
        self.existing_nets = existing_nets or []
        self.inserted_codes: list[dict] = []
        self.group_updates: list[dict] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        if "select codebook_id from subprojects" in sql:
            return FakeResult(scalar=self.codebook_id)
        if "exists(select 1 from codes where codebook_id" in sql:
            return FakeResult(scalar=self.has_own_codes)
        if "select name from nets" in sql:
            return FakeResult(scalars_list=self.existing_nets)
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


# --------------------------------------------------------------------------- #
# Categorías de Razón nuevas en rondas HEREDADAS (discover_new_reasons)
# --------------------------------------------------------------------------- #
class _NRResult:
    def __init__(self, rows=None, scalar=None, mapping=None):
        self._rows, self._scalar, self._mapping = rows or [], scalar, mapping

    def mappings(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._mapping

    def scalar(self):
        return self._scalar


class _NewReasonSession:
    """Fake que sirve subproyecto/origen, candidatos pendientes, códigos
    existentes (para el check de dedup) y captura los inserts."""

    def __init__(self, origin, candidates, existing_codes=None, existing_nets=None):
        self.origin = origin
        self.candidates = candidates
        self.existing_codes = existing_codes or []
        self.existing_nets = existing_nets or []
        self.inserted_codes = []
        self.inserted_net_codes = []
        self.suggested = []
        self.inserted_verbatim_codes = []
        self.coded_verbatims = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "sp.coding_type" in sql and "cb.origin" in sql:
            return _NRResult(mapping={
                "codebook_id": "cb-1", "coding_type": "reasons",
                "codebook_origin": self.origin,
            })
        if "from mention_groups" in sql and "pending_review" in sql:
            return _NRResult(rows=self.candidates)
        if "select id, label from codes" in sql:
            return _NRResult(rows=self.existing_codes)
        if "select name from nets" in sql:
            return _NRResult(rows=self.existing_nets)
        if "coalesce(max(code_number), 0) + 1" in sql:
            return _NRResult(scalar=1)
        if "study, p.external_code" in sql:
            return _NRResult(mapping={})
        if "select id from nets" in sql:
            return _NRResult(scalar=None)
        if sql.strip().startswith("insert into codes"):
            self.inserted_codes.append(params)
        elif sql.strip().startswith("insert into net_codes"):
            self.inserted_net_codes.append(params)
        elif sql.strip().startswith("update mention_groups"):
            self.suggested.append(params)
        elif sql.strip().startswith("insert into verbatim_codes"):
            self.inserted_verbatim_codes.append(params)
        elif sql.strip().startswith("update verbatims"):
            self.coded_verbatims.append(params)
        return _NRResult()


_PROPOSAL = {
    "net": "Experiencia sensorial",
    "label": "Buen sabor",
    "definition": "Valora positivamente el sabor.",
    "inclusion_criteria": ["Expresa agrado por el sabor"],
    "exclusion_criteria": ["Solo menciona precio"],
    "examples": ["Es rico"],
}


def test_discover_new_reasons_is_noop_for_scratch_round():
    # En scratch ya descubre su catálogo discover_reason_catalog: no duplica.
    db = _NewReasonSession(
        origin="scratch",
        candidates=[{"id": uuid.uuid4(), "normalized_text": "es rico", "sample_text": "Es rico", "frequency_count": 9}],
    )

    assert discover_new_reasons(db, uuid.uuid4(), min_mentions=3) == 0
    assert db.inserted_codes == []


def test_discover_new_reasons_creates_code_when_cluster_reaches_minimum(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "auto_approve_scratch_codebook", True)
    candidates = [
        {"id": uuid.uuid4(), "normalized_text": "es rico", "sample_text": "Es rico", "frequency_count": 5},
    ]
    db = _NewReasonSession(origin="inherited", candidates=candidates)

    with (
        patch("app.pipeline.semantic.cluster.embed_many", return_value=[[1.0, 0.0]]),
        patch("app.pipeline.semantic.cluster.propose_reason_codes", return_value=[_PROPOSAL]),
    ):
        grouped = discover_new_reasons(db, uuid.uuid4(), min_mentions=3)

    assert grouped == 1
    assert len(db.inserted_codes) == 1
    assert db.inserted_codes[0]["label"] == "Buen sabor"
    assert db.inserted_codes[0]["approval"] == "approved"
    assert db.suggested[0]["status"] == "auto_coded"
    assert len(db.inserted_verbatim_codes) == 1


def test_discover_new_reasons_reuses_existing_code_with_same_label(monkeypatch):
    # Paralelo del bug de Marcas: "Buen sabor" ya tiene código en el libro
    # (heredado, quizás todavía pending) — no se debe minar uno duplicado.
    from app.core.config import settings
    monkeypatch.setattr(settings, "auto_approve_scratch_codebook", True)
    candidates = [
        {"id": uuid.uuid4(), "normalized_text": "es rico", "sample_text": "Es rico", "frequency_count": 5},
    ]
    db = _NewReasonSession(
        origin="inherited",
        candidates=candidates,
        existing_codes=[{"id": "code-sabor-existing", "label": "Buen sabor"}],
    )

    with (
        patch("app.pipeline.semantic.cluster.embed_many", return_value=[[1.0, 0.0]]),
        patch("app.pipeline.semantic.cluster.propose_reason_codes", return_value=[_PROPOSAL]),
    ):
        grouped = discover_new_reasons(db, uuid.uuid4(), min_mentions=3)

    assert grouped == 1
    assert db.inserted_codes == []
    assert db.suggested[0]["code"] == "code-sabor-existing"
    assert db.inserted_verbatim_codes[0]["code"] == "code-sabor-existing"


def test_discover_new_reasons_below_minimum_leaves_pending(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "auto_approve_scratch_codebook", True)
    candidates = [
        {"id": uuid.uuid4(), "normalized_text": "es rico", "sample_text": "Es rico", "frequency_count": 1},
    ]
    db = _NewReasonSession(origin="inherited", candidates=candidates)

    with patch("app.pipeline.semantic.cluster.embed_many", return_value=[[1.0, 0.0]]):
        grouped = discover_new_reasons(db, uuid.uuid4(), min_mentions=3)

    assert grouped == 0
    assert db.inserted_codes == []


# --------------------------------------------------------------------------- #
# Batching de la propuesta de categorías (_propose_reason_codes_parallel)
# --------------------------------------------------------------------------- #
def test_propose_reason_codes_parallel_single_batch_calls_propose_once(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "reason_discovery_batch_size", 20)
    calls = []

    def fake_propose(batch, context, existing_nets=None):
        calls.append(list(batch))
        return [{"index": i, "label": s} for i, s in enumerate(batch)]

    with patch("app.pipeline.semantic.cluster.propose_reason_codes", side_effect=fake_propose):
        result = _propose_reason_codes_parallel([f"cluster {i}" for i in range(5)], {})

    assert len(calls) == 1  # cabe en un solo lote, no dispara el pool
    assert [r["label"] for r in result] == [f"cluster {i}" for i in range(5)]


def test_propose_reason_codes_parallel_splits_and_preserves_order(monkeypatch):
    # 45 clusters con batch_size=20 -> 3 lotes en paralelo; el resultado debe
    # volver en el MISMO orden que la entrada pese a correr concurrente (el
    # caller hace zip(proposals, big_clusters) y depende de ese orden).
    from app.core.config import settings
    monkeypatch.setattr(settings, "reason_discovery_batch_size", 20)
    monkeypatch.setattr(settings, "llm_parallel_requests", 3)
    summaries = [f"cluster {i}" for i in range(45)]
    calls = []

    def fake_propose(batch, context, existing_nets=None):
        calls.append(list(batch))
        return [{"index": i, "label": s} for i, s in enumerate(batch)]

    with patch("app.pipeline.semantic.cluster.propose_reason_codes", side_effect=fake_propose):
        result = _propose_reason_codes_parallel(summaries, {})

    assert len(calls) == 3  # 20 + 20 + 5
    assert [r["label"] for r in result] == summaries


def test_propose_reason_codes_parallel_sends_same_existing_nets_to_every_batch(monkeypatch):
    # Cada lote corre aislado (no ve los clusters de los otros); sin pasarles
    # el MISMO vocabulario de nets ya existentes, cada uno puede inventar un
    # nombre distinto para la misma idea ("Aroma" en el lote 1, "Sabor y
    # Aroma" en el lote 2) — la fragmentación que motivó este fix.
    from app.core.config import settings
    monkeypatch.setattr(settings, "reason_discovery_batch_size", 2)
    seen_nets = []

    def fake_propose(batch, context, existing_nets=None):
        seen_nets.append(existing_nets)
        return [{"index": i, "label": s} for i, s in enumerate(batch)]

    with patch("app.pipeline.semantic.cluster.propose_reason_codes", side_effect=fake_propose):
        _propose_reason_codes_parallel(
            ["a", "b", "c", "d"], {}, existing_nets=["Sabor", "Precio"],
        )

    assert len(seen_nets) == 2  # 4 items / batch_size=2 -> 2 lotes
    assert all(nets == ["Sabor", "Precio"] for nets in seen_nets)


def test_discover_new_reasons_passes_existing_nets_to_llm(monkeypatch):
    # discover_new_reasons corre en rondas HEREDADAS: el codebook importado ya
    # trae nets (p.ej. de una ronda homologada anterior) — deben llegar al
    # prompt para que el motor los reutilice en vez de inventar sinónimos.
    from app.core.config import settings
    monkeypatch.setattr(settings, "auto_approve_scratch_codebook", True)
    candidates = [
        {"id": uuid.uuid4(), "normalized_text": "es rico", "sample_text": "Es rico", "frequency_count": 5},
    ]
    db = _NewReasonSession(
        origin="inherited", candidates=candidates, existing_nets=["Sabor y Aroma", "Precio"],
    )
    seen_nets = []

    def fake_propose(cluster_summaries, context, existing_nets=None):
        seen_nets.append(existing_nets)
        return [_PROPOSAL]

    with (
        patch("app.pipeline.semantic.cluster.embed_many", return_value=[[1.0, 0.0]]),
        patch("app.pipeline.semantic.cluster.propose_reason_codes", side_effect=fake_propose),
    ):
        discover_new_reasons(db, uuid.uuid4(), min_mentions=3)

    assert seen_nets == [["Sabor y Aroma", "Precio"]]

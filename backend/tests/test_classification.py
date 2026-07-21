"""Pure unit test for the classification engine's decision logic.

ponytail: fakes the DB session instead of hitting Postgres — the new schema
uses gen_random_uuid()/now()/on-conflict, which SQLite (used by the other
tests) can't run. This only verifies the matched/unmatched branching and the
SQL params sent, not real persistence.
"""
import uuid
from unittest.mock import patch

from app.core.config import settings
from app.pipeline import classify_round


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar

    def first(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self, codes, groups, coding_type=None):
        self._codes = codes
        self._groups = groups
        self._coding_type = coding_type
        self.executed = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, params))
        if "coding_type from subprojects" in sql:
            return FakeResult(scalar=self._coding_type)
        if "from codes c" in sql:
            return FakeResult(rows=self._codes)
        if "from mention_groups mg" in sql:
            return FakeResult(rows=self._groups)
        if "select p.name as study" in sql:
            return FakeResult(rows=[])
        if "single_code_per_response from subprojects" in sql:
            return FakeResult(scalar=False)
        return FakeResult()

    def commit(self):
        pass


def test_classify_round_suggests_matches_and_abstains_without_autoclose():
    group_matched = {"id": uuid.uuid4(), "sample_text": "muy caro"}
    group_unmatched = {"id": uuid.uuid4(), "sample_text": "asdf"}
    group_low_confidence = {"id": uuid.uuid4(), "sample_text": "algo raro"}
    group_anomaly = {"id": uuid.uuid4(), "sample_text": "kjsdañfdsk"}
    group_no_se = {"id": uuid.uuid4(), "sample_text": "no se"}
    codes = [
        {"id": uuid.uuid4(), "code_number": 1, "label": "Precio", "net_name": None, "system_type": None, "aliases": []},
        {"id": uuid.uuid4(), "code_number": 97, "label": "Otras menciones", "net_name": None, "system_type": "other_mentions", "aliases": []},
        {"id": uuid.uuid4(), "code_number": 95, "label": "Menciones confusas/Incorrectas", "net_name": None, "system_type": "anomaly", "aliases": []},
        {"id": uuid.uuid4(), "code_number": 96, "label": "No sabe", "net_name": None, "system_type": "no_answer", "aliases": []},
    ]
    db = FakeSession(
        codes=codes,
        groups=[group_matched, group_unmatched, group_low_confidence, group_anomaly, group_no_se],
    )

    fake_results = [
        {"verbatim_id": str(group_matched["id"]), "code_numbers": [1], "confidence": 0.95},
        {"verbatim_id": str(group_unmatched["id"]), "code_numbers": [], "confidence": 0.1},
        # Matched a code, but below llm_confidence_threshold — should still go to human review.
        {"verbatim_id": str(group_low_confidence["id"]), "code_numbers": [1], "confidence": 0.3},
        # Alta confianza en código universal 95: auto-cierra (teclazo / confusa).
        {"verbatim_id": str(group_anomaly["id"]), "code_numbers": [95], "confidence": 0.9},
        # Alta confianza en 96: auto-cierra "no se".
        {"verbatim_id": str(group_no_se["id"]), "code_numbers": [96], "confidence": 0.95},
    ]

    with patch("app.pipeline.llm.classify.classify_batch", return_value=fake_results), \
         patch.object(settings, "auto_commit_llm", True):
        summary = classify_round(db, uuid.uuid4())

    # Contenido + 95 + 96 auto-cierran; baja confianza queda sugerida; vacío se abstiene.
    assert summary["groups_classified"] == 3
    assert summary["suggestions"] == 1
    assert summary["anomalies"] == 1
    assert summary["total"] == 5

    def has_param(key, value, stmt_filter=""):
        for sql, p in db.executed:
            if stmt_filter and stmt_filter not in sql:
                continue
            if isinstance(p, list):
                if any(isinstance(item, dict) and item.get(key) == value for item in p):
                    return True
            elif isinstance(p, dict):
                if p.get(key) == value:
                    return True
        return False

    assert has_param("id", group_unmatched["id"], "abstained")
    assert has_param("id", group_anomaly["id"])  # auto_coded via update_groups
    assert has_param("code", codes[0]["id"])
    assert has_param("code", codes[2]["id"])  # anomaly 95
    assert has_param("code", codes[3]["id"])  # no_answer 96
    assert has_param("state", "auto_coded")
    assert has_param("state", "suggested")
    assert has_param("active", True)
    assert has_param("active", False)

    insert_sql = next(sql for sql, p in db.executed if "insert into verbatim_codes" in sql)
    assert "'llm_suggestion'" in insert_sql
    assert "'engine_fuzzy'" not in insert_sql


def test_classify_round_confidence_threshold_gates_autoclose():
    """La confianza declarada es el gate de auto-cierre cuando auto_commit_llm está
    activo: por debajo del umbral del tipo -> sugerencia; por encima -> auto_coded.
    El mismo código con la misma confianza cambia de destino según el umbral de su
    coding_type."""
    group = {"id": uuid.uuid4(), "sample_text": "algo"}
    codes = [
        {"id": uuid.uuid4(), "code_number": 1, "label": "Precio", "net_name": None, "system_type": None, "aliases": []},
    ]
    fake_results = [{"verbatim_id": str(group["id"]), "code_numbers": [1], "confidence": 0.7}]

    with patch("app.pipeline.llm.classify.classify_batch", return_value=fake_results), \
         patch.object(settings, "auto_commit_llm", True), \
         patch.object(settings, "llm_confidence_threshold_brands", 0.9), \
         patch.object(settings, "llm_confidence_threshold_reasons", 0.5):
        # Marcas: umbral 0.9 > conf 0.7 -> por debajo -> sugerencia.
        db_brands = FakeSession(codes=codes, groups=[group], coding_type="brands")
        summary_brands = classify_round(db_brands, uuid.uuid4())

        # Razones: umbral 0.5 <= conf 0.7 -> por encima -> auto-cierra.
        db_reasons = FakeSession(codes=codes, groups=[group], coding_type="reasons")
        summary_reasons = classify_round(db_reasons, uuid.uuid4())

    assert summary_brands["anomalies"] == 0
    assert summary_brands["groups_classified"] == 0
    assert summary_brands["suggestions"] == 1
    assert summary_reasons["groups_classified"] == 1
    assert summary_reasons["suggestions"] == 0
    assert summary_reasons["anomalies"] == 0


def test_classify_round_suggest_only_when_autocommit_disabled():
    """Con auto_commit_llm apagado, ni una confianza alta auto-cierra: todo queda
    en sugerencia para Resolución (modo conservador / shadow)."""
    group = {"id": uuid.uuid4(), "sample_text": "algo"}
    codes = [
        {"id": uuid.uuid4(), "code_number": 1, "label": "Precio", "net_name": None, "system_type": None, "aliases": []},
    ]
    # 0.7 supera el umbral de confianza (0.6) pero no el de promoción (0.9): auto
    # cerraría si el flag estuviera activo, y no toca el caché semántico.
    fake_results = [{"verbatim_id": str(group["id"]), "code_numbers": [1], "confidence": 0.7}]

    with patch("app.pipeline.llm.classify.classify_batch", return_value=fake_results), \
         patch.object(settings, "auto_commit_llm", False):
        db = FakeSession(codes=codes, groups=[group], coding_type="reasons")
        summary = classify_round(db, uuid.uuid4())

    assert summary["groups_classified"] == 0
    assert summary["suggestions"] == 1


def test_classify_round_marks_failed_batch_as_engine_error():
    group = {"id": uuid.uuid4(), "sample_text": "texto pendiente", "frequency_count": 3}
    db = FakeSession(codes=[], groups=[group], coding_type="reasons")

    with patch(
        "app.pipeline.llm.classify._classify_batch_with_retry",
        side_effect=RuntimeError("DeepSeek no disponible"),
    ):
        summary = classify_round(db, uuid.uuid4())

    assert summary["engine_errors"] == 1
    assert summary["anomalies"] == 0
    assert any(
        "status = 'engine_error'" in sql
        and isinstance(params, list)
        and params[0]["id"] == group["id"]
        for sql, params in db.executed
    )


def test_classify_round_promotes_brand_over_threshold_not_reasons():
    """Solo coding_type=='brands' con confidence >= umbral de promoción llama a
    promote_llm_result_to_alias; razones nunca lo tocan (van al caché semántico)."""
    group = {"id": uuid.uuid4(), "sample_text": "Gloria"}
    code_id = uuid.uuid4()
    codes = [
        {"id": code_id, "code_number": 1, "label": "Gloria", "net_name": None, "system_type": None, "aliases": []},
    ]
    fake_results = [{"verbatim_id": str(group["id"]), "code_numbers": [1], "confidence": 0.95}]

    with patch("app.pipeline.llm.classify.classify_batch", return_value=fake_results), \
         patch("app.pipeline.llm.classify.promote_llm_result_to_alias") as promote_mock:
        classify_round(FakeSession(codes=codes, groups=[group], coding_type="brands"), uuid.uuid4())

    promote_mock.assert_called_once()
    _, kwargs = promote_mock.call_args
    assert kwargs["code_id"] == code_id
    assert kwargs["alias_normalized"] == "gloria"
    assert kwargs["match_score"] == 0.95

    with patch("app.pipeline.llm.classify.classify_batch", return_value=fake_results), \
         patch("app.pipeline.llm.classify.promote_llm_result_to_alias") as promote_mock_reasons, \
         patch("app.pipeline.llm.classify.write_reason_cache"):
        classify_round(FakeSession(codes=codes, groups=[group], coding_type="reasons"), uuid.uuid4())

    promote_mock_reasons.assert_not_called()


def test_classify_round_writes_reason_cache_over_threshold_not_brands():
    """Solo coding_type=='reasons' con confidence >= umbral de promoción llama a
    write_reason_cache; marcas nunca lo tocan (van al catálogo fuzzy)."""
    group = {"id": uuid.uuid4(), "sample_text": "muy fresco"}
    code_id = uuid.uuid4()
    codes = [
        {"id": code_id, "code_number": 1, "label": "Frescura", "net_name": None, "system_type": None, "aliases": []},
    ]
    fake_results = [{"verbatim_id": str(group["id"]), "code_numbers": [1], "confidence": 0.95}]

    with patch("app.pipeline.llm.classify.classify_batch", return_value=fake_results), \
         patch("app.pipeline.llm.classify.write_reason_cache") as write_mock:
        classify_round(FakeSession(codes=codes, groups=[group], coding_type="reasons"), uuid.uuid4())

    write_mock.assert_called_once()
    _, kwargs = write_mock.call_args
    assert kwargs["code_id"] == code_id
    assert kwargs["source_text"] == "muy fresco"
    assert kwargs["confidence"] == 0.95

    with patch("app.pipeline.llm.classify.classify_batch", return_value=fake_results), \
         patch("app.pipeline.llm.classify.promote_llm_result_to_alias"), \
         patch("app.pipeline.llm.classify.write_reason_cache") as write_mock_brands:
        classify_round(FakeSession(codes=codes, groups=[group], coding_type="brands"), uuid.uuid4())

    write_mock_brands.assert_not_called()

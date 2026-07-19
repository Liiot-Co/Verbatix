"""Unit tests for process_round's orchestration across a round's 2 subprojects
(Marcas/Razones, v8) and each subproject's own brands-fuzzy/reasons-LLM dispatch.

ponytail: mocks the engines themselves (each already covered by
test_fuzzy.py/test_classification.py) — this only proves the orchestration wiring,
not the engines' internals.
"""
import uuid
from unittest.mock import patch

from app.pipeline.process import (
    _apply_semantic_cache,
    _prefilter_garbage,
    _process_subproject,
    process_round,
)

ROUND_ID = uuid.uuid4()
SUBPROJECT_BRANDS = uuid.uuid4()
SUBPROJECT_REASONS = uuid.uuid4()


class FakeResult:
    def __init__(self, scalar=None, rowcount=0, mapping_rows=None):
        self._scalar = scalar
        self.rowcount = rowcount
        self._mapping_rows = mapping_rows or []

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def all(self):
        return self._mapping_rows

    def first(self):
        return self._mapping_rows[0] if self._mapping_rows else None


class FakeSession:
    def __init__(self, execute=None):
        self._execute_override = execute

    def execute(self, stmt, params=None):
        if self._execute_override:
            return self._execute_override(stmt, params)
        return FakeResult()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_process_round_dispatches_both_subprojects_in_parallel_and_sums_stats():
    subproject_results = {
        SUBPROJECT_BRANDS: {"run_id": "brands-run", "llm_run_id": "brands-llm", "groups_classified": 3, "anomalies": 1, "total": 5},
        SUBPROJECT_REASONS: {"run_id": "reasons-run", "llm_run_id": "reasons-llm", "groups_classified": 2, "anomalies": 0, "total": 2},
    }

    def fake_execute(stmt, params=None):
        sql = str(stmt)
        if "id, coding_type from subprojects where round_id" in sql:
            return FakeResult(mapping_rows=[
                {"id": SUBPROJECT_BRANDS, "coding_type": "brands"},
                {"id": SUBPROJECT_REASONS, "coding_type": "reasons"},
            ])
        return FakeResult()

    db = FakeSession(execute=fake_execute)

    with (
        patch("app.pipeline.process.SessionLocal", side_effect=lambda: FakeSession(execute=fake_execute)),
        patch(
            "app.pipeline.process._process_subproject",
            side_effect=lambda db, sp_id, coding_type, threshold: subproject_results[sp_id],
        ) as process_mock,
    ):
        result = process_round(db, ROUND_ID)

    assert process_mock.call_count == 2
    assert result["groups_classified"] == 5  # 3 + 2
    assert result["anomalies"] == 1
    assert result["total"] == 7


def test_process_round_raises_when_one_subproject_fails():
    """Section 2.5: a failing subproject must still fail the whole round (same
    contract as the old sequential version) — the exception propagates instead
    of being silently swallowed by the worker thread."""
    def fake_execute(stmt, params=None):
        sql = str(stmt)
        if "id, coding_type from subprojects where round_id" in sql:
            return FakeResult(mapping_rows=[
                {"id": SUBPROJECT_BRANDS, "coding_type": "brands"},
                {"id": SUBPROJECT_REASONS, "coding_type": "reasons"},
            ])
        return FakeResult()

    db = FakeSession(execute=fake_execute)

    def fake_process_subproject(db, sp_id, coding_type, threshold):
        if sp_id == SUBPROJECT_REASONS:
            raise RuntimeError("llm boom")
        return {"run_id": "r1", "llm_run_id": "l1", "groups_classified": 1, "anomalies": 0, "total": 1}

    with (
        patch("app.pipeline.process.SessionLocal", side_effect=lambda: FakeSession(execute=fake_execute)),
        patch("app.pipeline.process._process_subproject", side_effect=fake_process_subproject),
    ):
        try:
            process_round(db, ROUND_ID)
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert str(exc) == "llm boom"


def test_process_round_raises_when_round_has_no_subprojects():
    db = FakeSession(execute=lambda stmt, params=None: FakeResult(mapping_rows=[]))

    try:
        process_round(db, ROUND_ID)
        assert False, "expected LookupError"
    except LookupError:
        pass


def test_process_subproject_runs_fuzzy_for_brands():
    with (
        patch("app.pipeline.process._prefilter_garbage") as prefilter_mock,
        patch("app.pipeline.process._process_brands", return_value={"run_id": "r1", "groups_classified": 1, "anomalies": 0, "total": 1}) as fuzzy_mock,
        patch("app.pipeline.process._apply_semantic_cache", return_value={"groups_classified": 0}),
        patch("app.pipeline.process.classify_round", return_value={"run_id": "llm1", "groups_classified": 0, "anomalies": 0, "total": 0}),
    ):
        _process_subproject(FakeSession(), SUBPROJECT_BRANDS, "brands", 90.0)

    prefilter_mock.assert_called_once()
    fuzzy_mock.assert_called_once()


def test_process_subproject_skips_fuzzy_for_reasons():
    """Marcas -> fuzzy puro; Razones nunca toca el motor fuzzy (va directo a
    caché semántico + LLM) — bug preexistente corregido en la migración v8: el
    código llamaba a _process_brands sin condicionar por coding_type."""
    with (
        patch("app.pipeline.process._prefilter_garbage"),
        patch("app.pipeline.process._process_brands") as fuzzy_mock,
        patch("app.pipeline.process.discover_reason_catalog") as discover_mock,
        patch("app.pipeline.process._apply_semantic_cache", return_value={"groups_classified": 0}),
        patch("app.pipeline.process.classify_round", return_value={"run_id": "llm1", "groups_classified": 2, "anomalies": 0, "total": 2}),
    ):
        result = _process_subproject(FakeSession(), SUBPROJECT_REASONS, "reasons", 90.0)

    fuzzy_mock.assert_not_called()
    discover_mock.assert_called_once()
    assert result["groups_classified"] == 2


NO_SABE_VARIANTS = ["no sabe", "no se", "nose", "no sabria decir", "no conozco"]


def test_prefilter_auto_codes_system_alias_and_flags_real_garbage():
    """One garbage group (short text) -> anomaly. One 'no se' group -> auto_coded
    straight to its system code, skipping manual review entirely."""
    updates = []  # every UPDATE/INSERT, for assertions below

    def fake_execute(stmt, params=None):
        sql = str(stmt)
        if "codebook_id from subprojects where id" in sql:
            return FakeResult(scalar="cb-1")
        if "select id, system_type from codes" in sql:
            return FakeResult(mapping_rows=[{"id": "code-96", "system_type": "no_answer"}])
        if "select id from mention_groups" in sql:
            rows = [{"id": "group-2"}] if params.get("variants") == NO_SABE_VARIANTS else []
            return FakeResult(mapping_rows=rows)
        if sql.strip().startswith("update mention_groups") and "anomaly" in sql:
            return FakeResult(rowcount=1)  # the short-text garbage group
        updates.append((sql, params))
        return FakeResult(rowcount=1)

    total = _prefilter_garbage(FakeSession(execute=fake_execute), SUBPROJECT_BRANDS)

    assert total == 2  # 1 garbage + 1 "no se" resolved
    assert any("status = 'auto_coded'" in sql for sql, _ in updates)
    insert_sql, insert_params = next((s, p) for s, p in updates if s.strip().startswith("insert into verbatim_codes"))
    assert insert_params["code"] == "code-96"


def test_semantic_cache_skipped_for_brands():
    """coding_type != 'reasons' -> no DB access at all, no LLM cost paid on the check."""
    calls = []
    db = FakeSession(execute=lambda stmt, params=None: calls.append(stmt) or FakeResult())

    result = _apply_semantic_cache(db, SUBPROJECT_BRANDS, "brands")

    assert result == {"groups_classified": 0}
    assert calls == []


def test_semantic_cache_hit_auto_codes_group_before_llm_sees_it():
    """A group with a near-identical reason_embeddings hit gets marked
    'auto_coded' by the cache pass — so classify_round's own pending_review
    query (and therefore _classify_batch_with_retry/classify_batch) never
    sees it, without needing to spy on the LLM call itself."""
    group_id = "group-1"
    mention_groups = {group_id: {"normalized_text": "muy fresco", "status": "pending_review"}}
    inserted_verbatim_codes = []

    def fake_execute(stmt, params=None):
        sql = str(stmt)
        if "codebook_id, round_id from subprojects" in sql:
            return FakeResult(mapping_rows=[{"codebook_id": "cb-1", "round_id": "own-round"}])
        if "origin_mode, source_round_id from rounds" in sql:
            return FakeResult(mapping_rows=[{"origin_mode": "from_scratch", "source_round_id": None}])
        if "select id, normalized_text from mention_groups" in sql:
            rows = [
                {"id": gid, "normalized_text": g["normalized_text"]}
                for gid, g in mention_groups.items()
                if g["status"] == "pending_review"
            ]
            return FakeResult(mapping_rows=rows)
        if sql.strip().startswith("update mention_groups"):
            for p in params:
                mention_groups[p["id"]]["status"] = "auto_coded"
            return FakeResult()
        if sql.strip().startswith("insert into verbatim_codes"):
            inserted_verbatim_codes.extend(params)
            return FakeResult()
        return FakeResult()

    db = FakeSession(execute=fake_execute)

    with patch(
        "app.pipeline.process.semantic_cache.lookup",
        return_value={"code_id": "code-1", "codebook_id": "cb-1", "similarity": 0.95},
    ):
        result = _apply_semantic_cache(db, SUBPROJECT_REASONS, "reasons")

    assert result == {"groups_classified": 1}
    assert mention_groups[group_id]["status"] == "auto_coded"
    assert inserted_verbatim_codes[0]["code"] == "code-1"

    # classify_round filters on status='pending_review' via its own query — this
    # group is no longer in that set, so it never reaches the LLM.
    remaining_pending = [gid for gid, g in mention_groups.items() if g["status"] == "pending_review"]
    assert remaining_pending == []


def test_semantic_cache_miss_leaves_group_pending():
    group_id = "group-1"
    mention_groups = {group_id: {"normalized_text": "algo nuevo", "status": "pending_review"}}

    def fake_execute(stmt, params=None):
        sql = str(stmt)
        if "codebook_id, round_id from subprojects" in sql:
            return FakeResult(mapping_rows=[{"codebook_id": "cb-1", "round_id": "own-round"}])
        if "origin_mode, source_round_id from rounds" in sql:
            return FakeResult(mapping_rows=[{"origin_mode": "from_scratch", "source_round_id": None}])
        if "select id, normalized_text from mention_groups" in sql:
            rows = [{"id": gid, "normalized_text": g["normalized_text"]} for gid, g in mention_groups.items()]
            return FakeResult(mapping_rows=rows)
        return FakeResult()

    db = FakeSession(execute=fake_execute)

    with patch("app.pipeline.process.semantic_cache.lookup", return_value=None):
        result = _apply_semantic_cache(db, SUBPROJECT_REASONS, "reasons")

    assert result == {"groups_classified": 0}
    assert mention_groups[group_id]["status"] == "pending_review"


def test_semantic_cache_searches_source_round_when_homologated():
    """Task C4: a homologated round's subproject also searches the equivalent
    subproject (same coding_type) of its origin round's codebook, and remaps the
    hit's code_id to the equivalent inherited code in its own codebook (code ids
    aren't shared across cloned codebooks — see repositories.clone_codebook)."""
    group_id = "group-1"
    mention_groups = {group_id: {"normalized_text": "muy fresco", "status": "pending_review"}}
    inserted_verbatim_codes = []
    lookup_calls = []

    def fake_execute(stmt, params=None):
        sql = str(stmt)
        if "codebook_id, round_id from subprojects" in sql:
            return FakeResult(mapping_rows=[{"codebook_id": "cb-own", "round_id": "own-round"}])
        if "origin_mode, source_round_id from rounds" in sql:
            return FakeResult(mapping_rows=[{"origin_mode": "homologated", "source_round_id": "source-round"}])
        if "codebook_id from subprojects where round_id" in sql:
            return FakeResult(scalar="cb-source" if params["round"] == "source-round" else "cb-own")
        if "select id, normalized_text from mention_groups" in sql:
            rows = [
                {"id": gid, "normalized_text": g["normalized_text"]}
                for gid, g in mention_groups.items()
                if g["status"] == "pending_review"
            ]
            return FakeResult(mapping_rows=rows)
        if "inherited_from_code_id" in sql:
            # The origin round's code "code-source" was cloned into this
            # subproject's codebook as "code-own".
            return FakeResult(scalar="code-own" if params["src"] == "code-source" else None)
        if sql.strip().startswith("update mention_groups"):
            for p in params:
                mention_groups[p["id"]]["status"] = "auto_coded"
            return FakeResult()
        if sql.strip().startswith("insert into verbatim_codes"):
            inserted_verbatim_codes.extend(params)
            return FakeResult()
        return FakeResult()

    def fake_lookup(db, codebook_ids, normalized_text):
        lookup_calls.append(codebook_ids)
        return {"code_id": "code-source", "codebook_id": "cb-source", "similarity": 0.95}

    db = FakeSession(execute=fake_execute)

    with patch("app.pipeline.process.semantic_cache.lookup", side_effect=fake_lookup):
        result = _apply_semantic_cache(db, SUBPROJECT_REASONS, "reasons")

    assert lookup_calls == [["cb-own", "cb-source"]]
    assert result == {"groups_classified": 1}
    assert inserted_verbatim_codes[0]["code"] == "code-own"  # remapped, not the origin round's code_id


def test_semantic_cache_skips_hit_when_no_inherited_code_found():
    """Cross-codebook hit with no equivalent inherited code -> falls through to
    the LLM instead of writing a code_id from a different codebook."""
    group_id = "group-1"
    mention_groups = {group_id: {"normalized_text": "muy fresco", "status": "pending_review"}}

    def fake_execute(stmt, params=None):
        sql = str(stmt)
        if "codebook_id, round_id from subprojects" in sql:
            return FakeResult(mapping_rows=[{"codebook_id": "cb-own", "round_id": "own-round"}])
        if "origin_mode, source_round_id from rounds" in sql:
            return FakeResult(mapping_rows=[{"origin_mode": "homologated", "source_round_id": "source-round"}])
        if "codebook_id from subprojects where round_id" in sql:
            return FakeResult(scalar="cb-source" if params["round"] == "source-round" else "cb-own")
        if "select id, normalized_text from mention_groups" in sql:
            rows = [{"id": gid, "normalized_text": g["normalized_text"]} for gid, g in mention_groups.items()]
            return FakeResult(mapping_rows=rows)
        if "inherited_from_code_id" in sql:
            return FakeResult(scalar=None)
        return FakeResult()

    db = FakeSession(execute=fake_execute)

    with patch(
        "app.pipeline.process.semantic_cache.lookup",
        return_value={"code_id": "code-source", "codebook_id": "cb-source", "similarity": 0.95},
    ):
        result = _apply_semantic_cache(db, SUBPROJECT_REASONS, "reasons")

    assert result == {"groups_classified": 0}
    assert mention_groups[group_id]["status"] == "pending_review"

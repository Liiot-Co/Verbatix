"""Unit test for process_round's brands -> fuzzy, then LLM on the leftovers -> orchestration.

ponytail: mocks _process_brands/classify_round themselves (each already covered by
test_fuzzy.py/test_classification.py) — this only proves process_round calls both for
'brands' rounds and merges their stats, not the engines' internals.
"""
import uuid
from unittest.mock import patch

from app.pipeline.process import _apply_semantic_cache, _prefilter_garbage, process_round


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
    def __init__(self, coding_type, execute=None):
        self._coding_type = coding_type
        self._execute_override = execute

    def execute(self, stmt, params=None):
        if self._execute_override:
            return self._execute_override(stmt, params)
        sql = str(stmt)
        if "coding_type" in sql:
            return FakeResult(scalar=self._coding_type)
        return FakeResult()

    def commit(self):
        pass


def test_brands_round_runs_llm_on_fuzzy_leftovers():
    fuzzy_result = {"run_id": "fuzzy-run", "groups_classified": 3, "anomalies": 2, "total": 5}
    llm_result = {"run_id": "llm-run", "groups_classified": 1, "anomalies": 1, "total": 2}

    db = FakeSession(coding_type="brands")
    with (
        patch("app.pipeline.process._process_brands", return_value=fuzzy_result) as fuzzy_mock,
        patch("app.pipeline.process.classify_round", return_value=llm_result) as llm_mock,
    ):
        result = process_round(db, uuid.uuid4())

    fuzzy_mock.assert_called_once()
    llm_mock.assert_called_once()
    assert result["groups_classified"] == 4  # 3 fuzzy + 1 llm
    assert result["anomalies"] == 1  # only what the LLM still couldn't resolve
    assert result["total"] == 5


NO_SABE_VARIANTS = ["no sabe", "no se", "nose", "no sabria decir", "no conozco"]


def test_prefilter_auto_codes_system_alias_and_flags_real_garbage():
    """One garbage group (short text) -> anomaly. One 'no se' group -> auto_coded
    straight to its system code, skipping manual review entirely."""
    updates = []  # every UPDATE/INSERT, for assertions below

    def fake_execute(stmt, params=None):
        sql = str(stmt)
        if "select id, system_type from codes" in sql:
            return FakeResult(mapping_rows=[{"id": "code-96", "system_type": "no_answer"}])
        if "select id from mention_groups" in sql:
            rows = [{"id": "group-2"}] if params.get("variants") == NO_SABE_VARIANTS else []
            return FakeResult(mapping_rows=rows)
        if sql.strip().startswith("update mention_groups") and "anomaly" in sql:
            return FakeResult(rowcount=1)  # the short-text garbage group
        updates.append((sql, params))
        return FakeResult(rowcount=1)

    with patch("app.repositories._current_codebook_id", return_value="cb-1"):
        total = _prefilter_garbage(FakeSession(coding_type=None, execute=fake_execute), uuid.uuid4())

    assert total == 2  # 1 garbage + 1 "no se" resolved
    assert any("status = 'auto_coded'" in sql for sql, _ in updates)
    insert_sql, insert_params = next((s, p) for s, p in updates if s.strip().startswith("insert into verbatim_codes"))
    assert insert_params["code"] == "code-96"


def test_reasons_round_skips_fuzzy():
    llm_result = {"run_id": "llm-run", "groups_classified": 2, "anomalies": 0, "total": 2}

    db = FakeSession(coding_type="reasons")
    with (
        patch("app.pipeline.process._process_brands") as fuzzy_mock,
        patch("app.pipeline.process.classify_round", return_value=llm_result) as llm_mock,
    ):
        result = process_round(db, uuid.uuid4())

    fuzzy_mock.assert_not_called()
    llm_mock.assert_called_once()
    assert result == llm_result


def test_semantic_cache_skipped_for_brands():
    """coding_type != 'reasons' -> no DB access at all, no LLM cost paid on the check."""
    calls = []
    db = FakeSession(coding_type="brands", execute=lambda stmt, params=None: calls.append(stmt) or FakeResult())

    result = _apply_semantic_cache(db, uuid.uuid4(), "brands")

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
        if "from codebooks" in sql:
            return FakeResult(scalar="cb-1")
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

    db = FakeSession(coding_type="reasons", execute=fake_execute)

    with patch(
        "app.pipeline.process.semantic_cache.lookup",
        return_value={"code_id": "code-1", "codebook_id": "cb-1", "similarity": 0.95},
    ), patch("app.repositories._current_codebook_id", return_value="cb-1"):
        result = _apply_semantic_cache(db, uuid.uuid4(), "reasons")

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
        if "from codebooks" in sql:
            return FakeResult(scalar="cb-1")
        if "select id, normalized_text from mention_groups" in sql:
            rows = [{"id": gid, "normalized_text": g["normalized_text"]} for gid, g in mention_groups.items()]
            return FakeResult(mapping_rows=rows)
        return FakeResult()

    db = FakeSession(coding_type="reasons", execute=fake_execute)

    with patch("app.pipeline.process.semantic_cache.lookup", return_value=None), \
         patch("app.repositories._current_codebook_id", return_value="cb-1"):
        result = _apply_semantic_cache(db, uuid.uuid4(), "reasons")

    assert result == {"groups_classified": 0}
    assert mention_groups[group_id]["status"] == "pending_review"


def test_semantic_cache_searches_source_round_when_homologated():
    """Task C4: a homologated round with source_round_id also searches the
    origin round's codebook, and remaps the hit's code_id to the equivalent
    inherited code in its own codebook (code ids aren't shared across cloned
    codebooks — see repositories.clone_codebook)."""
    group_id = "group-1"
    mention_groups = {group_id: {"normalized_text": "muy fresco", "status": "pending_review"}}
    inserted_verbatim_codes = []
    lookup_calls = []

    def fake_current_codebook_id(db, round_id):
        return "cb-source" if round_id == "source-round" else "cb-own"

    def fake_execute(stmt, params=None):
        sql = str(stmt)
        if "origin_mode, source_round_id from rounds" in sql:
            return FakeResult(mapping_rows=[{"origin_mode": "homologated", "source_round_id": "source-round"}])
        if "select id, normalized_text from mention_groups" in sql:
            rows = [
                {"id": gid, "normalized_text": g["normalized_text"]}
                for gid, g in mention_groups.items()
                if g["status"] == "pending_review"
            ]
            return FakeResult(mapping_rows=rows)
        if "inherited_from_code_id" in sql:
            # The origin round's code "code-source" was cloned into this
            # round's codebook as "code-own".
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

    db = FakeSession(coding_type="reasons", execute=fake_execute)

    with patch("app.pipeline.process.semantic_cache.lookup", side_effect=fake_lookup), \
         patch("app.repositories._current_codebook_id", side_effect=fake_current_codebook_id):
        result = _apply_semantic_cache(db, "own-round", "reasons")

    assert lookup_calls == [["cb-own", "cb-source"]]
    assert result == {"groups_classified": 1}
    assert inserted_verbatim_codes[0]["code"] == "code-own"  # remapped, not the origin round's code_id


def test_semantic_cache_skips_hit_when_no_inherited_code_found():
    """Cross-codebook hit with no equivalent inherited code -> falls through to
    the LLM instead of writing a code_id from a different codebook."""
    group_id = "group-1"
    mention_groups = {group_id: {"normalized_text": "muy fresco", "status": "pending_review"}}

    def fake_current_codebook_id(db, round_id):
        return "cb-source" if round_id == "source-round" else "cb-own"

    def fake_execute(stmt, params=None):
        sql = str(stmt)
        if "origin_mode, source_round_id from rounds" in sql:
            return FakeResult(mapping_rows=[{"origin_mode": "homologated", "source_round_id": "source-round"}])
        if "select id, normalized_text from mention_groups" in sql:
            rows = [{"id": gid, "normalized_text": g["normalized_text"]} for gid, g in mention_groups.items()]
            return FakeResult(mapping_rows=rows)
        if "inherited_from_code_id" in sql:
            return FakeResult(scalar=None)
        return FakeResult()

    db = FakeSession(coding_type="reasons", execute=fake_execute)

    with patch(
        "app.pipeline.process.semantic_cache.lookup",
        return_value={"code_id": "code-source", "codebook_id": "cb-source", "similarity": 0.95},
    ), patch("app.repositories._current_codebook_id", side_effect=fake_current_codebook_id):
        result = _apply_semantic_cache(db, "own-round", "reasons")

    assert result == {"groups_classified": 0}
    assert mention_groups[group_id]["status"] == "pending_review"

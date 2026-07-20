import json
import uuid

from app.repositories import persist_dataset_snapshot, round_processing_blockers


FILE_ID = uuid.uuid4()
ROUND_ID = uuid.uuid4()


class FakeResult:
    def __init__(self, *, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class SnapshotSession:
    def __init__(self):
        self.snapshot = None

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).lower().split())
        params = params or {}
        if "select checksum, total_rows, file_type, dataset_snapshot" in sql:
            return FakeResult(rows=[{
                "checksum": "abc123",
                "total_rows": 10,
                "file_type": "dau",
                "dataset_snapshot": self.snapshot,
            }])
        if "select sp.coding_type" in sql and "count(v.id) as verbatims" in sql:
            return FakeResult(rows=[{
                "coding_type": "brands", "verbatims": 8, "respondents": 5,
                "question_variables": 2, "mention_groups": 4,
            }])
        if "select profile_status" in sql:
            return FakeResult(rows=[{"profile_status": "not_checked", "n": 5}])
        if "select flag_type" in sql:
            return FakeResult(rows=[{"flag_type": "possible_duplicate", "n": 1}])
        if "set dataset_snapshot = cast" in sql:
            self.snapshot = json.loads(params["snapshot"])
            return FakeResult()
        return FakeResult()


class BlockerSession:
    def __init__(self, pending_flags, unready_snapshots, missing_client_catalogs=0):
        self.pending_flags = pending_flags
        self.unready_snapshots = unready_snapshots
        self.missing_client_catalogs = missing_client_catalogs

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).lower().split())
        if "from import_review_flags f" in sql:
            return FakeResult(scalar=self.pending_flags)
        if "from imported_files" in sql:
            return FakeResult(scalar=self.unready_snapshots)
        if "join codebooks cb" in sql:
            return FakeResult(scalar=self.missing_client_catalogs)
        return FakeResult()


def test_dataset_snapshot_records_counts_and_preserves_draft_evidence():
    db = SnapshotSession()
    draft = persist_dataset_snapshot(
        db,
        FILE_ID,
        status="blocked",
        parsed_rows=10,
        field_selections=[{"field": "Q1", "included": True}],
        pending_questions=["Q2"],
        skipped_by_type={"reasons": 2},
    )

    assert draft["status"] == "blocked"
    assert draft["source"]["parsed_verbatims"] == 10
    assert draft["persisted_by_coding_type"]["brands"]["verbatims"] == 8
    assert draft["pending_flag_counts"] == {"possible_duplicate": 1}

    ready = persist_dataset_snapshot(db, FILE_ID, status="ready")
    assert ready["status"] == "ready"
    assert ready["population_reconciliation"] == "not_configured"
    assert ready["source"]["parsed_verbatims"] == 10
    assert ready["field_selections"] == [{"field": "Q1", "included": True}]
    assert ready["skipped_by_type"] == {"reasons": 2}


def test_round_processing_blockers_are_derived_from_existing_tables():
    assert round_processing_blockers(BlockerSession(0, 0), ROUND_ID) == []
    assert round_processing_blockers(BlockerSession(2, 1), ROUND_ID) == [
        "2 flags de importación pendientes",
        "1 snapshots de población sin cerrar",
    ]


def test_round_processing_waits_for_imported_client_catalog():
    assert round_processing_blockers(BlockerSession(0, 0, 1), ROUND_ID) == [
        "1 catálogos de cliente sin confirmar",
    ]

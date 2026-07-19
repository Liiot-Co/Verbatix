"""REQ-03 — cargas múltiples sin tocar el ID real del encuestado.

Cubre los casos de la sección 5 a nivel de unidad, con una FakeSession que
simula el estado real (respondents / import_review_flags / verbatims) — misma
convención que test_question_classification.py: nunca se toca una BD real.
"""
import uuid

import pytest

from app.pipeline.imports import (
    analyze_new_load,
    cleanup_orphan_groups,
    find_checksum_duplicate,
    get_load_review,
    resolve_flag,
    round_has_previous_load,
    suggest_source_label,
)
from app.repositories import propagate_group_codes_to_pending

ROUND_ID = uuid.uuid4()
FILE_OLD = uuid.uuid4()
FILE_NEW = uuid.uuid4()
USER_ID = uuid.uuid4()


# ── source_label sugerido ──


def test_suggest_source_label_cleans_filename():
    assert suggest_source_label("32406358_HBG_LECHES_2026.dau") == "32406358 HBG LECHES 2026"
    assert suggest_source_label("Dimension-Parte-1.xlsx") == "Dimension Parte 1"
    assert suggest_source_label("") == "Carga"


# ── FakeSession con estado real ──


class FakeResult:
    def __init__(self, scalar=None, rows=None, rowcount=0):
        self._scalar = scalar
        self._rows = rows or []
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """Simula respondents / imported_files / import_review_flags / verbatims de
    UNA ronda con dos cargas, respondiendo las queries de pipeline/imports.py."""

    def __init__(self):
        self.files = {}        # id -> {round_id, checksum, status, file_type, source_label, original_filename}
        self.respondents = {}  # id -> {round_id, imported_file_id, serial, realid}
        self.flags = {}        # id -> {imported_file_id, respondent_id, flag_type, detail, status}
        self.verbatims = []    # {respondent_id, imported_file_id, question_key, text}
        self.audit_log = []
        self.committed = False

    # helpers de armado
    def add_file(self, file_id, checksum="x", status="validated", label=None, name="archivo.dau"):
        self.files[file_id] = {
            "id": file_id, "round_id": ROUND_ID, "checksum": checksum, "status": status,
            "file_type": "dau", "source_label": label, "original_filename": name,
        }

    def add_respondent(self, file_id, serial, realid):
        rid = uuid.uuid4()
        self.respondents[rid] = {
            "id": rid, "round_id": ROUND_ID, "imported_file_id": file_id,
            "serial": serial, "realid": realid,
        }
        return rid

    def add_verbatim(self, respondent_id, file_id, qk="Q1", text="gloria"):
        self.verbatims.append({
            "respondent_id": respondent_id, "imported_file_id": file_id,
            "question_key": qk, "text": text,
        })

    def _label(self, file_id):
        f = self.files.get(file_id)
        if not f:
            return None
        return f["source_label"] or f["original_filename"]

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}

        if "checksum = :sum" in sql:
            rows = [
                {"id": f["id"], "original_filename": f["original_filename"],
                 "source_label": f["source_label"], "status": f["status"]}
                for f in self.files.values()
                if f["round_id"] == params["round"] and f["checksum"] == params["sum"]
            ]
            return FakeResult(rows=rows)

        if "select 1 from imported_files" in sql:
            others = [
                f for f in self.files.values()
                if f["round_id"] == params["round"] and f["id"] != params["file"]
                and f["status"] == "validated"
            ]
            return FakeResult(scalar=1 if others else None)

        if "previo.realid = nuevo.realid" in sql:
            rows = []
            for nuevo in self.respondents.values():
                if nuevo["imported_file_id"] != params["file"] or not nuevo["realid"]:
                    continue
                for previo in self.respondents.values():
                    if previo["imported_file_id"] == nuevo["imported_file_id"]:
                        continue
                    if previo["realid"] == nuevo["realid"]:
                        rows.append({
                            "respondent_id": nuevo["id"], "serial": nuevo["serial"],
                            "realid": nuevo["realid"], "previous_serial": previo["serial"],
                            "previous_source_label": self._label(previo["imported_file_id"]),
                        })
            return FakeResult(rows=rows)

        if "previo.respondent_external_id = nuevo.respondent_external_id" in sql:
            rows = []
            for nuevo in self.respondents.values():
                if nuevo["imported_file_id"] != params["file"]:
                    continue
                for previo in self.respondents.values():
                    if previo["imported_file_id"] == nuevo["imported_file_id"]:
                        continue
                    if previo["serial"] == nuevo["serial"] and previo["realid"] != nuevo["realid"]:
                        rows.append({
                            "serial": nuevo["serial"], "new_realid": nuevo["realid"],
                            "previous_realid": previo["realid"],
                            "previous_source_label": self._label(previo["imported_file_id"]),
                        })
            return FakeResult(rows=rows)

        if "select id, status from import_review_flags" in sql:
            rows = [
                {"id": f["id"], "status": f["status"]}
                for f in self.flags.values()
                if f["imported_file_id"] == params["file"]
                and f["respondent_id"] == params["resp"]
                and f["flag_type"] == "possible_duplicate"
            ]
            return FakeResult(rows=rows)

        if "insert into import_review_flags" in sql:
            self.flags[params["id"]] = {
                "id": params["id"], "imported_file_id": params["file"],
                "respondent_id": params["resp"], "flag_type": "possible_duplicate",
                "detail": params["detail"], "status": "pending",
            }
            return FakeResult(rowcount=1)

        if "from import_review_flags f" in sql and "join imported_files i" in sql:
            rows = []
            for f in self.flags.values():
                if f["id"] == params["id"]:
                    rows.append({
                        "id": f["id"], "status": f["status"], "respondent_id": f["respondent_id"],
                        "detail": f["detail"], "imported_file_id": f["imported_file_id"],
                        "round_id": ROUND_ID, "file_id": f["imported_file_id"],
                    })
            return FakeResult(rows=rows)

        if "from import_review_flags f" in sql and "left join respondents r" in sql:
            rows = []
            for f in self.flags.values():
                if f["imported_file_id"] != params["file"]:
                    continue
                resp = self.respondents.get(f["respondent_id"])
                rows.append({
                    "id": f["id"], "status": f["status"], "detail": f["detail"],
                    "flag_type": f["flag_type"],
                    "serial": resp["serial"] if resp else None,
                    "realid": resp["realid"] if resp else None,
                })
            return FakeResult(rows=rows)

        if "select count(*) from import_review_flags" in sql:
            n = sum(
                1 for f in self.flags.values()
                if f["imported_file_id"] == params["file"] and f["status"] == "pending"
            )
            return FakeResult(scalar=n)

        if "select source_question_key, original_text from verbatims" in sql:
            rows = [
                {"source_question_key": v["question_key"], "original_text": v["text"]}
                for v in self.verbatims
                if v["respondent_id"] == params["resp"] and v["imported_file_id"] == params["file"]
            ]
            return FakeResult(rows=rows)

        if "delete from verbatims" in sql:
            before = len(self.verbatims)
            self.verbatims = [
                v for v in self.verbatims
                if not (v["respondent_id"] == params["resp"] and v["imported_file_id"] == params["file"])
            ]
            return FakeResult(rowcount=before - len(self.verbatims))

        if "update import_review_flags set detail" in sql:
            self.flags[params["id"]]["detail"] = params["detail"]
            return FakeResult(rowcount=1)

        if "update import_review_flags" in sql and "set status" in sql:
            self.flags[params["id"]]["status"] = params["st"]
            return FakeResult(rowcount=1)

        if "insert into audit_logs" in sql:
            self.audit_log.append(params)
            return FakeResult(rowcount=1)

        if "delete from mention_groups" in sql:
            return FakeResult(rowcount=0)

        return FakeResult()

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


def _two_load_session():
    """Carga vieja: Serial 1 (realid A), Serial 2 (realid B).
    Carga nueva: Serial 1 (realid C — colisión de Serial, persona distinta) y
    Serial 9 (realid A — duplicado real)."""
    db = FakeSession()
    db.add_file(FILE_OLD, checksum="old", label="Dimension Parte 1")
    db.add_file(FILE_NEW, checksum="new", status="uploaded", label="Enfield Parte 2")
    db.add_respondent(FILE_OLD, "1", "rev-AAA")
    db.add_respondent(FILE_OLD, "2", "rev-BBB")
    db.add_respondent(FILE_NEW, "1", "rev-CCC")
    dup_id = db.add_respondent(FILE_NEW, "9", "rev-AAA")
    db.add_verbatim(dup_id, FILE_NEW, "Q1", "gloria")
    db.add_verbatim(dup_id, FILE_NEW, "Q2", "laive")
    return db, dup_id


# ── detección: duplicado real vs Serial repetido ──


def test_duplicate_realid_is_flagged_and_kept():
    db, dup_id = _two_load_session()
    review = analyze_new_load(db, ROUND_ID, FILE_NEW)

    assert len(review["duplicates"]) == 1
    dup = review["duplicates"][0]
    assert dup["status"] == "pending"
    assert dup["serial"] == "9"
    assert dup["realid"] == "rev-AAA"
    assert dup["matches"] == [{"serial": "1", "source_label": "Dimension Parte 1"}]
    # Insertar y marcar: la fila sigue existiendo (los verbatims no se tocaron).
    assert any(v["respondent_id"] == dup_id for v in db.verbatims)
    assert len(db.flags) == 1


def test_repeated_serial_with_distinct_realid_is_informative_only():
    db, _ = _two_load_session()
    review = analyze_new_load(db, ROUND_ID, FILE_NEW)

    assert len(review["serial_collisions"]) == 1
    collision = review["serial_collisions"][0]
    assert collision["serial"] == "1"
    assert collision["new_realid"] == "rev-CCC"
    assert collision["previous_realid"] == "rev-AAA"
    assert collision["previous_source_label"] == "Dimension Parte 1"
    # Ningún flag para la colisión de Serial: ambos registros conviven.
    flagged = {f["respondent_id"] for f in db.flags.values()}
    serial_1_new = next(
        r["id"] for r in db.respondents.values()
        if r["imported_file_id"] == FILE_NEW and r["serial"] == "1"
    )
    assert serial_1_new not in flagged


def test_analyze_is_idempotent_on_reimport():
    # Reintento del import (p.ej. tras clasificar variables): no duplica flags.
    db, _ = _two_load_session()
    analyze_new_load(db, ROUND_ID, FILE_NEW)
    analyze_new_load(db, ROUND_ID, FILE_NEW)
    assert len(db.flags) == 1


# ── resolución humana ──


def test_resolve_keep_preserves_both():
    db, dup_id = _two_load_session()
    review = analyze_new_load(db, ROUND_ID, FILE_NEW)
    flag_id = uuid.UUID(review["duplicates"][0]["flag_id"])

    result = resolve_flag(db, flag_id, "keep", user_id=USER_ID)

    assert result["status"] == "approved_keep"
    assert result["pending_flags"] == 0
    assert any(v["respondent_id"] == dup_id for v in db.verbatims)
    assert db.committed
    assert db.audit_log  # constancia en audit_logs


def test_resolve_remove_deletes_new_load_verbatims_with_record():
    db, dup_id = _two_load_session()
    review = analyze_new_load(db, ROUND_ID, FILE_NEW)
    flag_id = uuid.UUID(review["duplicates"][0]["flag_id"])

    result = resolve_flag(db, flag_id, "remove", user_id=USER_ID)

    assert result["status"] == "approved_remove"
    assert result["removed_verbatims"] == 2
    assert not any(v["respondent_id"] == dup_id for v in db.verbatims)
    # Nada se borra sin constancia: los textos quedan en el detail del flag.
    detail = db.flags[flag_id]["detail"]
    assert "gloria" in detail and "laive" in detail


def test_resolve_edit_keeps_row_with_note():
    db, dup_id = _two_load_session()
    review = analyze_new_load(db, ROUND_ID, FILE_NEW)
    flag_id = uuid.UUID(review["duplicates"][0]["flag_id"])

    result = resolve_flag(db, flag_id, "edit", user_id=USER_ID, note="es la misma persona, se acepta")

    assert result["status"] == "edited"
    assert any(v["respondent_id"] == dup_id for v in db.verbatims)
    assert "es la misma persona" in db.flags[flag_id]["detail"]


def test_resolve_is_idempotent_on_double_submit():
    db, _ = _two_load_session()
    review = analyze_new_load(db, ROUND_ID, FILE_NEW)
    flag_id = uuid.UUID(review["duplicates"][0]["flag_id"])

    resolve_flag(db, flag_id, "keep", user_id=USER_ID)
    second = resolve_flag(db, flag_id, "remove", user_id=USER_ID)

    assert second["already_resolved"] is True
    assert db.flags[flag_id]["status"] == "approved_keep"  # la primera decisión gana


def test_resolve_rejects_unknown_action():
    db, _ = _two_load_session()
    review = analyze_new_load(db, ROUND_ID, FILE_NEW)
    flag_id = uuid.UUID(review["duplicates"][0]["flag_id"])
    with pytest.raises(ValueError):
        resolve_flag(db, flag_id, "borrar-todo", user_id=USER_ID)


def test_resolve_missing_flag_raises_lookup():
    db = FakeSession()
    with pytest.raises(LookupError):
        resolve_flag(db, uuid.uuid4(), "keep", user_id=USER_ID)


# ── estado de la cola (retomar la pantalla) ──


def test_get_load_review_reports_pending_and_collisions():
    db, _ = _two_load_session()
    analyze_new_load(db, ROUND_ID, FILE_NEW)

    state = get_load_review(db, ROUND_ID, FILE_NEW)
    assert state["pending_flags"] == 1
    assert state["requires_review"] is True
    assert len(state["serial_collisions"]) == 1

    flag_id = uuid.UUID(state["duplicates"][0]["flag_id"])
    resolve_flag(db, flag_id, "keep", user_id=USER_ID)
    state = get_load_review(db, ROUND_ID, FILE_NEW)
    assert state["pending_flags"] == 0
    assert state["requires_review"] is False


# ── archivo repetido / primera carga ──


def test_same_checksum_in_round_is_reported():
    db, _ = _two_load_session()
    dup = find_checksum_duplicate(db, ROUND_ID, "old")
    assert dup is not None
    assert dup["source_label"] == "Dimension Parte 1"
    assert find_checksum_duplicate(db, ROUND_ID, "inedito") is None


def test_first_load_has_no_previous():
    db = FakeSession()
    db.add_file(FILE_OLD, status="uploaded")
    assert round_has_previous_load(db, ROUND_ID, FILE_OLD) is False


def test_additional_load_detects_previous_validated():
    db, _ = _two_load_session()
    assert round_has_previous_load(db, ROUND_ID, FILE_NEW) is True


# ── propagación de códigos a verbatims nuevos de grupos ya resueltos ──


class PropagateResult(FakeResult):
    pass


class PropagateSession:
    """Estado mínimo para propagate_group_codes_to_pending: un grupo resuelto con
    un hermano codificado, y verbatims nuevos 'pending' colgados de ese grupo."""

    def __init__(self, group_status="resolved"):
        self.group_id = uuid.uuid4()
        self.group_status = group_status
        self.sibling_id = uuid.uuid4()
        self.new_ids = [uuid.uuid4(), uuid.uuid4()]
        self.code_id = uuid.uuid4()
        self.inserted_codes = []
        self.status_updates = {}

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}

        if "join mention_groups g on g.id = v.mention_group_id" in sql:
            rows = [
                {"verbatim_id": vid, "group_id": self.group_id, "group_status": self.group_status}
                for vid in self.new_ids
            ]
            return FakeResult(rows=rows)

        if "select v2.id from verbatims v2" in sql:
            return FakeResult(scalar=self.sibling_id)

        if "select code_id, output_index, source" in sql:
            return FakeResult(rows=[{
                "code_id": self.code_id, "output_index": 1,
                "source": "analyst_manual", "confidence_score": None, "matched_alias": "gloria",
            }])

        if "insert into verbatim_codes" in sql:
            self.inserted_codes.append(params)
            return FakeResult(rowcount=1)

        if "update verbatims set coding_status" in sql:
            self.status_updates[params["vid"]] = params["st"]
            return FakeResult(rowcount=1)

        return FakeResult()


def test_new_verbatim_in_resolved_group_inherits_codes_without_reopening():
    db = PropagateSession(group_status="resolved")
    updated = propagate_group_codes_to_pending(db, uuid.uuid4())

    assert updated == 2
    assert {p["vid"] for p in db.inserted_codes} == set(db.new_ids)
    assert all(p["code"] == db.code_id for p in db.inserted_codes)
    assert all(st == "manually_coded" for st in db.status_updates.values())


def test_new_verbatim_in_auto_coded_group_becomes_auto_coded():
    db = PropagateSession(group_status="auto_coded")
    propagate_group_codes_to_pending(db, uuid.uuid4())
    assert all(st == "auto_coded" for st in db.status_updates.values())


def test_propagate_noop_without_pending():
    class Empty:
        def execute(self, stmt, params=None):
            return FakeResult(rows=[])

    assert propagate_group_codes_to_pending(Empty(), uuid.uuid4()) == 0


def test_cleanup_orphan_groups_returns_rowcount():
    db, _ = _two_load_session()
    assert cleanup_orphan_groups(db, ROUND_ID) == 0

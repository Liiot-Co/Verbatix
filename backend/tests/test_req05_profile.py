"""REQ-05 — perfil de referencia vs Respondent ID (no realid).

Cubre los 8 casos del brief con FakeSession + Excel fixture generado
con openpyxl (equivalente a `perfil final_final.xlsx`).
"""
from __future__ import annotations

import io
import json
import uuid

import pytest
from openpyxl import Workbook

from app.pipeline.profile import (
    ProfileFormatError,
    match_file_against_profile,
    parse_profile_rows,
    resolve_profile_flag,
    resolve_profile_flags_bulk,
    save_profile_file,
)
from app.repositories import build_mention_groups

ROUND_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
SP_ID = uuid.uuid4()


def _make_profile_xlsx(rows: list[dict], *, missing_serial: bool = False) -> bytes:
    """Fixture estilo perfil final_final.xlsx."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Perfil"
    if missing_serial:
        headers = ["realid", "Completion Indicator", "Sexo", "Edad"]
    else:
        headers = ["Respondent ID", "realid", "Completion Indicator", "Sexo", "Edad"]
    ws.append(headers)
    for row in rows:
        if missing_serial:
            ws.append([
                row.get("realid"),
                row.get("completion", "Complete"),
                row.get("sexo", "M"),
                row.get("edad", 30),
            ])
        else:
            ws.append([
                row["serial"],
                row.get("realid"),
                row.get("completion", "Complete"),
                row.get("sexo", "M"),
                row.get("edad", 30),
            ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class FakeResult:
    def __init__(self, scalar=None, rows=None, rowcount=0):
        self._scalar = scalar
        self._rows = rows or []
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self):
        self.profile_files: dict = {}
        self.profile_entries: list[dict] = []
        self.respondents: dict = {}
        self.flags: dict = {}
        self.verbatims: list[dict] = []
        self.mention_groups: list[dict] = []
        self.audit_log: list = []
        self.committed = False

    def add_respondent(self, serial, realid, *, status="not_checked", file_id=FILE_ID):
        rid = uuid.uuid4()
        self.respondents[rid] = {
            "id": rid,
            "round_id": ROUND_ID,
            "imported_file_id": file_id,
            "respondent_external_id": serial,
            "realid": realid,
            "profile_status": status,
        }
        return rid

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).lower().split())
        params = params or {}

        if "insert into profile_files" in sql:
            self.profile_files[params["id"]] = dict(params)
            return FakeResult()

        if "select coding_type from profile_files" in sql:
            pf = self.profile_files.get(params["id"])
            return FakeResult(rows=[{"coding_type": pf.get("ct")}] if pf else [])

        if (
            "from profile_entries" in sql
            and "select respondent_external_id, realid" in sql
        ):
            pid = params.get("file") or params.get("id")
            rows = [
                {
                    "respondent_external_id": e["respondent_external_id"],
                    "realid": e.get("realid"),
                }
                for e in self.profile_entries
                if e["profile_file_id"] == pid
            ]
            return FakeResult(rows=rows)

        if "select count(*) from profile_entries" in sql:
            pid = params.get("file") or params.get("id")
            n = sum(1 for e in self.profile_entries if e["profile_file_id"] == pid)
            return FakeResult(scalar=n)

        if "insert into profile_entries" in sql:
            quotas = params.get("quotas")
            if isinstance(quotas, str):
                quotas = json.loads(quotas)
            self.profile_entries.append({
                "id": params["id"],
                "profile_file_id": params["file"],
                "respondent_external_id": params["serial"],
                "realid": params.get("realid"),
                "completion_indicator": params.get("comp"),
                "quotas": quotas,
            })
            return FakeResult()

        if "from profile_files" in sql and "order by created_at desc" in sql and "limit 1" in sql:
            if not self.profile_files:
                return FakeResult(scalar=None, rows=[])
            latest = max(self.profile_files.values(), key=lambda p: str(p["id"]))
            if "original_filename" in sql:
                return FakeResult(rows=[{
                    "id": latest["id"],
                    "original_filename": latest["name"],
                    "total_rows": latest["rows"],
                    "created_at": None,
                }])
            return FakeResult(scalar=latest["id"])

        if "from profile_entries" in sql and "respondent_external_id" in sql and "select respondent" in sql:
            pid = params.get("file") or params.get("id")
            serials = [
                e["respondent_external_id"] for e in self.profile_entries
                if e["profile_file_id"] == pid and e["respondent_external_id"]
            ]
            if "count(distinct" in sql:
                return FakeResult(scalar=len(set(serials)))
            return FakeResult(rows=serials)

        if "from profile_entries" in sql and "limit 1" in sql:
            return FakeResult(rows=[])

        if "from respondents" in sql and "imported_file_id = :file" in sql and "select id, respondent" in sql:
            rows = [
                {
                    "id": r["id"],
                    "respondent_external_id": r["respondent_external_id"],
                    "realid": r["realid"],
                    "profile_status": r["profile_status"],
                }
                for r in self.respondents.values()
                if r["imported_file_id"] == params["file"] and r["round_id"] == params["round"]
            ]
            return FakeResult(rows=rows)

        if "select distinct r.id" in sql or ("from respondents r" in sql and "join verbatims" in sql):
            ct = params.get("ct")
            rows = []
            for r in self.respondents.values():
                if r["imported_file_id"] != params["file"] or r["round_id"] != params["round"]:
                    continue
                has = any(
                    v.get("respondent_id") == r["id"]
                    and v.get("coding_type", ct) == ct
                    for v in self.verbatims
                )
                if has or not any(v.get("respondent_id") == r["id"] for v in self.verbatims):
                    # Si hay verbatims tipados, filtrar; si el fake no tipó, incluir
                    if any(v.get("respondent_id") == r["id"] and "coding_type" in v for v in self.verbatims):
                        if not has:
                            continue
                    rows.append({
                        "id": r["id"],
                        "respondent_external_id": r["respondent_external_id"],
                        "realid": r["realid"],
                        "profile_status": r["profile_status"],
                    })
            return FakeResult(rows=rows)

        if "select id from subprojects" in sql:
            sp = getattr(self, "subprojects", {}).get(params.get("ct"))
            return FakeResult(scalar=sp)

        if "from import_review_flags" in sql and "detail->>'coding_type'" in sql:
            for f in self.flags.values():
                if (
                    f["imported_file_id"] == params.get("file")
                    and f["respondent_id"] == params.get("resp")
                    and f["flag_type"] == "not_in_profile"
                    and (f.get("detail") or {}).get("coding_type") == params.get("ct")
                ):
                    return FakeResult(rows=[{"id": f["id"], "status": f["status"], "detail": f["detail"]}])
            return FakeResult(rows=[])

        if "from import_review_flags" in sql and "select id, status, detail" in sql:
            for f in self.flags.values():
                if (
                    f["imported_file_id"] == params.get("file")
                    and f["respondent_id"] == params.get("resp")
                    and f["flag_type"] == "not_in_profile"
                ):
                    return FakeResult(rows=[{"id": f["id"], "status": f["status"], "detail": f["detail"]}])
            return FakeResult(rows=[])

        if "update respondents set profile_status" in sql:
            if "id = any(:ids)" in sql or "id = any(:ids)" in sql.replace(" ", ""):
                ids = params.get("ids") or []
                for rid in ids:
                    if rid in self.respondents and "excluded_confirmed" in sql:
                        self.respondents[rid]["profile_status"] = "excluded_confirmed"
                return FakeResult()
            rid = params.get("id")
            if rid in self.respondents:
                # extract status from sql
                if "excluded_confirmed" in sql:
                    self.respondents[rid]["profile_status"] = "excluded_confirmed"
                elif "'matched'" in sql or "matched" in sql:
                    self.respondents[rid]["profile_status"] = "matched"
                elif "not_in_profile" in sql:
                    self.respondents[rid]["profile_status"] = "not_in_profile"
            return FakeResult()

        if "from import_review_flags" in sql and "id = any(:ids)" in sql:
            ids = set(params.get("ids") or [])
            if "flag_type = 'not_in_profile'" in sql and "status = 'pending'" in sql and "select f.id, f.respondent" in sql:
                rows = []
                for f in self.flags.values():
                    if f["id"] in ids and f["flag_type"] == "not_in_profile" and f["status"] == "pending":
                        rows.append({
                            "id": f["id"],
                            "respondent_id": f["respondent_id"],
                            "imported_file_id": f["imported_file_id"],
                            "detail": f.get("detail"),
                            "round_id": ROUND_ID,
                        })
                return FakeResult(rows=rows)
            if "limit 1" in sql:
                for f in self.flags.values():
                    if f["id"] in ids:
                        return FakeResult(rows=[{
                            "file_id": f["imported_file_id"],
                            "round_id": ROUND_ID,
                        }])
                return FakeResult(rows=[])

        if "from import_review_flags" in sql and "imported_file_id = :file" in sql and "select f.id" in sql and "not_in_profile" in sql:
            rows = [
                f["id"] for f in self.flags.values()
                if f["imported_file_id"] == params["file"]
                and f["flag_type"] == "not_in_profile"
                and f["status"] == "pending"
            ]
            return FakeResult(rows=rows)

        if "from import_review_flags" in sql and "flag_type = 'not_in_profile'" in sql:
            if "select id, status" in sql or ("select id, status from" in sql):
                for f in self.flags.values():
                    if (
                        f["imported_file_id"] == params.get("file")
                        and f["respondent_id"] == params.get("resp")
                        and f["flag_type"] == "not_in_profile"
                    ):
                        return FakeResult(rows=[{"id": f["id"], "status": f["status"]}])
                return FakeResult(rows=[])
            if "select id from" in sql and "status = 'pending'" in sql and "respondent_id" in sql:
                for f in self.flags.values():
                    if (
                        f["imported_file_id"] == params.get("file")
                        and f["respondent_id"] == params.get("resp")
                        and f["flag_type"] == "not_in_profile"
                        and f["status"] == "pending"
                    ):
                        return FakeResult(scalar=f["id"])
                return FakeResult(scalar=None)
            if "count(*)" in sql:
                n = sum(
                    1 for f in self.flags.values()
                    if f["imported_file_id"] == params["file"]
                    and f.get("flag_type", "not_in_profile") == "not_in_profile"
                    and f["status"] == "pending"
                )
                if "flag_type = 'not_in_profile'" not in sql and "status = 'pending'" in sql:
                    n = sum(
                        1 for f in self.flags.values()
                        if f["imported_file_id"] == params["file"] and f["status"] == "pending"
                    )
                return FakeResult(scalar=n)
            if "join imported_files" in sql:
                f = self.flags.get(params["id"])
                if not f or f["flag_type"] != "not_in_profile":
                    return FakeResult(rows=[])
                return FakeResult(rows=[{
                    "id": f["id"],
                    "status": f["status"],
                    "respondent_id": f["respondent_id"],
                    "detail": f["detail"],
                    "imported_file_id": f["imported_file_id"],
                    "round_id": ROUND_ID,
                }])

        if "select count(*) from import_review_flags" in sql and "status = 'pending'" in sql:
            n = sum(
                1 for f in self.flags.values()
                if f["imported_file_id"] == params["file"] and f["status"] == "pending"
            )
            return FakeResult(scalar=n)

        if "insert into import_review_flags" in sql:
            detail = params.get("detail")
            if isinstance(detail, str):
                detail = json.loads(detail)
            self.flags[params["id"]] = {
                "id": params["id"],
                "imported_file_id": params["file"],
                "respondent_id": params["resp"],
                "flag_type": "not_in_profile",
                "detail": detail,
                "status": "pending",
            }
            return FakeResult()

        if "update import_review_flags" in sql and "status = :st" in sql:
            if "id = any(:ids)" in sql:
                for fid in params.get("ids") or []:
                    f = self.flags.get(fid)
                    if f and f["status"] == "pending":
                        f["status"] = params["st"]
                return FakeResult()
            f = self.flags.get(params["id"])
            if f:
                f["status"] = params["st"]
            return FakeResult()

        if "update import_review_flags set detail" in sql:
            return FakeResult()

        if "update verbatims set mention_group_id = null" in sql or "update verbatims v" in sql:
            if "respondent_id = any(:resps)" in sql:
                resps = set(params.get("resps") or [])
                sp = params.get("sp")
                ct = params.get("ct")
                for v in self.verbatims:
                    if v["respondent_id"] not in resps:
                        continue
                    if v["imported_file_id"] != params["file"]:
                        continue
                    if sp is not None and v.get("subproject_id") not in (None, sp):
                        continue
                    if ct is not None and v.get("coding_type") not in (None, ct):
                        continue
                    v["mention_group_id"] = None
                return FakeResult(rowcount=len(resps))
            for v in self.verbatims:
                if v["respondent_id"] == params.get("resp") and v["imported_file_id"] == params["file"]:
                    v["mention_group_id"] = None
            return FakeResult(rowcount=1)

        if "insert into audit_log" in sql or "insert into action_log" in sql:
            self.audit_log.append(params)
            return FakeResult()

        # build_mention_groups queries (smoke)
        if "insert into mention_groups" in sql:
            return FakeResult()
        if "update verbatims v set mention_group_id" in sql:
            return FakeResult()
        if "select count(*) from mention_groups" in sql:
            return FakeResult(scalar=0)

        return FakeResult()

    def commit(self):
        self.committed = True


# ── parse ──


def test_parse_profile_allows_realid_only():
    content = _make_profile_xlsx(
        [{"realid": "R1"}, {"realid": "R2"}], missing_serial=True,
    )
    sheet, entries = parse_profile_rows(content)
    assert sheet == "Perfil"
    assert len(entries) == 2
    assert entries[0]["respondent_external_id"] is None
    assert entries[0]["realid"] == "R1"


def test_parse_profile_requires_serial_or_realid():
    wb = Workbook()
    ws = wb.active
    ws.append(["Sexo", "Edad"])
    ws.append(["M", 30])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ProfileFormatError, match="Respondent ID"):
        parse_profile_rows(buf.getvalue())


def test_parse_profile_keeps_realid_and_quotas_as_context():
    content = _make_profile_xlsx([
        {"serial": "101", "realid": "REAL-A", "sexo": "F", "edad": 25},
        {"serial": "102", "realid": "REAL-B", "sexo": "M", "edad": 40},
    ])
    sheet, entries = parse_profile_rows(content)
    assert sheet == "Perfil"
    assert len(entries) == 2
    assert entries[0]["respondent_external_id"] == "101"
    assert entries[0]["realid"] == "REAL-A"
    assert entries[0]["quotas"]["Sexo"] == "F"


# ── match ──


def test_all_serials_in_profile_zero_candidates():
    db = FakeSession()
    content = _make_profile_xlsx([
        {"serial": "1", "realid": "A"},
        {"serial": "2", "realid": "B"},
    ])
    _, entries = parse_profile_rows(content)
    saved = save_profile_file(
        db, round_id=ROUND_ID, original_filename="perfil.xlsx",
        storage_path=None, entries=entries, uploaded_by=USER_ID,
    )
    db.add_respondent("1", "A")
    db.add_respondent("2", "B")

    result = match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
        profile_file_id=uuid.UUID(saved["profile_file_id"]),
    )
    assert result["expected"] == 2
    assert result["arrived"] == 2
    assert result["extra"] == 0
    assert result["candidates"] == []
    assert result["summary"].endswith("sobran 0.")
    assert all(r["profile_status"] == "matched" for r in db.respondents.values())


def test_match_by_realid_union_when_serial_differs():
    """Unión Serial|realid: mismo realid en perfil → matched aunque Serial distinto."""
    db = FakeSession()
    content = _make_profile_xlsx([
        {"serial": "10", "realid": "SAME-PERSON"},
    ])
    _, entries = parse_profile_rows(content)
    saved = save_profile_file(
        db, round_id=ROUND_ID, original_filename="perfil.xlsx",
        storage_path=None, entries=entries, uploaded_by=USER_ID,
    )
    rid = db.add_respondent("99", "SAME-PERSON")

    result = match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
        profile_file_id=uuid.UUID(saved["profile_file_id"]),
    )
    assert result["extra"] == 0
    assert result["candidates"] == []
    assert db.respondents[rid]["profile_status"] == "matched"


def test_extra_serial_without_realid_overlap_is_candidate():
    """Serial distinto y realid distinto → candidato."""
    db = FakeSession()
    content = _make_profile_xlsx([
        {"serial": "10", "realid": "PERSON-A"},
    ])
    _, entries = parse_profile_rows(content)
    saved = save_profile_file(
        db, round_id=ROUND_ID, original_filename="perfil.xlsx",
        storage_path=None, entries=entries, uploaded_by=USER_ID,
    )
    rid = db.add_respondent("99", "PERSON-B")

    result = match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
        profile_file_id=uuid.UUID(saved["profile_file_id"]),
    )
    assert result["expected"] == 1
    assert result["arrived"] == 1
    assert result["extra"] == 1
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["serial"] == "99"
    assert db.respondents[rid]["profile_status"] == "not_in_profile"
    assert any(f["flag_type"] == "not_in_profile" for f in db.flags.values())


def test_typed_remove_only_unlinks_that_coding_type():
    db = FakeSession()
    brands_sp = uuid.uuid4()
    reasons_sp = uuid.uuid4()
    db.subprojects = {"brands": brands_sp, "reasons": reasons_sp}
    content = _make_profile_xlsx([{"serial": "1", "realid": "A"}])
    _, entries = parse_profile_rows(content)
    saved = save_profile_file(
        db, round_id=ROUND_ID, original_filename="perfil-marcas.xlsx",
        storage_path=None, entries=entries, uploaded_by=USER_ID,
        coding_type="brands",
    )
    rid = db.add_respondent("99", "X")
    db.verbatims.append({
        "respondent_id": rid, "imported_file_id": FILE_ID,
        "mention_group_id": uuid.uuid4(), "text": "marca",
        "coding_type": "brands", "subproject_id": brands_sp,
    })
    db.verbatims.append({
        "respondent_id": rid, "imported_file_id": FILE_ID,
        "mention_group_id": uuid.uuid4(), "text": "razon",
        "coding_type": "reasons", "subproject_id": reasons_sp,
    })
    match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
        profile_file_id=uuid.UUID(saved["profile_file_id"]),
    )
    flag_id = next(iter(db.flags))
    assert db.flags[flag_id]["detail"]["coding_type"] == "brands"

    result = resolve_profile_flag(db, flag_id, "remove", user_id=USER_ID)
    assert result["status"] == "approved_remove"
    assert db.respondents[rid]["profile_status"] != "excluded_confirmed"
    brands_v = next(v for v in db.verbatims if v["coding_type"] == "brands")
    reasons_v = next(v for v in db.verbatims if v["coding_type"] == "reasons")
    assert brands_v["mention_group_id"] is None
    assert reasons_v["mention_group_id"] is not None


def test_approve_exclusion_marks_excluded_without_deleting():
    db = FakeSession()
    content = _make_profile_xlsx([{"serial": "1", "realid": "A"}])
    _, entries = parse_profile_rows(content)
    saved = save_profile_file(
        db, round_id=ROUND_ID, original_filename="perfil.xlsx",
        storage_path=None, entries=entries, uploaded_by=USER_ID,
    )
    rid = db.add_respondent("99", "X")
    db.verbatims.append({
        "respondent_id": rid, "imported_file_id": FILE_ID,
        "mention_group_id": uuid.uuid4(), "text": "hola",
    })
    match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
        profile_file_id=uuid.UUID(saved["profile_file_id"]),
    )
    flag_id = next(iter(db.flags))

    result = resolve_profile_flag(db, flag_id, "remove", user_id=USER_ID)
    assert result["status"] == "approved_remove"
    assert db.respondents[rid]["profile_status"] == "excluded_confirmed"
    assert rid in db.respondents  # no borrado
    assert db.verbatims[0]["mention_group_id"] is None  # desenganchado, no borrado
    assert len(db.verbatims) == 1


def test_keep_candidate_processes_normally():
    db = FakeSession()
    content = _make_profile_xlsx([{"serial": "1", "realid": "A"}])
    _, entries = parse_profile_rows(content)
    saved = save_profile_file(
        db, round_id=ROUND_ID, original_filename="perfil.xlsx",
        storage_path=None, entries=entries, uploaded_by=USER_ID,
    )
    rid = db.add_respondent("99", "X")
    match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
        profile_file_id=uuid.UUID(saved["profile_file_id"]),
    )
    flag_id = next(iter(db.flags))

    result = resolve_profile_flag(db, flag_id, "keep", user_id=USER_ID)
    assert result["status"] == "approved_keep"
    assert db.respondents[rid]["profile_status"] == "not_in_profile"  # historial
    assert rid in db.respondents
    # Re-match no reabre approved_keep
    again = match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
        profile_file_id=uuid.UUID(saved["profile_file_id"]),
    )
    assert again["pending_flags"] == 0


def test_no_profile_is_noop_not_checked():
    db = FakeSession()
    rid = db.add_respondent("1", "A")
    result = match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
    )
    assert result["has_profile"] is False
    assert result["candidates"] == []
    assert result["pending_flags"] == 0
    assert db.respondents[rid]["profile_status"] == "not_checked"
    assert db.flags == {}


def test_fixture_perfil_style_end_to_end():
    """Fixture con presentes y ausentes — flujo completo parse → save → match."""
    db = FakeSession()
    content = _make_profile_xlsx([
        {"serial": "1001", "realid": "P-1001", "sexo": "F"},
        {"serial": "1002", "realid": "P-1002", "sexo": "M"},
        {"serial": "1003", "realid": "P-1003", "sexo": "F"},
    ])
    _, entries = parse_profile_rows(content)
    assert {e["respondent_external_id"] for e in entries} == {"1001", "1002", "1003"}
    saved = save_profile_file(
        db, round_id=ROUND_ID, original_filename="perfil final_final.xlsx",
        storage_path=None, entries=entries, uploaded_by=USER_ID,
    )
    db.add_respondent("1001", "P-1001")
    db.add_respondent("1002", "P-1002")
    db.add_respondent("9999", "EXTRA")  # sobra

    result = match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
        profile_file_id=uuid.UUID(saved["profile_file_id"]),
    )
    assert result["expected"] == 3
    assert result["arrived"] == 3
    assert result["extra"] == 1
    assert result["candidates"][0]["serial"] == "9999"


def test_bulk_exclude_all_in_one_shot():
    db = FakeSession()
    content = _make_profile_xlsx([{"serial": "1", "realid": "A"}])
    _, entries = parse_profile_rows(content)
    saved = save_profile_file(
        db, round_id=ROUND_ID, original_filename="perfil.xlsx",
        storage_path=None, entries=entries, uploaded_by=USER_ID,
    )
    r1 = db.add_respondent("10", "X")
    r2 = db.add_respondent("11", "Y")
    db.verbatims.append({
        "respondent_id": r1, "imported_file_id": FILE_ID,
        "mention_group_id": uuid.uuid4(), "text": "a",
    })
    db.verbatims.append({
        "respondent_id": r2, "imported_file_id": FILE_ID,
        "mention_group_id": uuid.uuid4(), "text": "b",
    })
    match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
        profile_file_id=uuid.UUID(saved["profile_file_id"]),
    )
    flag_ids = list(db.flags.keys())
    assert len(flag_ids) == 2

    result = resolve_profile_flags_bulk(
        db, flag_ids, "remove", user_id=USER_ID,
    )
    assert result["resolved"] == 2
    assert result["status"] == "approved_remove"
    assert result["pending_flags"] == 0
    assert db.respondents[r1]["profile_status"] == "excluded_confirmed"
    assert db.respondents[r2]["profile_status"] == "excluded_confirmed"
    assert all(v["mention_group_id"] is None for v in db.verbatims)
    assert all(f["status"] == "approved_remove" for f in db.flags.values())


def test_bulk_keep_all_in_one_shot():
    db = FakeSession()
    content = _make_profile_xlsx([{"serial": "1", "realid": "A"}])
    _, entries = parse_profile_rows(content)
    saved = save_profile_file(
        db, round_id=ROUND_ID, original_filename="perfil.xlsx",
        storage_path=None, entries=entries, uploaded_by=USER_ID,
    )
    db.add_respondent("10", "X")
    db.add_respondent("11", "Y")
    match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
        profile_file_id=uuid.UUID(saved["profile_file_id"]),
    )
    flag_ids = list(db.flags.keys())
    result = resolve_profile_flags_bulk(db, flag_ids, "keep", user_id=USER_ID)
    assert result["resolved"] == 2
    assert result["status"] == "approved_keep"
    assert result["pending_flags"] == 0
    assert all(f["status"] == "approved_keep" for f in db.flags.values())


def test_resolve_all_pending_by_file():
    from app.pipeline.profile import resolve_all_pending_profile_flags

    db = FakeSession()
    content = _make_profile_xlsx([{"serial": "1", "realid": "A"}])
    _, entries = parse_profile_rows(content)
    saved = save_profile_file(
        db, round_id=ROUND_ID, original_filename="perfil.xlsx",
        storage_path=None, entries=entries, uploaded_by=USER_ID,
    )
    db.add_respondent("10", "X")
    db.add_respondent("11", "Y")
    db.add_respondent("12", "Z")
    match_file_against_profile(
        db, round_id=ROUND_ID, imported_file_id=FILE_ID,
        profile_file_id=uuid.UUID(saved["profile_file_id"]),
    )
    assert sum(1 for f in db.flags.values() if f["status"] == "pending") == 3

    result = resolve_all_pending_profile_flags(
        db,
        round_id=ROUND_ID,
        imported_file_id=FILE_ID,
        action="remove",
        user_id=USER_ID,
    )
    assert result["resolved"] == 3
    assert result["pending_flags"] == 0
    assert all(f["status"] == "approved_remove" for f in db.flags.values())


def test_regression_without_profile_build_groups_unchanged():
    """Sin perfil, build_mention_groups no filtra a nadie (excluded_confirmed)."""
    db = FakeSession()
    # Solo verifica que la query se ejecuta sin exigir perfil.
    n = build_mention_groups(db, SP_ID)
    assert n == 0

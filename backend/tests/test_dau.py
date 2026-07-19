import os

import pytest

from app.pipeline.ingest import dau

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.dau")


def _content():
    with open(FIXTURE, "rb") as f:
        return f.read()


def test_is_dau():
    assert dau.is_dau(_content())
    assert not dau.is_dau(b"PK\x03\x04not a dau")


def test_detect_sheets():
    sheets = dau.detect_sheets(_content())
    assert len(sheets) == 1
    sheet = sheets[0]
    assert sheet["rows"] == 50
    assert sheet["guessed_as"] == "verbatims"
    assert "realid" in sheet["columns"]
    assert "NBS_UNAIDBlock[{_1}].NBS_UNAID" in sheet["columns"]


def test_parse_verbatims_includes_open_response_fields():
    rows = dau.parse_verbatims(_content())
    keys = {row["question_key"] for row in rows}
    assert "NBS_UNAIDBlock[{_1}].NBS_UNAID" in keys
    for row in rows:
        assert row["original_text"]
        assert row["respondent_external_id"]
        assert row["input_code_number"] is None
        assert row["truth_code_number"] is None


def test_parse_verbatims_excludes_infrastructure_fields():
    rows = dau.parse_verbatims(_content())
    keys = {row["question_key"] for row in rows}
    assert keys.isdisjoint(dau._NON_RESPONSE_FIELDS)


def test_parse_records_rejects_missing_bom():
    with pytest.raises(dau.DauFormatError):
        dau.parse_records(b"not a dau file")


def test_parse_records_rejects_empty():
    with pytest.raises(dau.DauFormatError):
        dau.parse_records(b"\xff\xfe")


def test_guess_coding_type_known_patterns():
    assert dau.guess_coding_type("NBS_UNAIDBlock[{_1}].NBS_UNAID") == "reasons"
    assert dau.guess_coding_type("NBS_UNAID_FUPBlock[{_1}].NBS_UNAID_FUP") == "brands"
    assert dau.guess_coding_type("NBS_UNAID_FUP_ADD[{_4}].Slice") == "brands"
    assert dau.guess_coding_type("VYK[1].Slice") == "brands"
    assert dau.guess_coding_type("CUST_BE1[1].Slice") is None


def test_other_fields_are_infrastructure_not_verbatims():
    assert "VXY.Other" in dau._NON_RESPONSE_FIELDS
    assert "VYH.Other" in dau._NON_RESPONSE_FIELDS

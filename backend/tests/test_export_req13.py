"""REQ-13 risk gate: does `Verbatim.source_question_key` carry the real
Dimensions variable+slice path needed to write SQL/OnNextCase exports?

FINDING (confirmed against the real HBG Leches fixtures, 2026-07-19):
- `.dau` ingest (`pipeline/ingest/dau.py::parse_verbatims`) sets `question_key`
  to the literal `##v '<field>' = ...` name from the client's export, e.g.
  `NBS_UNAID_FUP_ADD[{_4}].Slice`. That value is stored verbatim as
  `Verbatim.source_question_key` (see `repositories.py` import path).
- The real `..._SQL.txt` uses that exact same literal path
  (`UPDATE vdata SET NBS_UNAID_FUP_ADD[{_4}].Slice.Coding = {CB_4}, ...`) —
  SQL generation can use `source_question_key` directly, no transform needed.
- The real `..._OnNextCase.txt` uses a mangled form of the same path
  (`NBS_UNAID_FUP_ADD___4___Slice_Codes`): every occurrence of `[{_`, `}].`
  is replaced with `___` (each 3-char non-alphanumeric run -> 3 underscores)
  and a `_Codes` suffix is appended. Deterministic string transform, not a
  missing data problem.

CONCLUSION: `source_question_key` is sufficient. Not blocking Phase 2. No
schema/import change needed. `sql.py` uses it as-is; `onenextcase.py` applies
the mangle-and-suffix transform documented above.
"""
import os
import zipfile
from io import BytesIO

import pytest

from app.pipeline.export import (
    build_export_zip,
    build_metadata_txt,
    build_onenextcase_txt,
    build_sql_txt,
    mangle_variable,
)
from app.pipeline.ingest import dau

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.dau")


def _content():
    with open(FIXTURE, "rb") as f:
        return f.read()


def test_source_question_key_matches_real_dimensions_variable_path():
    """question_key for a coded-brand field must equal the literal Dimensions
    path (`Var[{_N}].Slice`), byte-for-byte the same string the real
    ..._SQL.txt uses in its `UPDATE vdata SET <path>.Coding = {CB_X}` lines."""
    rows = dau.parse_verbatims(_content())
    keys = {r["question_key"] for r in rows}

    assert "NBS_UNAID_FUP_ADD[{_4}].Slice" in keys
    assert "NBS_UNAIDBlock[{_1}].NBS_UNAID" in keys
    assert "NBS_UNAID_FUPBlock[{_1}].NBS_UNAID_FUP" in keys


def test_question_key_is_onenextcase_manglable():
    """The OnNextCase.txt variable name is a deterministic transform of the
    same question_key: non-alnum brackets/dots collapse to underscores and a
    `_Codes` suffix is appended. Confirmed against the real OnNextCase.txt
    line for the same respondent/variable (`..._Codes=..._Codes+{CB_4}`)."""
    key = "NBS_UNAID_FUP_ADD[{_4}].Slice"
    mangled = "".join(c if (c.isalnum() or c == "_") else "_" for c in key)
    assert mangled == "NBS_UNAID_FUP_ADD___4___Slice"
    assert f"{mangled}_Codes" == "NBS_UNAID_FUP_ADD___4___Slice_Codes"


_EXPORT_DATA = {
    "nets_by_coding_type": {
        "marcas": [
            {"name": "Ideal", "codes": [
                {"code_number": 1, "label": "Ideal"},
                {"code_number": 6, "label": "Anchor"},
            ]},
        ],
        "razones": [
            {"name": "NETO RAZONES", "codes": [
                {"code_number": 1, "label": "Precio"},
            ]},
        ],
    },
    "verbatims": [
        {"question_key": "NBS_UNAID_FUP_ADD[{_4}].Slice", "coding_type": "marcas"},
        {"question_key": "NBS_UNAID_FUP_ADD[{_5}].Slice", "coding_type": "marcas"},
        {"question_key": "NBS_UNAID_FUP_ADD[{_4}].Slice", "coding_type": "marcas"},
        {"question_key": "RAZ_ADD[{_1}].Slice", "coding_type": "razones"},
    ],
}


def test_build_metadata_txt_matches_fixture_syntax():
    """Structurally matches the real MetaData.txt: one `define {...}` block
    per distinct (coding_type, question_key), CRLF, no comma on last entry."""
    out = build_metadata_txt(_EXPORT_DATA)

    assert out.count("define \r\n  {") == 3  # 2 marcas vars (dedup) + 1 razones var
    assert 'CB_NBS_UNAID_FUP_ADD___4___Slice"NBS_UNAID_FUP_ADD[{_4}].Slice - " define \r\n' in out
    assert '    CB_1 "Ideal",\r\n    CB_6 "Anchor"\r\n  };' in out
    assert '    CB_1 "Precio"\r\n  };' in out


def test_build_metadata_txt_uses_real_catalog_numbers_only():
    """Never invents code numbers — every CB_N entry line comes straight
    from nets_by_coding_type[*][*]['codes'][*]['code_number']."""
    out = build_metadata_txt(_EXPORT_DATA)
    entry_numbers = {
        int(line.strip().split(" ", 1)[0].removeprefix("CB_"))
        for line in out.splitlines()
        if line.strip().startswith("CB_") and "define" not in line
    }
    assert entry_numbers == {1, 6}


def test_mangle_variable_matches_onenextcase_transform():
    assert mangle_variable("NBS_UNAID_FUP_ADD[{_4}].Slice") == "NBS_UNAID_FUP_ADD___4___Slice"


def test_build_sql_txt_matches_real_fixture_line():
    """Structurally matches the real ..._SQL.txt: one UPDATE vdata per
    respondent combining every coded variable, `<path>.Coding = {CB_N}`
    clauses (sorted by path for determinism — the vendor tool's own
    ordering is internal and not reproducible), CRLF, no trailing comma."""
    export_data = {
        "verbatims": [
            {"respondent_external_id": "3", "question_key": "NBS_UNAID_FUP_ADD[{_4}].Slice",
             "codes": [{"code_number": 4}]},
            {"respondent_external_id": "3", "question_key": "VYK[1].Slice",
             "codes": [{"code_number": 2}]},
            {"respondent_external_id": "3", "question_key": "NBS_UNAIDBlock[{_1}].NBS_UNAID",
             "codes": [{"code_number": 4}]},
            {"respondent_external_id": "5", "question_key": "VYK[1].Slice",
             "codes": [{"code_number": 2}]},
        ],
    }
    out = build_sql_txt(export_data)

    expected = (
        "UPDATE vdata SET NBS_UNAIDBlock[{_1}].NBS_UNAID.Coding = {CB_4}, "
        "NBS_UNAID_FUP_ADD[{_4}].Slice.Coding = {CB_4}, "
        "VYK[1].Slice.Coding = {CB_2} WHERE Respondent.Serial = 3\r\n"
        "UPDATE vdata SET VYK[1].Slice.Coding = {CB_2} WHERE Respondent.Serial = 5\r\n"
    )
    assert out == expected


def test_build_sql_txt_never_invents_codes():
    export_data = {
        "verbatims": [
            {"respondent_external_id": "3", "question_key": "VYK[1].Slice",
             "codes": [{"code_number": 2}]},
        ],
    }
    assert "CB_2" in build_sql_txt(export_data)
    assert build_sql_txt({"verbatims": []}) == ""


def test_build_onenextcase_txt_matches_real_fixture_syntax():
    """Structurally matches the real OnNextCase.txt: Select Case block, one
    tab-indented Case per respondent, two-tab-indented `<var>_Codes=...`
    lines using the mangled variable name (confirmed line-for-line against
    the real Case 3 / VYK[1] entry)."""
    export_data = {
        "verbatims": [
            {"respondent_external_id": "3", "question_key": "VYK[1].Slice",
             "codes": [{"code_number": 2}]},
            {"respondent_external_id": "5", "question_key": "NBS_UNAID_FUP_ADD[{_4}].Slice",
             "codes": [{"code_number": 16}]},
        ],
    }
    out = build_onenextcase_txt(export_data)

    expected = (
        "Select Case Respondent.Serial\r\n"
        "\tCase 3\r\n"
        "\t\tVYK_1__Slice_Codes=VYK_1__Slice_Codes+{CB_2}\r\n"
        "\tCase 5\r\n"
        "\t\tNBS_UNAID_FUP_ADD___4___Slice_Codes=NBS_UNAID_FUP_ADD___4___Slice_Codes+{CB_16}\r\n"
        "End Select\r\n"
    )
    assert out == expected


def test_build_onenextcase_txt_empty():
    assert build_onenextcase_txt({"verbatims": []}) == "Select Case Respondent.Serial\r\nEnd Select\r\n"


_ZIP_EXPORT_DATA = {
    "project_external_code": "32406432",
    "round_number": 1,
    "study_name": "HBG Leches",
    "total_verbatims": 1,
    "max_output_index": 1,
    "nets_by_coding_type": {
        "marcas": [{
            "name": "NETO MARCAS",
            "codes": [{"code_number": 1, "label": "Gloria", "content": "GLORIA", "frequency": 1, "pct": 1.0}],
        }],
    },
    "verbatims": [{
        "respondent_external_id": "3",
        "question_key": "NBS_UNAID_FUP_ADD[{_4}].Slice",
        "original_text": "GLORIA",
        "coding_type": "marcas",
        "codes": [{"output_index": 1, "code_number": 1, "label": "Gloria"}],
    }],
}


def test_build_export_zip_excel_only():
    zbytes = build_export_zip(_ZIP_EXPORT_DATA, {"excel"})
    with zipfile.ZipFile(BytesIO(zbytes)) as zf:
        assert zf.namelist() == ["LC_32406432_R1.xlsx"]


def test_build_export_zip_sql_and_onenextcase_share_one_dictionary():
    zbytes = build_export_zip(_ZIP_EXPORT_DATA, {"sql", "onenextcase"})
    with zipfile.ZipFile(BytesIO(zbytes)) as zf:
        names = set(zf.namelist())
        assert names == {"LC_32406432_R1_SQL.txt", "LC_32406432_R1_OnNextCase.txt", "LC_32406432_R1_MetaData.txt"}
        assert zf.read("LC_32406432_R1_SQL.txt")[:2] == b"\xff\xfe"


def test_build_export_zip_rejects_empty_or_unknown_formats():
    with pytest.raises(ValueError):
        build_export_zip(_ZIP_EXPORT_DATA, set())
    with pytest.raises(ValueError):
        build_export_zip(_ZIP_EXPORT_DATA, {"pdf"})


def test_build_export_zip_mdd_not_implemented_yet():
    with pytest.raises(NotImplementedError):
        build_export_zip(_ZIP_EXPORT_DATA, {"mdd"})

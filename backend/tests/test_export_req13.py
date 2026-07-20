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

from app.pipeline.export import build_metadata_txt, mangle_variable
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

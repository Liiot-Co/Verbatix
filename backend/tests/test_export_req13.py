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

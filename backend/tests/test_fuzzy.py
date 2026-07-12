"""Tests unitarios del fuzzy matching (pipelineProcess)."""
import polars as pl

from app.services.pipelineProcess import CodeAlias, run_fuzzy_matching
from app.services.pipelineProcess.models import Cols


CATALOG = [
    CodeAlias(code_id="c-gloria", alias_normalized="gloria"),
    CodeAlias(code_id="c-gloria", alias_normalized="fresco gloria"),
    CodeAlias(code_id="c-laive", alias_normalized="laive"),
    CodeAlias(code_id="c-bonle", alias_normalized="bonle"),
    CodeAlias(code_id="c-otto", alias_normalized="otto kunz"),
]


def _df(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def test_fuzzy_classifies_typos_and_exact():
    df = _df(
        [
            {
                "respondent_external_id": "1",
                "question_key": "q1",
                "normalized_text": "gloria",
                "coding_type": "brands",
            },
            {
                "respondent_external_id": "2",
                "question_key": "q1",
                "normalized_text": "glorai",
                "coding_type": "brands",
            },
            {
                "respondent_external_id": "3",
                "question_key": "q1",
                "normalized_text": "layve",
                "coding_type": "brands",
            },
            {
                "respondent_external_id": "4",
                "question_key": "q1",
                "normalized_text": "xyzmarca",
                "coding_type": "brands",
            },
        ]
    )
    res = run_fuzzy_matching(df, CATALOG)
    assert res.classified.height >= 2
    assert "xyzmarca" in res.unmatched[Cols.NORMALIZED_TEXT].to_list()
    assert set(res.classified[Cols.SOURCE].unique().to_list()) == {"engine_fuzzy"}


def test_reasons_all_go_unmatched():
    df = _df(
        [
            {
                "respondent_external_id": "1",
                "question_key": "q2",
                "normalized_text": "es rico y barato",
                "coding_type": "reasons",
            },
            {
                "respondent_external_id": "2",
                "question_key": "q2",
                "normalized_text": "gloria",
                "coding_type": "reasons",
            },
        ]
    )
    res = run_fuzzy_matching(df, CATALOG)
    assert res.classified.height == 0
    assert res.unmatched.height == 2


def test_empty_catalog_all_unmatched():
    df = _df(
        [
            {
                "respondent_external_id": "1",
                "question_key": "q1",
                "normalized_text": "gloria",
                "coding_type": "brands",
            },
        ]
    )
    res = run_fuzzy_matching(df, [])
    assert res.classified.height == 0
    assert res.unmatched.height == 1

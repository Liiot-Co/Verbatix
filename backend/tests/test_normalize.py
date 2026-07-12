import polars as pl
import pytest

from app.services.normalize import normalize
from app.services.normalize_pipeline import normalization_stats, rows_to_normalized_df


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("GLORIA", "gloria"),
        ("  gloria. ", "gloria"),
        ("Gloría!!", "gloria"),
        ("Bonlé", "bonle"),
        ("LAIVE", "laive"),
        ("Coca-Cola", "coca cola"),
        ("", ""),
        ("   ", ""),
        ("n/a", "n a"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_normalize_idempotent():
    for text in ("GLORIA", "  bonlé  ", "coca-cola"):
        once = normalize(text)
        assert normalize(once) == once


def test_pipeline_brands_slim_schema():
    rows = [
        {"respondent_external_id": "1", "question_key": "q1", "original_text": "GLORIA"},
        {"respondent_external_id": "2", "question_key": "q1", "original_text": "gloria."},
        {"respondent_external_id": "3", "question_key": "q1", "original_text": "   "},
    ]
    df = rows_to_normalized_df(rows, "brands")
    assert df.columns == [
        "respondent_external_id",
        "question_key",
        "normalized_text",
        "coding_type",
    ]
    assert df.height == 2
    assert df["coding_type"].unique().to_list() == ["brands"]
    assert df.filter(pl.col("normalized_text") == "gloria").height == 2


def test_pipeline_reasons_keeps_full_phrase():
    rows = [
        {
            "respondent_external_id": "99",
            "question_key": "q2",
            "original_text": "Es rico y BARATO",
        },
    ]
    df = rows_to_normalized_df(rows, "reasons")
    assert df.height == 1
    assert df.row(0, named=True)["normalized_text"] == "es rico y barato"
    assert df.row(0, named=True)["coding_type"] == "reasons"


def test_pipeline_stats():
    rows = [
        {"respondent_external_id": "1", "original_text": "GLORIA"},
        {"respondent_external_id": "2", "original_text": "gloria."},
        {"respondent_external_id": "3", "original_text": "   "},
    ]
    df = rows_to_normalized_df(rows, "brands")
    stats = normalization_stats(df, source_rows=3, coding_type="brands")
    assert stats["coding_type"] == "brands"
    assert stats["parsed_rows"] == 2
    assert stats["unique_normalized"] == 1

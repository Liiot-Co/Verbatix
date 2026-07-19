from app.pipeline.ingest import excel


def test_sample_values_returns_distinct_non_empty():
    rows = [
        {"Verbatim": "sabor rico"},
        {"Verbatim": "sabor rico"},
        {"Verbatim": "buen precio"},
        {"Verbatim": ""},
        {"Verbatim": None},
    ]
    assert set(excel.sample_values(rows, "Verbatim")) == {"sabor rico", "buen precio"}


def test_sample_values_caps_at_n():
    rows = [{"Verbatim": str(i)} for i in range(10)]
    result = excel.sample_values(rows, "Verbatim", n=3)
    assert len(result) == 3
    assert len(set(result)) == 3

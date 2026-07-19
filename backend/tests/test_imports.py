from app.pipeline import imports


def test_field_metadata_for_dau_known_pattern():
    records = [
        {"realid": "1", "NBS_UNAIDBlock[{_1}].NBS_UNAID": "razon a"},
        {"realid": "2", "NBS_UNAIDBlock[{_1}].NBS_UNAID": "razon b"},
    ]
    meta = imports.field_metadata_for_dau(records)
    fields = {m["field"]: m for m in meta}

    assert "realid" not in fields  # infraestructura, excluido
    known = fields["NBS_UNAIDBlock[{_1}].NBS_UNAID"]
    assert known["suggested_coding_type"] == "reasons"
    assert known["reason"]
    assert set(known["sample_values"]) == {"razon a", "razon b"}


def test_field_metadata_for_dau_unknown_pattern():
    records = [{"realid": "1", "CUST_BE1": "leche"}]
    meta = imports.field_metadata_for_dau(records)
    fields = {m["field"]: m for m in meta}

    unknown = fields["CUST_BE1"]
    assert unknown["suggested_coding_type"] is None
    assert unknown["reason"] == "sin patrón conocido, requiere clasificación manual"


def test_field_metadata_for_excel_never_suggests():
    rows = [{"Marca": "coca cola"}, {"Marca": "pepsi"}]
    meta = imports.field_metadata_for_excel(rows, ["Marca"])

    assert len(meta) == 1
    assert meta[0]["suggested_coding_type"] is None
    assert meta[0]["reason"] is None
    assert set(meta[0]["sample_values"]) == {"coca cola", "pepsi"}

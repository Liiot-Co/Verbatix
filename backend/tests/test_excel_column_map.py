"""Regresión: parse_verbatims sigue funcionando sin column_map (sniffing de header
'Verbatim' intacto), y admite column_map.verbatim explícito cuando viene."""
import io

from openpyxl import Workbook

from app.pipeline.ingest import excel


def _make_xlsx(header, data_rows):
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for row in data_rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_verbatims_without_column_map_unchanged():
    content = _make_xlsx(
        ["Respondent ID", "Question ID", "Verbatim"],
        [["1", "Q1", "sabor rico"], ["2", "Q1", "buen precio"]],
    )
    rows = excel.parse_verbatims(content, "Sheet")
    assert len(rows) == 2
    assert rows[0]["original_text"] == "sabor rico"


def test_parse_verbatims_with_explicit_column_map():
    content = _make_xlsx(
        ["Respondent ID", "Question ID", "Verbatim", "Comentario libre"],
        [["1", "Q1", "sabor rico", "otro texto"]],
    )
    rows = excel.parse_verbatims(content, "Sheet", {"verbatim": "Comentario libre"})
    assert len(rows) == 1
    assert rows[0]["original_text"] == "otro texto"

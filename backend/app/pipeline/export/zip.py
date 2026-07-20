"""Empaquetado del ZIP de exportación configurable (REQ-13 Fase 3)."""
import io
import zipfile

from .dictionary import build_metadata_txt
from .excel import build_codebook_excel
from .mdd import build_mdd_xml
from .onenextcase import build_onenextcase_txt
from .sql import build_sql_txt

VALID_FORMATS = {"excel", "sql", "onenextcase", "mdd"}


def build_export_zip(export_data: dict, formats: set[str]) -> bytes:
    """ZIP con los archivos seleccionados en `formats`. El diccionario CB_#
    (MetaData.txt) se incluye una sola vez si se pide sql/onenextcase/mdd —
    lo comparten los tres, no se duplica (ver Task 3)."""
    if not formats or not formats <= VALID_FORMATS:
        raise ValueError(f"formats must be a non-empty subset of {VALID_FORMATS}, got {formats!r}")

    ext = export_data.get("project_external_code") or "STUDIO"
    rnd = export_data.get("round_number") or 1
    base = f"LC_{ext}_R{rnd}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if "excel" in formats:
            zf.writestr(f"{base}.xlsx", build_codebook_excel(export_data))
        if "sql" in formats:
            sql_bytes = b"\xff\xfe" + build_sql_txt(export_data).encode("utf-16-le")
            zf.writestr(f"{base}_SQL.txt", sql_bytes)
        if "onenextcase" in formats:
            zf.writestr(f"{base}_OnNextCase.txt", build_onenextcase_txt(export_data).encode("utf-8"))
        if "mdd" in formats:
            zf.writestr(f"{base}.mdd", build_mdd_xml(export_data))
        if formats & {"sql", "onenextcase", "mdd"}:
            metadata = build_metadata_txt(export_data)
            zf.writestr(f"{base}_MetaData.txt", metadata.encode("utf-8"))

    return buf.getvalue()

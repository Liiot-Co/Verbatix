"""Empaquetado del ZIP de exportación (REQ-13)."""
import io
import zipfile

from .excel import build_codebook_excel
from .mdd import build_mdd_txt


def build_export_zip(export_data: dict) -> bytes:
    """ZIP con Excel LC + dos TXT simulando MDD."""
    ext = export_data.get("project_external_code") or "STUDIO"
    rnd = export_data.get("round_number") or 1
    base = f"LC_{ext}_R{rnd}"

    xlsx = build_codebook_excel(export_data)
    mdd1 = build_mdd_txt(export_data, 1).encode("utf-8")
    mdd2 = build_mdd_txt(export_data, 2).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base}.xlsx", xlsx)
        zf.writestr(f"{base}_mdd_1.txt", mdd1)
        zf.writestr(f"{base}_mdd_2.txt", mdd2)
    return buf.getvalue()

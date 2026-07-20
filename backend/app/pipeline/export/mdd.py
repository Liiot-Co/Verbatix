"""Generador de `.mdd` por template-clone (REQ-13 Fase 4, Task 11).

No reescribe el schema MDM desde cero: parte del `.mdd` real de HBG Leches
(`assets/mdd_template.mdd`) como plantilla y sólo reemplaza las categorías
dentro de los dos bloques `<categories name="CB_...">` (Marcas y Razones),
dejando atoms/languages/el resto del documento byte-idénticos. Ver hallazgo
de Task 10 en tasks/plan.md: sin una segunda muestra de cliente para validar
generalización — riesgo aceptado, no eliminado.
"""
import os
import re
from xml.sax.saxutils import escape

from .dictionary import _flatten_codes

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "assets", "mdd_template.mdd")

# (coding_type, categories id, categories name) — confirmados contra el .mdd real,
# mismo naming CB_<mangled_variable_name> ya usado en dictionary.py/onenextcase.py.
_CATALOG_BLOCKS = [
    ("brands", "7", "CB_NBS_UNAID_FUP_ADD___4___Slice"),
    ("reasons", "115", "CB_NBS_UNAIDBlock___1___NBS_UNAID"),
]


def _build_categories(codes: list[dict]) -> str:
    parts = []
    for c in codes:
        label = escape(str(c["label"]))
        parts.append(
            f'<category id="_mdd_{c["code_number"]}" name="CB_{c["code_number"]}">'
            f'<labels context="LABEL"><text context="ANALYSIS" xml:lang="en-US">{label}</text></labels>'
            f"</category>"
        )
    return "".join(parts)


def build_mdd_xml(export_data: dict) -> bytes:
    with open(_TEMPLATE_PATH, encoding="utf-8-sig") as f:
        text = f.read()

    nets_by_coding_type = export_data.get("nets_by_coding_type") or {}
    for coding_type, block_id, block_name in _CATALOG_BLOCKS:
        codes = _flatten_codes(nets_by_coding_type.get(coding_type) or [])
        pattern = re.compile(
            rf'(<categories id="{block_id}" name="{re.escape(block_name)}"[^>]*>'
            rf'<labels context="LABEL"><text context="ANALYSIS" xml:lang="en-US"></text></labels>)'
            rf".*?"
            rf'(<category id="_\d+" name="CB_99">.*?</category><deleted /></categories>)',
            re.S,
        )
        replacement = _build_categories(codes)
        text = pattern.sub(lambda m: m.group(1) + replacement + m.group(2), text)

    return ("\ufeff" + text).encode("utf-8")

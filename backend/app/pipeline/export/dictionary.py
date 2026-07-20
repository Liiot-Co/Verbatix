"""Diccionario compartido de definiciones CB_# (REQ-13 Fase 2).

Mismo contenido que necesitan tanto OnNextCase.txt como el bloque de
estructura del MDD: un bloque `define { CB_N "Label", ... }` por variable
Dimensions real, usando el catálogo de códigos del coding_type al que
pertenece esa variable (Marcas y Razones tienen catálogos independientes,
ver `_build_codebook_nets` en repositories.py)."""


def mangle_variable(question_key: str) -> str:
    """Transforma `Var[{_N}].Slice` en `Var___N___Slice`, igual que el
    nombre de variable real en OnNextCase.txt (ver test_export_req13.py)."""
    return "".join(c if (c.isalnum() or c == "_") else "_" for c in question_key)


def _flatten_codes(nets: list[dict]) -> list[dict]:
    codes = []
    for net in nets or []:
        codes.extend(net.get("codes") or [])
    return codes


def build_metadata_txt(export_data: dict) -> str:
    """Un bloque `define {...}` por variable Dimensions real (question_key),
    en el orden en que aparecen en `verbatims`, usando el catálogo de códigos
    de su coding_type."""
    nets_by_coding_type = export_data.get("nets_by_coding_type") or {}
    catalogs = {ct: _flatten_codes(nets) for ct, nets in nets_by_coding_type.items()}

    seen: set[tuple[str, str]] = set()
    blocks = []
    for v in export_data.get("verbatims") or []:
        coding_type = v.get("coding_type")
        question_key = v.get("question_key")
        if not coding_type or not question_key:
            continue
        dedup_key = (coding_type, question_key)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        codes = catalogs.get(coding_type) or []
        entries = ",\r\n".join(f'    CB_{c["code_number"]} "{c["label"]}"' for c in codes)
        blocks.append(
            f'CB_{mangle_variable(question_key)}"{question_key} - " define \r\n'
            f"  {{\r\n{entries}\r\n  }};"
        )

    return "\r\n\r\n".join(blocks) + "\r\n" if blocks else ""

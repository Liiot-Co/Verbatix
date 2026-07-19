"""Parser del Excel real del cliente (Gloria Queso y similares)."""
import io
import random
import re

from openpyxl import load_workbook

_ALIAS_COUNT = re.compile(r"\((\d+)\)\s*$")


def sample_values(rows: list[dict[str, object]], column: str, n: int = 5) -> list[str]:
    """Hasta `n` valores no vacíos y distintos de `column`, elegidos al azar."""
    seen: list[str] = []
    for r in rows:
        v = r.get(column)
        if v is None or v == "":
            continue
        s = str(v).strip()
        if s and s not in seen:
            seen.append(s)
    return seen if len(seen) <= n else random.sample(seen, n)


def _row_values(ws, limit=8):
    return [[c for c in row] for row in ws.iter_rows(min_row=1, max_row=limit, values_only=True)]


def detect_sheets(content: bytes) -> list[dict]:
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        head = _row_values(ws)
        flat = " ".join(str(c).lower() for row in head for c in row if c)
        if "verbatim" in flat and "respondent" in flat:
            guessed, cols = "verbatims", _header_of(head, "verbatim")
        elif "mencion principal" in flat or "mención principal" in flat or "codigo" in flat or "código" in flat:
            guessed, cols = "codebook", _header_of(head, "código", "codigo")
        else:
            guessed, cols = "unknown", []
        out.append({
            "name": ws.title,
            "rows": ws.max_row,
            "guessed_as": guessed,
            "columns": [str(c) for c in cols if c],
        })
    return out


def _header_of(head_rows, *keywords) -> list:
    for row in head_rows:
        low = [str(c).lower() if c else "" for c in row]
        if any(any(k in cell for k in keywords) for cell in low):
            return list(row)
    return []


def read_rows(content: bytes, sheet: str) -> tuple[list[str], list[dict[str, object]]]:
    """Primera fila como encabezado, resto como filas dict{columna: valor} —
    lectura genérica de una hoja para el preview de selección de campos
    (a diferencia de `parse_verbatims`, no asume una columna 'Verbatim')."""
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb[sheet]
    raw_rows = list(ws.iter_rows(values_only=True))
    if not raw_rows:
        return [], []
    header = [str(c).strip() if c else "" for c in raw_rows[0]]
    columns = [c for c in header if c]
    rows = [dict(zip(header, r)) for r in raw_rows[1:]]
    return columns, rows


def parse_verbatims(content: bytes, sheet: str, column_map: dict[str, str] | None = None) -> list[dict]:
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))
    header_i = next(
        (
            i for i, r in enumerate(rows)
            if r and any(str(c).strip().lower() == "verbatim" for c in r if c)
        ),
        None,
    )
    if header_i is None:
        # Sin el default, el next() vacío lanza StopIteration, que dentro de una
        # coroutine ASGI se convierte en un RuntimeError críptico (500).
        raise ValueError(f"La hoja '{sheet}' no tiene una columna 'Verbatim'")
    header = [str(c).strip().lower() if c else "" for c in rows[header_i]]

    def col(*names):
        for n in names:
            if n in header:
                return header.index(n)
        return None

    i_resp = col("respondent id")
    i_q = col("question id")
    # column_map.verbatim es explícito (usado por importaciones .dau, donde no
    # hay header "Verbatim" que adivinar); si no viene, cae al sniffing actual.
    verbatim_col = (column_map or {}).get("verbatim")
    i_txt = header.index(verbatim_col.strip().lower()) if verbatim_col and verbatim_col.strip().lower() in header else col("verbatim")
    i_in = col("input id 1", "input id")
    i_out = col("output id 1", "output id")

    out = []
    for r in rows[header_i + 1:]:
        if not r or i_txt is None or not r[i_txt]:
            continue
        out.append({
            "respondent_external_id": str(r[i_resp]) if i_resp is not None and r[i_resp] else None,
            "question_key": str(r[i_q]) if i_q is not None and r[i_q] else None,
            "original_text": str(r[i_txt]).strip(),
            "input_code_number": int(r[i_in]) if i_in is not None and isinstance(r[i_in], (int, float)) else None,
            "truth_code_number": int(r[i_out]) if i_out is not None and isinstance(r[i_out], (int, float)) else None,
        })
    return out


def parse_codebook(content: bytes, sheet: str) -> dict:
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))

    codes, nets, current_net = [], [], None
    for r in rows:
        if not r or all(c is None for c in r):
            continue
        a, b, c, d = (r + (None,) * 4)[:4]

        if isinstance(a, str) and "neto" in a.lower():
            current_net = a.strip()
            if current_net not in nets:
                nets.append(current_net)
            continue

        if isinstance(b, int) and isinstance(c, str):
            codes.append(_mk_code(b, c, d, current_net))
            continue

        if isinstance(a, int) and isinstance(b, str):
            codes.append(_mk_code(a, b, c, current_net))
            continue

    return {"codes": codes, "nets": nets}


def _mk_code(number: int, label: str, contenido, net) -> dict:
    aliases = []
    if isinstance(contenido, str):
        for raw in contenido.split("/"):
            raw = raw.strip()
            if not raw:
                continue
            m = _ALIAS_COUNT.search(raw)
            occ = int(m.group(1)) if m else 1
            aliases.append({"text": _ALIAS_COUNT.sub("", raw).strip(), "occurrences": occ})
            
    label_str = str(label).strip()
    if "/" in label_str:
        parts = label_str.split("/", 1)
        if not net:
            net = parts[0].strip()
        label_str = parts[1].strip()
        
    formatted_label = label_str.capitalize() if label_str else label_str
    
    return {
        "code_number": number,
        "label": formatted_label,
        "aliases": aliases,
        "net": net,
        "is_system": 95 <= number <= 99,
    }

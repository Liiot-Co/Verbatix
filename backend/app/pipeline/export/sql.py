"""Generador de UPDATE vdata ... (REQ-13 Fase 2, ver SQL.txt real de HBG Leches).

Un UPDATE por respondente, combinando todas sus variables codificadas
(Marcas + Razones, igual que el archivo real). `source_question_key` es el
path Dimensions literal (`Var[{_N}].Slice`), así que se usa tal cual, sin
mangling — a diferencia de OnNextCase (ver dictionary.py)."""


def build_sql_txt(export_data: dict) -> str:
    order: list[str] = []
    sets_by_respondent: dict[str, list[tuple[str, int]]] = {}

    for v in export_data.get("verbatims") or []:
        serial = v.get("respondent_external_id")
        question_key = v.get("question_key")
        if not serial or not question_key:
            continue
        if serial not in sets_by_respondent:
            sets_by_respondent[serial] = []
            order.append(serial)
        for code in v.get("codes") or []:
            # ponytail: one code per verbatim slot is the common case; a
            # double-coded verbatim emits a repeated SET clause for the
            # same path, which is a known limitation until a real
            # multi-code example turns up.
            sets_by_respondent[serial].append((question_key, code["code_number"]))

    lines = []
    for serial in order:
        clauses = sorted(sets_by_respondent[serial], key=lambda t: t[0])
        set_clause = ", ".join(f"{key}.Coding = {{CB_{num}}}" for key, num in clauses)
        lines.append(f"UPDATE vdata SET {set_clause} WHERE Respondent.Serial = {serial}")

    return "\r\n".join(lines) + "\r\n" if lines else ""

"""Generador del Case-script OnNextCase.txt (REQ-13 Fase 2).

`Select Case Respondent.Serial` con un `Case <serial>` por respondente y una
línea `<var>_Codes=<var>_Codes+{CB_N}` por código, usando el mismo mangling
de nombre de variable que el archivo real (ver dictionary.mangle_variable,
confirmado en Task 2 contra el OnNextCase.txt de HBG Leches)."""

from .dictionary import mangle_variable


def build_onenextcase_txt(export_data: dict) -> str:
    order: list[str] = []
    lines_by_respondent: dict[str, list[str]] = {}

    for v in export_data.get("verbatims") or []:
        serial = v.get("respondent_external_id")
        question_key = v.get("question_key")
        if not serial or not question_key:
            continue
        if serial not in lines_by_respondent:
            lines_by_respondent[serial] = []
            order.append(serial)
        var = f"{mangle_variable(question_key)}_Codes"
        for code in v.get("codes") or []:
            lines_by_respondent[serial].append(f"{var}={var}+{{CB_{code['code_number']}}}")

    body = []
    for serial in order:
        body.append(f"\tCase {serial}")
        for line in sorted(lines_by_respondent[serial]):
            body.append(f"\t\t{line}")

    return "\r\n".join(["Select Case Respondent.Serial", *body, "End Select"]) + "\r\n"

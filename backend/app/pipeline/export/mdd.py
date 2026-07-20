"""Simulación de archivos .mdd como TXT (hasta definir el formato XML real, ver REQ-13 Fase 4)."""
from datetime import datetime, timezone


def build_mdd_txt(export_data: dict, part: int) -> str:
    """Simulación de archivos .mdd como TXT (hasta definir el formato binario real).
    Combina Marcas y Razones — mismo criterio que build_codebook_excel."""
    ext = export_data.get("project_external_code") or "STUDIO"
    rnd = export_data.get("round_number") or 1
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    verbatims = export_data.get("verbatims") or []

    if part == 1:
        lines = [
            f"# Verbatix MDD simulation — coded verbatims (Marcas + Razones)",
            f"# Study: {ext} | Round: {rnd} | Generated: {stamp}",
            f"# Format: tab-separated (import placeholder)",
            "",
            "StudyID\tRespondentID\tQuestionID\tVerbatim\tOutputIndex\tCodeNumber\tCodeLabel",
        ]
        for v in verbatims:
            codes = sorted(v.get("codes") or [], key=lambda c: c.get("output_index", 1))
            if not codes:
                lines.append(
                    f"{ext}\t{v.get('respondent_external_id') or ''}\t"
                    f"{v.get('question_key') or ''}\t{v.get('original_text') or ''}\t\t\t"
                )
                continue
            for code in codes:
                lines.append(
                    f"{ext}\t{v.get('respondent_external_id') or ''}\t"
                    f"{v.get('question_key') or ''}\t{v.get('original_text') or ''}\t"
                    f"{code.get('output_index', 1)}\t{code.get('code_number', '')}\t"
                    f"{code.get('label', '')}"
                )
        return "\n".join(lines) + "\n"

    lines = [
        f"# Verbatix MDD simulation — codebook dictionary (Marcas + Razones)",
        f"# Study: {ext} | Round: {rnd} | Generated: {stamp}",
        "",
        "CodingType\tCodeNumber\tLabel\tFrequency\tPct\tNet\tContent",
    ]
    for coding_type, nets in (export_data.get("nets_by_coding_type") or {}).items():
        for net in nets or []:
            for code in net.get("codes") or []:
                lines.append(
                    f"{coding_type}\t{code['code_number']}\t{code['label']}\t{code['frequency']}\t"
                    f"{code['pct']}\t{net['name']}\t{code.get('content') or ''}"
                )
    return "\n".join(lines) + "\n"

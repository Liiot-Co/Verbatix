"""REQ-08 / REQ-04 — tope de código único (por Marcas/Razones) y decisión de
menciones extra (por ronda). No tocan guess_coding_type ni el wizard de
clasificación de Paso 0 más allá de consumir sus resultados.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.orm import Session


class SingleCodeViolation(ValueError):
    """Se intentó asignar más de un código de contenido con código único activo."""


ROUND_DECISION_KEY = "__round__"

# Separadores de menciones múltiples en un solo campo de Marcas: coma, barra y las
# conjunciones "y"/"e" aisladas (ej. "Gloria, bonle", "Bonlé y Laive"). Solo aplica
# a Marcas — en Razones "rico y barato" es una decisión semántica del LLM, no un
# split ortográfico.
_MENTION_SEPARATORS = re.compile(r"\s*,\s*|\s*/\s*|\s+y\s+|\s+e\s+", re.IGNORECASE)


def split_mentions(original_text: str) -> list[str]:
    """Parte un campo de Marcas en sus menciones, en orden y determinista.

    Solo separa cuando cada parte resultante es no vacía y de longitud >= 2; si el
    corte es ambiguo (deja fragmentos de 1 carácter, o no hay separador) devuelve el
    texto completo como una sola mención — que seguirá su curso normal (fuzzy/LLM/
    Resolución) en vez de romperse en pedazos inservibles.
    """
    text_value = (original_text or "").strip()
    if not text_value:
        return []
    parts = [part.strip() for part in _MENTION_SEPARATORS.split(text_value)]
    parts = [part for part in parts if part]
    if len(parts) <= 1 or any(len(part) < 2 for part in parts):
        return [text_value]
    return parts


def expand_brand_mentions(rows: list[dict], brand_keys: set[str]) -> list[dict]:
    """Expande cada fila de Marcas con varias menciones en un solo campo a una fila
    por mención, en orden. Debe correr ANTES de apply_mention_limits para que el
    tope de código único (primera mención) y el máximo de menciones se apliquen con
    la misma maquinaria a menciones ya separadas. Filas de otros tipos o de una sola
    mención se devuelven intactas.
    """
    if not brand_keys:
        return rows
    out: list[dict] = []
    for row in rows:
        if row.get("question_key") not in brand_keys:
            out.append(row)
            continue
        mentions = split_mentions(str(row.get("original_text") or ""))
        if len(mentions) <= 1:
            out.append(row)
            continue
        for mention in mentions:
            expanded = dict(row)
            expanded["original_text"] = mention
            out.append(expanded)
    return out


def max_mentions_per_respondent(rows: list[dict], question_key: str) -> int:
    """Máximo de ocurrencias de `question_key` por encuestado en el lote."""
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.get("question_key") != question_key:
            continue
        resp = str(row.get("respondent_external_id") or "").strip()
        if not resp:
            continue
        counts[resp] += 1
    return max(counts.values()) if counts else 0


def max_mentions_across_keys(rows: list[dict], question_keys: set[str]) -> int:
    """Máximo de menciones por encuestado entre las question_keys dadas."""
    if not question_keys:
        return 0
    return max(
        (max_mentions_per_respondent(rows, qk) for qk in question_keys),
        default=0,
    )


def apply_mention_limits(
    rows: list[dict],
    *,
    single_code_keys: set[str],
    limited_keys: dict[str, int],
) -> list[dict]:
    """Filtra el lote antes de insertar:

    - single_code_keys: solo la primera mención por (encuestado, pregunta)
    - limited_keys: como máximo N menciones por (encuestado, pregunta)
    """
    seen: dict[tuple[str, str], int] = defaultdict(int)
    out: list[dict] = []
    for row in rows:
        qk = row.get("question_key")
        if not qk:
            out.append(row)
            continue
        resp = str(row.get("respondent_external_id") or "").strip()
        key = (resp, qk)
        count = seen[key]
        if qk in single_code_keys:
            limit = 1
        elif qk in limited_keys:
            limit = limited_keys[qk]
        else:
            out.append(row)
            seen[key] = count + 1
            continue
        if count < limit:
            out.append(row)
            seen[key] = count + 1
    return out


def cap_codes_for_single_response(
    code_rows: list[dict],
    *,
    single_code: bool,
) -> list[dict]:
    """Tope duro REQ-08: con código único, como máximo 1 código de contenido
    (+ opcionalmente 1 de sistema). `code_rows` trae al menos `id` y `is_system`.
    Si hay >1 de contenido, se conserva el primero y se descartan el resto
    (motor); Resolución debe rechazar antes con SingleCodeViolation."""
    if not single_code or not code_rows:
        return code_rows
    content = [c for c in code_rows if not c.get("is_system")]
    system = [c for c in code_rows if c.get("is_system")]
    kept: list[dict] = []
    if content:
        kept.append(content[0])
    if system:
        kept.append(system[0])
    return kept


def assert_single_code_assignment(code_rows: list[dict], *, single_code: bool) -> None:
    """Resolución: con código único activo, pedir reemplazar — no sumar."""
    if not single_code:
        return
    content = [c for c in code_rows if not c.get("is_system")]
    system = [c for c in code_rows if c.get("is_system")]
    if len(content) > 1:
        raise SingleCodeViolation(
            "Esta ronda/tipo es de código único: reemplaza el código de contenido, no sumes otro"
        )
    if len(content) + len(system) > 2:
        raise SingleCodeViolation(
            "Código único admite como máximo un código de contenido y uno de sistema"
        )
    if len(system) > 1:
        raise SingleCodeViolation(
            "Código único admite como máximo un código de sistema"
        )


def persist_round_controls(
    db: Session,
    *,
    round_id: uuid.UUID,
    expected_max_mentions: int | None,
    single_code_by_type: dict[str, bool] | None,
) -> None:
    """Persiste interruptor por Marcas/Razones y máximo esperado de la ronda."""
    if expected_max_mentions is not None:
        db.execute(
            text("""
                update rounds
                   set expected_max_mentions = :max_m, updated_at = now()
                 where id = :id
            """),
            {"id": round_id, "max_m": expected_max_mentions},
        )
    if single_code_by_type:
        for coding_type, single in single_code_by_type.items():
            db.execute(
                text("""
                    update subprojects
                       set single_code_per_response = :single, updated_at = now()
                     where round_id = :round and coding_type = :ct
                """),
                {"round": round_id, "ct": coding_type, "single": bool(single)},
            )


def record_mention_decision(
    db: Session,
    *,
    imported_file_id: uuid.UUID,
    expected_max_mentions: int | None,
    detected_max_mentions: int,
    decision: str,
    decided_by,
) -> None:
    """Historial a nivel carga (ronda general), no por question_id."""
    if decision not in ("process_all", "limit_to_expected"):
        raise ValueError(f"Decisión de menciones inválida: {decision!r}")
    db.execute(
        text("""
            update imported_files
               set detected_max_mentions = :detected,
                   mentions_decision = :decision
             where id = :file
        """),
        {
            "file": imported_file_id,
            "detected": detected_max_mentions,
            "decision": decision,
        },
    )
    db.execute(
        text("""
            insert into question_mention_decisions (
              id, imported_file_id, question_id, question_key,
              expected_max_mentions, detected_max_mentions, decision, decided_by
            )
            values (
              :id, :file, null, :qk, :expected, :detected, :decision, :by
            )
            on conflict (imported_file_id, question_key) do update set
              expected_max_mentions = excluded.expected_max_mentions,
              detected_max_mentions = excluded.detected_max_mentions,
              decision = excluded.decision,
              decided_by = excluded.decided_by,
              decided_at = now()
        """),
        {
            "id": uuid.uuid4(),
            "file": imported_file_id,
            "qk": ROUND_DECISION_KEY,
            "expected": expected_max_mentions,
            "detected": detected_max_mentions,
            "decision": decision,
            "by": decided_by,
        },
    )

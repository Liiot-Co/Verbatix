"""
Contratos de datos del módulo de fuzzy matching.

Aquí viven las constantes de configuración, los nombres de columna que el
módulo consume/produce, y los schemas Pydantic de la capa HTTP. Ningún otro
archivo debe redefinir estos nombres: son la fuente única de verdad del contrato.
"""

from __future__ import annotations

import polars as pl
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Configuración del algoritmo
# --------------------------------------------------------------------------- #
# Score mínimo (0-100) para aceptar un match como clasificación automática.
# QUEMADO a propósito: el análisis sobre datos reales mostró que los typos de
# marca legítimos caen por encima de ~80 (layve->laive 80, glorai->gloria 83)
# mientras los falsos positivos quedan debajo (edan->edam 75). Se expone como
# constante para moverlo a config/env sin tocar la lógica.
SCORE_THRESHOLD: float = 80.0

# Solo las marcas se clasifican por similitud sintáctica. Las razones son
# equivalencias semánticas, no ortográficas (frescura ~ firme daría un falso
# positivo), así que se derivan enteras al siguiente módulo (LLM/embeddings).
FUZZY_CODING_TYPE: str = "brands"

# Textos de hasta este largo solo aceptan match exacto (score 100). WRatio
# escala el partial_ratio y regala matches por substring en textos cortos:
# sobre datos reales, 'uno' -> 'ninguno' daba 90 (falso positivo claro).
SHORT_TEXT_EXACT_MAX_LEN: int = 3

# Variantes canónicas (ya normalizadas) de las respuestas que corresponden a
# códigos de sistema, por system_type. En el flujo sin codebook evitan que
# "no se"/"ninguna" — casi siempre entre los textos más frecuentes — se
# promuevan como marcas falsas: se vuelven aliases del código de sistema y el
# fuzzy las codifica directo a 96/98/99.
SYSTEM_ALIAS_VARIANTS: dict[str, tuple[str, ...]] = {
    "no_answer": (
        "no sabe", "no se", "nose", "no sabria decir", "no conozco",
        "ni idea", "no idea", "sin idea", "ninguna idea", "no tengo idea",
        "no lo se", "no sabria", "no sabe no responde", "desconozco",
        "no conozco ninguna", "no conozco ninguno",
        "no estoy seguro", "no estoy segura", "no estoy segur",
        "no se bien", "no sabria decirte", "quien sabe",
    ),
    "none": (
        "nada", "ninguna", "ninguno", "ni una", "niguna",
        "mas ninguna", "mas ninguno", "ya ninguna", "ninguna mas",
    ),
    "no_recall": (
        "no recuerda", "no recuerdo", "no me acuerdo", "no responde",
        "no contesta", "no recuerdo ninguna", "no recuerdo el nombre",
    ),
    # 97 "Otras menciones": respuestas literales de catch-all, no marcas reales.
    "other_mentions": (
        "otros", "otro", "otras", "otra", "etc", "etcetera",
        "los demas", "las demas", "demas", "varios", "varias",
    ),
}


# --------------------------------------------------------------------------- #
# Nombres de columna (contrato con los módulos vecinos)
# --------------------------------------------------------------------------- #
class Cols:
    """Columnas que entran y salen del módulo."""

    # Entrada (lo que produce el módulo de normalización)
    RESPONDENT_ID = "respondent_external_id"
    QUESTION_KEY = "question_key"
    NORMALIZED_TEXT = "normalized_text"
    CODING_TYPE = "coding_type"

    # Salida de clasificados (para persistir en verbatim_codes)
    CODE_ID = "code_id"
    MATCHED_ALIAS = "matched_alias"
    SCORE = "score"
    SOURCE = "source"


# Valor de `source` con el que se etiquetan los clasificados por este módulo,
# alineado con la columna `verbatim_codes.source` del modelo de datos.
SOURCE_FUZZY: str = "engine_fuzzy"

# Schema del DataFrame de entrada que el módulo espera recibir.
INPUT_SCHEMA: dict[str, pl.DataType] = {
    Cols.RESPONDENT_ID: pl.String,
    Cols.QUESTION_KEY: pl.String,
    Cols.NORMALIZED_TEXT: pl.String,
    Cols.CODING_TYPE: pl.String,
}


# --------------------------------------------------------------------------- #
# Catálogo de códigos contra el que se hace matching
# --------------------------------------------------------------------------- #
class CodeAlias(BaseModel):
    """
    Un alias del libro de códigos. El caller (Supabase / tabla code_aliases)
    inyecta la lista de estos; el matcher no sabe de dónde vienen.
    """

    code_id: str
    alias_normalized: str


# --------------------------------------------------------------------------- #
# Contratos HTTP (capa FastAPI)
# --------------------------------------------------------------------------- #
class VerbatimIn(BaseModel):
    respondent_external_id: str
    normalized_text: str
    coding_type: str
    question_key: str | None = None


class MatchRequest(BaseModel):
    verbatims: list[VerbatimIn] = Field(min_length=1)
    catalog: list[CodeAlias] = Field(min_length=1)
    threshold: float | None = None


class ClassifiedOut(BaseModel):
    respondent_external_id: str
    question_key: str | None = None
    normalized_text: str
    code_id: str
    matched_alias: str
    score: float
    source: str


class UnmatchedOut(BaseModel):
    respondent_external_id: str
    question_key: str | None = None
    normalized_text: str
    coding_type: str


class MatchResponse(BaseModel):
    classified: list[ClassifiedOut]
    unmatched: list[UnmatchedOut]

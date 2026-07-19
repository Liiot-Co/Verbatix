"""Parser de exports .dau (Ascribe/IBM MDM) — mismo contrato de interfaz que excel.py.

Formato: UTF-16LE con BOM, CRLF, registros delimitados por
``##recstart N`` / ``##v 'campo' = 'valor'`` / ``##end N``. Portado de
parse_dau.py (prototipo standalone probado contra el .dau real del cliente).
"""
import random
import re

_FIELD_RE = re.compile(r"^##v '(.+?)' = '(.*)'$")
_RECSTART_RE = re.compile(r"^##recstart (\d+)$")
_END_RE = re.compile(r"^##end (\d+)$")
_BOM_UTF16_LE = b"\xff\xfe"
_BOM_UTF16_BE = b"\xfe\xff"

_SHEET_NAME = "Registros DAU"

# REQ-03: el N de '##recstart N' es el Serial del encuestado (validado contra el
# OnNextCase.txt real de HBG Leches: 'Select Case Respondent.Serial' -> Case 8
# codifica exactamente las variables con respuesta del bloque ##recstart 8).
# Se guarda bajo una clave reservada que no puede colisionar con un campo ##v
# (los nombres de campo nunca empiezan con '##').
_SERIAL_KEY = "##serial"

# Campos de infraestructura que IBM MDM/Ascribe siempre exporta en un .dau,
# sin importar el diseño del cuestionario (ver Datos Cliente/.../MetaData.txt
# y Formato DAU.md) — identificación, metadata de proyecto, fechas, URLs y
# control de calidad. Nunca son una respuesta del encuestado.
# ponytail: bloqueo exacto por nombre, no por prefijo — si un cliente futuro
# usa infraestructura adicional (otro export tool), esta lista no la cubre.
# Parametrizar por estudio (permitir que el analista agregue exclusiones) es
# la siguiente iteración, pendiente de un caso real que lo pida.
_NON_RESPONSE_FIELDS = frozenset({
    "realid",
    "panelDetails.ProfilesID",
    "panelDetails.IsPpgRespondent",
    "ProjectVersion",
    "ProjectPropertiesVersion",
    "MaconomyJobNo",
    "PROJECT_CODE",
    "ListVersions",
    "DataCollection.EndQuestion",
    "HiddenMethodology",
    "mbVars.rsval",
    "pasteAttemptData",
    "timings.yyyymmdd",
    "timings.weekNumber",
    "yyyymmdd",
    "weekno",
    "dumurl",
    "dumurl2",
    "DQM.Version",
    "DQM.ResponseEval",
    "DQM.ResponseEvalReason",
    # Campos "otro, especifique" de preguntas cerradas (ciudad no listada, tipo de
    # producto no listado) — texto libre pero no es un verbatim de marca/razón
    # (ver Formato DAU.md, sección "Campos Other"). Confirmados contra el .dau real
    # de 32406358 HBG LECHES; lista exacta, no por sufijo (mismo criterio que el
    # resto de este set — ver comentario ponytail arriba).
    "VXY.Other",
    "VYH.Other",
})


# Patrón de plantilla Ascribe/IBM MDM confirmado en dos estudios de clientes
# distintos (32406358 LECHES, 32406432 QUESO — ver Formato DAU.md sección 8):
# NBS_UNAIDBlock es siempre el loop de razones espontáneas, NBS_UNAID_FUP(Block|_ADD)
# es siempre la marca asociada a cada razón. Es un módulo reutilizado por la agencia,
# no específico de un proyecto, así que se puede clasificar sin pedirle al analista.
#
# VYK, en cambio, SÍ es específico del script de 32406358 HBG LECHES (confirmado
# contra su MetaData.txt: "VYK: BE1. ¿Qué marcas de LECHE conoces...?") — no es un
# nombre reutilizado entre clientes como NBS_UNAID (en QUESO la misma pregunta se
# llama CUST_BE1/CUST_BE2). Un futuro estudio con su propia variable de marca
# "clásica" bajo otro nombre seguirá sin patrón conocido y requerirá que
# ingeniería la revise y agregue aquí — por eso el wizard, para .dau, avisa en vez
# de dejar que el analista adivine (ver CreationWizard.tsx).
_KNOWN_CODING_TYPES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^NBS_UNAID_FUP_ADD\["), "brands"),
    (re.compile(r"^NBS_UNAID_FUPBlock\["), "brands"),
    (re.compile(r"^NBS_UNAIDBlock\["), "reasons"),
    (re.compile(r"^VYK\["), "brands"),
)


def guess_coding_type(question_key: str) -> str | None:
    """Coding_type conocido de antemano para question_keys que siguen la plantilla
    NBS_UNAID*, o None si el campo es específico del estudio y necesita
    clasificación manual (classify_question)."""
    for pattern, coding_type in _KNOWN_CODING_TYPES:
        if pattern.match(question_key):
            return coding_type
    return None


def sample_values(records: list[dict[str, str]], field: str, n: int = 5) -> list[str]:
    """Hasta `n` valores no vacíos y distintos de `field`, elegidos al azar."""
    seen: list[str] = []
    for r in records:
        v = r.get(field)
        if v and v not in seen:
            seen.append(v)
    return seen if len(seen) <= n else random.sample(seen, n)


class DauFormatError(ValueError):
    """El contenido no respeta el formato .dau esperado."""


def is_dau(content: bytes) -> bool:
    return content[:2] == _BOM_UTF16_LE


def _decode(content: bytes) -> str:
    if content[:2] == _BOM_UTF16_BE:
        raise DauFormatError("archivo UTF-16 big-endian (BOM FE FF); se espera UTF-16 little-endian (BOM FF FE)")
    if content[:2] != _BOM_UTF16_LE:
        raise DauFormatError(f"falta BOM UTF-16LE (se esperaban bytes FF FE, se obtuvo {content[:2]!r})")
    try:
        return content.decode("utf-16")
    except UnicodeDecodeError as exc:
        raise DauFormatError(f"secuencia UTF-16LE inválida: {exc}") from exc


def parse_records(content: bytes) -> list[dict[str, str]]:
    text = _decode(content)
    if not text.strip():
        raise DauFormatError("archivo vacío")

    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    current_num: str | None = None

    for line in text.replace("\r\n", "\n").split("\n"):
        recstart_m = _RECSTART_RE.match(line)
        end_m = _END_RE.match(line)

        if recstart_m:
            if current is not None:
                raise DauFormatError(
                    f"'##recstart {recstart_m.group(1)}' encontrado antes de cerrar el registro {current_num}"
                )
            current = {_SERIAL_KEY: recstart_m.group(1)}
            current_num = recstart_m.group(1)
        elif end_m:
            if current is None or end_m.group(1) != current_num:
                raise DauFormatError(f"'##end {end_m.group(1)}' sin '##recstart' correspondiente")
            records.append(current)
            current, current_num = None, None
        elif current is not None and line.startswith("##v "):
            # ponytail: asume que cada campo cabe en una línea. Un valor con un
            # salto de línea literal rompería este parseo — no manejado, ya que
            # los archivos reales del cliente no lo hacen (CRLF solo delimita
            # registros/campos). Líneas ##v malformadas se ignoran silenciosamente.
            m = _FIELD_RE.match(line)
            if m:
                current[m.group(1)] = m.group(2)

    if current is not None:
        raise DauFormatError(f"registro '##recstart {current_num}' sin '##end' correspondiente")
    if not records:
        raise DauFormatError("no se encontraron registros '##recstart'/'##end'")

    return records


def detect_sheets(content: bytes) -> list[dict]:
    records = parse_records(content)
    columns = sorted({key for r in records for key in r if not key.startswith("##")})
    return [{
        "name": _SHEET_NAME,
        "rows": len(records),
        "guessed_as": "verbatims",
        "columns": columns,
    }]


def parse_verbatims(content: bytes) -> list[dict]:
    """Un .dau no tiene "columna de verbatim" única (a diferencia de Excel):
    cada registro es un bloque de campos ##v. Se auto-selecciona como
    respuesta abierta todo campo que NO sea infraestructura conocida
    (`_NON_RESPONSE_FIELDS`) — el resto (razones, marcas mencionadas,
    campos "Other", variables codificadas de estudio) se toma tal cual,
    una fila por (registro, campo) con valor no vacío.
    """
    records = parse_records(content)
    out = []
    for r in records:
        realid = r.get("realid")
        # REQ-03: Serial (##recstart N) y realid quedan SEPARADOS. Plan B si un
        # registro no trajera serial (formato degradado): respondent_external_id
        # cae al realid, exactamente el comportamiento previo.
        serial = r.get(_SERIAL_KEY) or realid
        for field, value in r.items():
            if field.startswith("##") or field in _NON_RESPONSE_FIELDS or not value:
                continue
            out.append({
                "respondent_external_id": serial,
                "realid": realid,
                "question_key": field,
                "original_text": value.strip(),
                "input_code_number": None,
                "truth_code_number": None,
            })
    return out

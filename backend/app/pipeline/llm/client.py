import json
from typing import Literal

import requests
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings


PROMPT_VERSIONS = {
    "brands": "brand_residual_classification-v2",
    "reasons": "reason_residual_classification-v2",
}


def _coerce_idea_text(value: object) -> str | None:
    """DeepSeek a veces mete code_numbers o dicts en ordered_ideas."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)):
        return str(int(value))
    if isinstance(value, dict):
        for key in ("text", "idea", "label", "value"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        code_number = value.get("code_number")
        if code_number is not None:
            return str(code_number)
    return str(value)


class ResidualDecision(BaseModel):
    group_id: str
    decision: Literal["assign", "abstain", "propose_new_code", "system_candidate"]
    code_numbers: list[int] = Field(default_factory=list)
    ordered_ideas: list[str] = Field(default_factory=list)
    evidence: str = ""
    ambiguity_reason: str | None = None
    confidence: float = Field(ge=0, le=1)

    @field_validator("ordered_ideas", mode="before")
    @classmethod
    def coerce_ordered_ideas(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [text for text in (_coerce_idea_text(item) for item in value) if text]

    @model_validator(mode="after")
    def validate_decision_codes(self):
        if self.decision == "assign" and not self.code_numbers:
            raise ValueError("assign requiere code_numbers")
        if self.decision in ("abstain", "propose_new_code") and self.code_numbers:
            raise ValueError(f"{self.decision} no permite code_numbers")
        if len(self.code_numbers) != len(set(self.code_numbers)):
            raise ValueError("code_numbers contiene duplicados")
        return self


class ResidualResponse(BaseModel):
    prompt_version: str
    results: list[ResidualDecision]


_LIST_CAP = 8


class ReasonCodeProposal(BaseModel):
    index: int = Field(ge=0)
    net: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=500)
    inclusion_criteria: list[str] = Field(min_length=1)
    exclusion_criteria: list[str] = Field(min_length=1)
    examples: list[str] = Field(min_length=1)

    @field_validator("inclusion_criteria", "exclusion_criteria", "examples", mode="before")
    @classmethod
    def _truncate_list(cls, v: object) -> object:
        """Silently cap oversized lists instead of hard-failing validation.

        The LLM occasionally returns more than _LIST_CAP items; truncating is
        safer than aborting the entire round with a ValidationError.
        """
        if isinstance(v, list) and len(v) > _LIST_CAP:
            return v[:_LIST_CAP]
        return v


class ReasonCodebookResponse(BaseModel):
    prompt_version: Literal["reason_codebook_proposal-v1"]
    results: list[ReasonCodeProposal]


class BrandCanonicalProposal(BaseModel):
    index: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=120)
    category_fit: Literal["fits", "ambiguous", "unlikely"]
    rationale: str = Field(min_length=1, max_length=400)


class BrandCanonicalResponse(BaseModel):
    prompt_version: Literal["brand_canonicalization-v1"]
    results: list[BrandCanonicalProposal]


def _coerce_structured_envelope(payload: object, prompt_version: str) -> dict:
    """Normaliza respuestas LLM que a veces vienen como lista o sin prompt_version.

    DeepSeek con json_object a veces devuelve `[{...}]` en lugar de
    `{"prompt_version": "...", "results": [...]}`. Sin este wrapper el bootstrap
    scratch falla entero y la ronda queda en `failed`.
    """
    if isinstance(payload, list):
        return {"prompt_version": prompt_version, "results": payload}
    if isinstance(payload, dict):
        envelope = dict(payload)
        if "results" not in envelope and isinstance(envelope.get("proposals"), list):
            envelope["results"] = envelope.pop("proposals")
        envelope.setdefault("prompt_version", prompt_version)
        return envelope
    raise ValueError(f"Respuesta estructurada inesperada: {type(payload).__name__}")


_DOMAIN_INTRO = {
    "brands": (
        "El codebook de abajo codifica MARCAS del estudio, no razones. Cada verbatim que ves aquí "
        "ya pasó por un matcher exacto/difuso (fuzzy) contra los alias conocidos de cada marca y "
        "NO encontró match — son los casos difíciles a propósito: errores de tipeo raros, nombres "
        "parciales, marcas nuevas no catalogadas, o respuestas que no son marcas en absoluto. "
        "Solo asigna un code_number si el texto tiene sentido claro de marca: nombra o alude "
        "inequívocamente a una de las marcas listadas (variaciones, errores de tipeo cercanos, "
        "o el nombre parcial reconocible cuentan; una asociación libre o adivinanza no)."
    ),
    "reasons": (
        "El codebook de abajo codifica RAZONES (motivos que el encuestado da), no marcas. Cada "
        "línea tiene el formato 'numero: categoria/razon' (p.ej. '12: Contextura/Buena textura' "
        "o '34: Nivel de sal/Punto de sal'). La categoria es solo contexto para desambiguar "
        "razones parecidas en distintos temas. Clasifica por la razón que el texto expresa, "
        "usando el código cuya categoria mejor describa esa razón — incluida una categoria que "
        "sea sobre la marca/nombre en sí, si el codebook la tiene y el verbatim encaja ahí como "
        "razón. No le asignes un código de una categoria distinta solo porque el texto menciona "
        "una marca de pasada."
    ),
}

# 97 ("otras menciones") is a real catch-all, but for brands it must not swallow a nameable
# brand — "nestle" belongs in its own code (Nestlé), decided by a human in el Centro de
# Resolución, not buried under "otras menciones" where it's indistinguishable from noise.
_CODE97_RULE = {
    "brands": (
        "- NO uses 97 para una marca real identificable que no tiene su propio código en el "
        "codebook (p.ej. \"nestle\"): devuelve code_numbers como lista vacía [] para que quede "
        "pendiente de revisión humana, donde se puede crear esa marca como código propio. 97 es "
        "solo para respuestas válidas que de verdad no nombran ninguna marca identificable "
        "(descripciones vagas, genéricas, o sin nombre propio reconocible)."
    ),
    "reasons": (
        "- Usa 97 (otras menciones) solo cuando el texto SÍ corresponde al tema de la pregunta y es "
        "una respuesta válida y clara, pero nombra algo específico que no tiene su propio código en "
        "el codebook."
    ),
}


def _build_prompt(
    codebook: list[dict], verbatims: list[dict], coding_type: str,
    context: dict | None = None,
) -> str:
    codebook_lines = []
    for c in codebook:
        line = f"{c['code_number']}: {c['net']}/{c['label']}" if c.get("net") else f"{c['code_number']}: {c['label']}"
        aliases = c.get("aliases")
        if aliases and len(aliases) > 0:
            line += f" (Aliases: {', '.join(aliases)})"
        if c.get("definition"):
            line += f". Definición: {c['definition']}"
        if c.get("inclusion_criteria"):
            line += f". Incluye: {'; '.join(c['inclusion_criteria'])}"
        if c.get("exclusion_criteria"):
            line += f". Excluye: {'; '.join(c['exclusion_criteria'])}"
        if c.get("examples"):
            line += f". Ejemplos aprobados: {'; '.join(c['examples'][:5])}"
        codebook_lines.append(line)
    codebook_lines = "\n".join(codebook_lines)
    verbatim_lines = "\n".join(
        json.dumps({
            "group_id": v["id"], "text": v["text"],
            "frequency": v.get("frequency"),
            "surface_forms": v.get("surface_forms") or [],
            "questions": v.get("questions") or [],
        }, ensure_ascii=False)
        for v in verbatims
    )
    domain_intro = _DOMAIN_INTRO.get(coding_type, _DOMAIN_INTRO["reasons"])
    system_numbers = {
        c["system_type"]: c["code_number"]
        for c in codebook
        if c.get("system_type")
    }
    anomaly = system_numbers.get("anomaly", 95)
    no_answer = system_numbers.get("no_answer", 96)
    other_mentions = system_numbers.get("other_mentions", 97)
    none = system_numbers.get("none", 98)
    no_recall = system_numbers.get("no_recall", 99)
    code97_rule = _CODE97_RULE.get(
        coding_type, _CODE97_RULE["reasons"]
    ).replace("97", str(other_mentions))
    return (
        f"Eres un clasificador de verbatims de encuestas de marketing. {domain_intro}\n"
        f"Contexto del estudio: {json.dumps(context or {}, ensure_ascii=False)}\n"
        f"Versión de contrato: {PROMPT_VERSIONS.get(coding_type, 'residual-v2')}\n\n"
        "No estás obligado a dar una respuesta afirmativa. Usa criterio, no adivines:\n"
        "- Si el texto encaja claramente con un code_number del codebook, asígnalo.\n"
        "- Sé tolerante con errores ortográficos y de tipeo comunes (ej. 'pueraza' -> 'pureza').\n"
        f"- Usa un código de sistema ({anomaly} menciones confusas/incorrectas, "
        f"{no_answer} no sabe/no contesta, {other_mentions} otras menciones, "
        f"{none} ninguna, {no_recall} no recuerda/no responde) "
        "cuando el texto en sí expresa literalmente esa situación:\n"
        f"  · \"no sé\"/\"nose\"/\"no estoy seguro\" -> {no_answer}\n"
        f"  · \"ninguna\"/\"nada\"/\"más ninguna\" -> {none}\n"
        f"  · \"otros\"/\"otro\"/\"etc\" (catch-all literal, sin marca concreta) -> {other_mentions}\n"
        f"  · \"no responde\"/\"no recuerda\" -> {no_recall}\n"
        f"  · teclazo ilegible, basura o respuesta que NO corresponde al tema "
        f"(p.ej. una razón de compra en una pregunta de marcas; 'kjsdañfdsk jdsfj') -> {anomaly}\n"
        "No uses los códigos de sistema como cajón de sastre para casos difíciles de clasificar "
        "entre marcas/razones reales del codebook.\n"
        f"{code97_rule}\n"
        "- Si el caso es genuinamente difícil o ambiguo y ninguna de las reglas anteriores aplica "
        "con confianza, devuelve code_numbers como lista vacía []. Eso está bien — significa que "
        "va a revisión humana en una fase posterior, en vez de forzar una respuesta incorrecta.\n\n"
        "Además de code_numbers, para cada verbatim devuelve 'confidence': un número entre 0 y 1 "
        "que refleje qué tan seguro estás de esa clasificación (o de que ningún código aplica, si "
        "code_numbers es []). 1 = inequívoco, texto que encaja exactamente. 0.5 = razonable pero "
        "podría ser otra cosa. Cerca de 0 = estás adivinando. Sé honesto, no optimista — un caso "
        "de baja confianza también se resuelve en la revisión humana, así que no hay penalidad por "
        "admitir incertidumbre.\n\n"
        "Reglas para evitar alucinaciones:\n"
        "- Solo puedes usar code_numbers que aparecen LITERALMENTE en el Codebook de abajo. "
        "Nunca inventes, adivines ni extrapoles un número de código que no esté en la lista.\n"
        "- No asumas una marca o razón que el texto no menciona explícita o inequívocamente. "
        "Parafraseo y sinónimos claros sí cuentan; una asociación libre o suposición no.\n\n"
        "- Devuelve code_numbers en el orden en que las ideas aparecen en el texto. "
        "Si el contexto exige código único, conserva solo la primera idea de contenido.\n\n"
        f"Codebook:\n{codebook_lines}\n\n"
        f"Grupos (JSON por línea):\n{verbatim_lines}\n\n"
        'Responde ÚNICAMENTE con JSON en este formato exacto: '
        '{"prompt_version":"<versión indicada>","results":[{'
        '"group_id":"<uuid>","decision":"assign|abstain|propose_new_code|system_candidate",'
        '"code_numbers":[],"ordered_ideas":[],"evidence":"<texto mínimo>",'
        '"ambiguity_reason":null,"confidence":0.0}]}. '
        "Incluye exactamente un resultado por group_id. assign requiere códigos; abstain y "
        "propose_new_code no permiten códigos. system_candidate es solo sugerencia revisable."
    )


def classify_batch(
    codebook: list[dict], verbatims: list[dict], coding_type: str,
    context: dict | None = None,
) -> list[dict]:
    """Llama DeepSeek y valida el contrato completo antes de devolver candidatos."""
    prompt = _build_prompt(codebook, verbatims, coding_type, context)
    response = requests.post(
        f"{settings.llm_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={
            "model": settings.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "stream": False,
        },
        timeout=300,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    try:
        parsed = ResidualResponse.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError("DeepSeek devolvió una respuesta estructurada inválida") from e

    expected_version = PROMPT_VERSIONS.get(coding_type, "residual-v2")
    if parsed.prompt_version != expected_version:
        raise ValueError("DeepSeek devolvió una versión de prompt inesperada")
    expected_ids = [str(item["id"]) for item in verbatims]
    returned_ids = [item.group_id for item in parsed.results]
    if len(returned_ids) != len(set(returned_ids)):
        raise ValueError("DeepSeek devolvió group_id duplicados")
    if set(returned_ids) != set(expected_ids):
        raise ValueError("DeepSeek devolvió group_id incompletos o desconocidos")

    allowed_numbers = {int(item["code_number"]) for item in codebook}
    system_numbers = {
        int(item["code_number"]) for item in codebook if item.get("system_type")
    }
    by_id = {item.group_id: item for item in parsed.results}
    output = []
    for group_id in expected_ids:
        item = by_id[group_id]
        if any(number not in allowed_numbers for number in item.code_numbers):
            raise ValueError(f"DeepSeek devolvió un código inexistente para {group_id}")
        if item.decision == "system_candidate" and any(
            number not in system_numbers for number in item.code_numbers
        ):
            raise ValueError("system_candidate solo permite códigos de sistema")
        code_numbers = item.code_numbers
        if context and context.get("single_code_per_response") and len(code_numbers) > 1:
            code_numbers = code_numbers[:1]
        output.append({
            "verbatim_id": group_id, "decision": item.decision,
            "code_numbers": code_numbers, "ordered_ideas": item.ordered_ideas,
            "evidence": item.evidence, "ambiguity_reason": item.ambiguity_reason,
            "confidence": item.confidence,
        })
    return output


def _build_naming_prompt(representative_texts: list[str]) -> str:
    lines = "\n".join(f"{i}: {t}" for i, t in enumerate(representative_texts))
    return (
        "Eres un analista armando el libro de códigos de una encuesta de marketing. "
        "Cada línea de abajo es el texto más representativo de un grupo de razones de "
        "compra parecidas entre sí (ya agrupadas por similitud semántica). Para cada "
        "grupo, ponle un nombre de categoría corto (2-5 palabras, en español, con "
        "mayúscula inicial) que describa la idea general — no repitas el texto literal, "
        "generaliza (ej. 'Rico', 'Buen sabor', 'Delicioso' -> 'Buen sabor'). Un nombre por "
        "grupo, en el mismo orden.\n\n"
        f"Grupos:\n{lines}\n\n"
        'Responde ÚNICAMENTE con JSON: {"results": [{"index": <int>, "label": "<nombre>"}, ...]}, '
        "un objeto por cada índice de arriba, en cualquier orden."
    )


def _build_reason_codebook_prompt(
    cluster_summaries: list[str], context: dict | None = None, existing_nets: list[str] | None = None,
) -> str:
    lines = "\n".join(f"{index}: {summary}" for index, summary in enumerate(cluster_summaries))
    # Sin esta lista, cada llamada inventa nets a ciegas: la misma idea temática
    # termina repartida en nets distintos entre rondas ("Aroma" / "Sabor y
    # Aroma", "Tamaño" / "Tamaño/Cantidad") o, con la propuesta en paralelo por
    # lotes (ver semantic/cluster._propose_reason_codes_parallel), incluso
    # DENTRO de una misma corrida — cada lote ve solo su propio tramo de
    # clusters y no puede reutilizar el net que otro lote acaba de nombrar. Ver
    # los nets ya existentes (del codebook heredado + de rondas homologadas
    # previas) es lo único que da al modelo con qué reutilizar en vez de
    # sinónimos.
    nets_block = (
        "Nets ya existentes en este estudio (reutiliza el nombre EXACTO si la categoría "
        "corresponde; no inventes un sinónimo si uno de estos ya cubre la idea): "
        + (", ".join(existing_nets) if existing_nets else "ninguno todavía") + "\n"
    )
    return (
        "Eres un analista senior construyendo un libro de códigos de RAZONES para una encuesta. "
        "Cada índice representa un cluster semántico ponderado por frecuencia e incluye ejemplos "
        "centrales y de frontera. Propón una categoría operacional que un codificador pueda aplicar "
        "sin adivinar. Mantén categorías distintas cuando cambie la idea principal, la negación o "
        "la polaridad. Analiza el conjunto completo: si varios clusters pertenecen a la misma "
        "categoría operacional, reutiliza EXACTAMENTE el mismo net y label para permitir una fusión "
        "segura; evita duplicados léxicos como 'Precio'/'El precio'. Prefiere un libro compacto y "
        "exhaustivo antes que una categoría por frase. No inventes hechos que no aparezcan en los ejemplos.\n"
        f"Contexto del estudio: {json.dumps(context or {}, ensure_ascii=False)}\n\n"
        f"{nets_block}\n"
        f"Clusters:\n{lines}\n\n"
        "Responde ÚNICAMENTE con JSON válido: "
        '{"prompt_version":"reason_codebook_proposal-v1","results":[{'
        '"index":0,"net":"Neto temático","label":"Nombre corto",'
        '"definition":"Definición operacional","inclusion_criteria":["criterio observable"],'
        '"exclusion_criteria":["caso que pertenece a otra categoría"],'
        '"examples":["ejemplo textual del cluster"]}]}. '
        "Debe existir exactamente un resultado por índice, sin duplicados ni índices desconocidos."
    )


def propose_reason_codes(
    cluster_summaries: list[str], context: dict | None = None, existing_nets: list[str] | None = None,
) -> list[dict]:
    """Contrato estructurado para propuestas del libro de Razones."""
    if not cluster_summaries:
        return []
    response = requests.post(
        f"{settings.llm_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={
            "model": settings.llm_model,
            "messages": [{
                "role": "user",
                "content": _build_reason_codebook_prompt(cluster_summaries, context, existing_nets),
            }],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "stream": False,
        },
        timeout=300,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    try:
        payload = _coerce_structured_envelope(
            json.loads(content), "reason_codebook_proposal-v1",
        )
        parsed = ReasonCodebookResponse.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("DeepSeek devolvió una propuesta de libro inválida") from exc
    indices = [proposal.index for proposal in parsed.results]
    expected = set(range(len(cluster_summaries)))
    if len(indices) != len(set(indices)) or set(indices) != expected:
        raise ValueError("DeepSeek devolvió índices incompletos, duplicados o desconocidos")
    by_index = {proposal.index: proposal for proposal in parsed.results}
    return [by_index[index].model_dump() for index in range(len(cluster_summaries))]


def propose_brand_codes(
    cluster_summaries: list[str], context: dict | None = None,
) -> list[dict]:
    """Canoniza candidatos de Marca sin aprobarlos ni clasificarlos."""
    if not cluster_summaries:
        return []
    lines = "\n".join(f"{index}: {summary}" for index, summary in enumerate(cluster_summaries))
    prompt = (
        "Eres un analista de marcas. Canoniza cada cluster usando únicamente sus variantes y el "
        "contexto de categoría. Corrige capitalización/acentos solo cuando sea justificable; no "
        "conviertas una palabra parecida en otra marca. Marca category_fit como ambiguous o unlikely "
        "si la pertenencia a la categoría no es demostrable. Todas las respuestas serán revisadas por "
        "una persona y nunca se aprobarán automáticamente.\n"
        f"Contexto: {json.dumps(context or {}, ensure_ascii=False)}\nClusters:\n{lines}\n\n"
        'Responde solo JSON: {"prompt_version":"brand_canonicalization-v1","results":[{'
        '"index":0,"label":"Marca canónica","category_fit":"fits|ambiguous|unlikely",'
        '"rationale":"evidencia breve"}]}. Un resultado exacto por índice.'
    )
    response = requests.post(
        f"{settings.llm_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={
            "model": settings.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "stream": False,
        },
        timeout=300,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    try:
        payload = _coerce_structured_envelope(
            json.loads(content), "brand_canonicalization-v1",
        )
        parsed = BrandCanonicalResponse.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("DeepSeek devolvió una canonización de marcas inválida") from exc
    indices = [proposal.index for proposal in parsed.results]
    expected = set(range(len(cluster_summaries)))
    if len(indices) != len(set(indices)) or set(indices) != expected:
        raise ValueError("DeepSeek devolvió índices de marca incompletos, duplicados o desconocidos")
    by_index = {proposal.index: proposal for proposal in parsed.results}
    return [by_index[index].model_dump() for index in range(len(cluster_summaries))]


def name_clusters(representative_texts: list[str]) -> list[str]:
    """Un llamado LLM: le pone nombre de categoría a cada texto representativo
    de un cluster (ver pipeline/semantic/cluster.py). Devuelve las labels en el
    mismo orden que `representative_texts`; si el LLM omite un índice, cae al
    texto original capitalizado en vez de fallar todo el bootstrap."""
    if not representative_texts:
        return []
    prompt = _build_naming_prompt(representative_texts)
    response = requests.post(
        f"{settings.llm_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={
            "model": settings.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "stream": False,
        },
        timeout=300,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    try:
        results = json.loads(content)["results"]
    except json.JSONDecodeError as e:
        raise ValueError(f"DeepSeek returned non-JSON content: {content!r}") from e

    labels = [t.strip().capitalize() for t in representative_texts]
    for r in results:
        idx = r.get("index")
        if isinstance(idx, int) and 0 <= idx < len(labels) and r.get("label"):
            labels[idx] = r["label"]
    return labels

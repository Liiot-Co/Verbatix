import json

import requests

from app.core.config import settings


_DOMAIN_INTRO = {
    "brands": (
        "El codebook de abajo codifica MARCAS de queso, no razones. Cada verbatim que ves aquí "
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


def _build_prompt(codebook: list[dict], verbatims: list[dict], coding_type: str) -> str:
    codebook_lines = []
    for c in codebook:
        line = f"{c['code_number']}: {c['net']}/{c['label']}" if c.get("net") else f"{c['code_number']}: {c['label']}"
        aliases = c.get("aliases")
        if aliases and len(aliases) > 0:
            line += f" (Aliases: {', '.join(aliases)})"
        codebook_lines.append(line)
    codebook_lines = "\n".join(codebook_lines)
    verbatim_lines = "\n".join(f"{v['id']}: {v['text']}" for v in verbatims)
    domain_intro = _DOMAIN_INTRO.get(coding_type, _DOMAIN_INTRO["reasons"])
    code97_rule = _CODE97_RULE.get(coding_type, _CODE97_RULE["reasons"])
    return (
        f"Eres un clasificador de verbatims de encuestas de marketing. {domain_intro}\n\n"
        "No estás obligado a dar una respuesta afirmativa. Usa criterio, no adivines:\n"
        "- Si el texto encaja claramente con un code_number del codebook, asígnalo.\n"
        "- Sé tolerante con errores ortográficos y de tipeo comunes (ej. 'pueraza' -> 'pureza').\n"
        "- Usa un código de sistema (95 menciones confusas/incorrectas, 96 no sabe/no contesta, "
        "98 ninguna, 99 no recuerda/no responde) SOLO cuando el texto en sí expresa literalmente "
        "esa situación: \"no sé\" -> 96; vacío, ilegible, o una respuesta clara que NO corresponde "
        "en absoluto al tema de la pregunta (p.ej. una razón de compra en una pregunta de marcas) "
        "-> 95; \"ninguna\"/\"nada\" -> 98; \"no responde\"/\"no recuerda\" -> 99. No son un cajón "
        "de sastre para casos difíciles de clasificar.\n"
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
        f"Codebook:\n{codebook_lines}\n\n"
        f"Verbatims (id: texto):\n{verbatim_lines}\n\n"
        'Responde ÚNICAMENTE con JSON en este formato exacto: '
        '{"results": [{"verbatim_id": "<id>", "code_numbers": [<int>, ...], "confidence": <0-1>}, ...]}. '
        "code_numbers puede ser una lista vacía. Incluye un objeto por cada verbatim, en el mismo orden."
    )


def classify_batch(codebook: list[dict], verbatims: list[dict], coding_type: str) -> list[dict]:
    """Calls the DeepSeek chat API with JSON-mode output. Returns [{verbatim_id, code_numbers, confidence}]."""
    prompt = _build_prompt(codebook, verbatims, coding_type)
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
        return json.loads(content)["results"]
    except json.JSONDecodeError as e:
        raise ValueError(f"DeepSeek returned non-JSON content: {content!r}") from e


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

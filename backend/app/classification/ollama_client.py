import json

import requests

from app.config import settings

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "verbatim_id": {"type": "string"},
                    "code_numbers": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["verbatim_id", "code_numbers"],
            },
        },
    },
    "required": ["results"],
}


def _build_prompt(codebook: list[dict], verbatims: list[dict]) -> str:
    codebook_lines = "\n".join(f"{c['code_number']}: {c['label']}" for c in codebook)
    verbatim_lines = "\n".join(f"{v['id']}: {v['text']}" for v in verbatims)
    return (
        "Eres un clasificador de verbatims de encuestas de marketing. "
        "Asigna a cada verbatim uno o más códigos del codebook. Si el verbatim no aplica a "
        "ningún código específico, usa el código de sistema que mejor describa el caso "
        "(95 menciones confusas/incorrectas, 96 no sabe/no contesta, 97 otras menciones, "
        "98 ninguna, 99 no responde). Nunca dejes code_numbers vacío.\n\n"
        "Reglas para evitar alucinaciones:\n"
        "- Solo puedes usar code_numbers que aparecen LITERALMENTE en el Codebook de abajo. "
        "Nunca inventes, adivines ni extrapoles un número de código que no esté en la lista.\n"
        "- No asumas una marca o razón que el texto no menciona explícita o inequívocamente. "
        "Parafraseo y sinónimos claros sí cuentan; una asociación libre o suposición no.\n"
        "- Si el texto es ambiguo, ilegible, o no corresponde con claridad a ningún código del "
        "codebook, usa 97 (otras menciones) o 96 (no sabe) en vez de forzar el código que más se "
        "parezca.\n\n"
        f"Codebook:\n{codebook_lines}\n\n"
        f"Verbatims (id: texto):\n{verbatim_lines}\n"
    )


def classify_batch(codebook: list[dict], verbatims: list[dict]) -> list[dict]:
    """Calls the local Ollama model with structured output. Returns [{verbatim_id, code_numbers}]."""
    prompt = _build_prompt(codebook, verbatims)
    response = requests.post(
        f"{settings.ollama_host}/api/chat",
        json={
            "model": settings.ollama_model,
            "messages": [{"role": "user", "content": prompt}],
            "format": RESULT_SCHEMA,
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    content = response.json()["message"]["content"]
    return json.loads(content)["results"]

import json
from unittest.mock import patch

import pytest

from app.pipeline.llm.client import (
    PROMPT_VERSIONS,
    _build_prompt,
    classify_batch,
    propose_brand_codes,
    propose_reason_codes,
)


def test_brands_prompt_forbids_97_for_real_uncatalogued_brands():
    prompt = _build_prompt(codebook=[{"code_number": 1, "label": "Alpina", "net": None}], verbatims=[], coding_type="brands")
    assert "NO uses 97" in prompt


def test_reasons_prompt_keeps_permissive_97_rule():
    prompt = _build_prompt(codebook=[{"code_number": 1, "label": "Buena textura", "net": None}], verbatims=[], coding_type="reasons")
    assert "NO uses 97" not in prompt
    assert "Usa 97 (otras menciones) solo cuando" in prompt


def test_reasons_prompt_instructs_net_level_match_before_97():
    """El caso reportado: 'omega', 'dha', 'fortificada' deben ir al código del net
    Vitaminas (aunque el ejemplo literal no aparezca en el codebook), no a 97."""
    prompt = _build_prompt(
        codebook=[{"code_number": 19, "label": "Que sea nutritiva", "net": "Vitaminas"}],
        verbatims=[], coding_type="reasons",
    )
    assert "TEMA (net) de algún código" in prompt
    assert "no exijas que el término sea idéntico a un ejemplo ya visto" in prompt


@pytest.mark.parametrize("mention", ["omega", "dha", "fortificada", "minerales", "suplementos"])
def test_classify_batch_routes_vitamin_mentions_to_net_code_not_97(mention):
    """Antes de la regla, 'omega'/'dha'/etc. caían a 97 (otras menciones) por no
    coincidir literalmente con ningún ejemplo del código de nutrientes/vitaminas."""
    response = FakeResponse({
        "prompt_version": PROMPT_VERSIONS["reasons"],
        "results": [{
            "group_id": "g1", "decision": "assign", "code_numbers": [19],
            "ordered_ideas": [mention], "evidence": mention,
            "ambiguity_reason": None, "confidence": 0.85,
        }],
    })
    codebook = [{"code_number": 19, "label": "Que sea nutritiva", "net": "Vitaminas"}]
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        result = classify_batch(codebook, [{"id": "g1", "text": mention}], "reasons")
    assert result[0]["code_numbers"] == [19]


def test_reasons_prompt_instructs_specific_label_when_net_has_multiple_codes():
    """Edge case: dos códigos comparten net 'Nutrientes' (Vitaminas vs Proteína).
    El modelo no debe usar el net como excusa para asignar cualquiera al azar."""
    prompt = _build_prompt(
        codebook=[
            {"code_number": 19, "label": "Vitaminas", "net": "Nutrientes"},
            {"code_number": 20, "label": "Proteína", "net": "Nutrientes"},
        ],
        verbatims=[], coding_type="reasons",
    )
    assert "elige el label más específico" in prompt


def test_reasons_prompt_forbids_forcing_opposite_valence_into_same_theme_code():
    """Edge case: 'mal sabor' no debe forzarse en un código de net 'Sabor'/'Buen sabor'
    solo porque comparten tema — la valencia es opuesta."""
    prompt = _build_prompt(
        codebook=[{"code_number": 12, "label": "Buen sabor", "net": "Sabor"}],
        verbatims=[], coding_type="reasons",
    )
    assert "sentido opuesto" in prompt
    assert "no lo fuerces ahí solo porque el tema coincide" in prompt


@pytest.mark.parametrize(
    "mention,expected_code",
    [("omega", 19), ("proteina", 20)],
)
def test_classify_batch_picks_specific_code_among_shared_net(mention, expected_code):
    """Dos códigos comparten el net 'Nutrientes': el modelo debe distinguir cuál
    label específico aplica en vez de tratarlos como intercambiables."""
    response = FakeResponse({
        "prompt_version": PROMPT_VERSIONS["reasons"],
        "results": [{
            "group_id": "g1", "decision": "assign", "code_numbers": [expected_code],
            "ordered_ideas": [mention], "evidence": mention,
            "ambiguity_reason": None, "confidence": 0.8,
        }],
    })
    codebook = [
        {"code_number": 19, "label": "Vitaminas", "net": "Nutrientes"},
        {"code_number": 20, "label": "Proteína", "net": "Nutrientes"},
    ]
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        result = classify_batch(codebook, [{"id": "g1", "text": mention}], "reasons")
    assert result[0]["code_numbers"] == [expected_code]


def test_classify_batch_abstains_on_opposite_valence_instead_of_forcing_positive_code():
    """'mal sabor' contra un codebook que solo tiene 'Buen sabor' debe quedar
    pendiente ([]), no forzado dentro del código de valencia contraria."""
    response = FakeResponse({
        "prompt_version": PROMPT_VERSIONS["reasons"],
        "results": [{
            "group_id": "g1", "decision": "abstain", "code_numbers": [],
            "ordered_ideas": [], "evidence": "mal sabor",
            "ambiguity_reason": "sentido opuesto al único código de sabor disponible",
            "confidence": 0.3,
        }],
    })
    codebook = [{"code_number": 12, "label": "Buen sabor", "net": "Sabor"}]
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        result = classify_batch(codebook, [{"id": "g1", "text": "mal sabor"}], "reasons")
    assert result[0]["code_numbers"] == []


def test_classify_batch_still_allows_97_for_non_thematic_vague_mention():
    """'bueno'/'lactosa' sin tema propio en el codebook siguen cayendo a 97: la
    regla nueva solo evita 97 cuando SÍ comparte tema con un net existente."""
    response = FakeResponse({
        "prompt_version": PROMPT_VERSIONS["reasons"],
        "results": [{
            "group_id": "g1", "decision": "assign", "code_numbers": [97],
            "ordered_ideas": ["bueno"], "evidence": "bueno",
            "ambiguity_reason": None, "confidence": 0.6,
        }],
    })
    codebook = [
        {"code_number": 19, "label": "Que sea nutritiva", "net": "Vitaminas"},
        {"code_number": 97, "label": "Otras menciones", "net": None},
    ]
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        result = classify_batch(codebook, [{"id": "g1", "text": "bueno"}], "reasons")
    assert result[0]["code_numbers"] == [97]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self.payload)}}]}


def test_deepseek_contract_rejects_missing_or_unknown_group_ids():
    response = FakeResponse({
        "prompt_version": PROMPT_VERSIONS["brands"],
        "results": [{
            "group_id": "unknown", "decision": "abstain", "code_numbers": [],
            "ordered_ideas": [], "evidence": "", "ambiguity_reason": "dudoso",
            "confidence": 0.2,
        }],
    })
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        with pytest.raises(ValueError, match="group_id"):
            classify_batch(
                [{"code_number": 1, "label": "Alpina"}],
                [{"id": "expected", "text": "x"}], "brands",
            )


def test_deepseek_contract_rejects_nonexistent_code():
    response = FakeResponse({
        "prompt_version": PROMPT_VERSIONS["reasons"],
        "results": [{
            "group_id": "g1", "decision": "assign", "code_numbers": [9999],
            "ordered_ideas": ["precio"], "evidence": "barato",
            "ambiguity_reason": None, "confidence": 0.9,
        }],
    })
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        with pytest.raises(ValueError, match="inexistente"):
            classify_batch(
                [{"code_number": 1, "label": "Precio"}],
                [{"id": "g1", "text": "barato"}], "reasons",
            )


def test_single_code_contract_keeps_first_ordered_code():
    response = FakeResponse({
        "prompt_version": PROMPT_VERSIONS["reasons"],
        "results": [{
            "group_id": "g1", "decision": "assign", "code_numbers": [1, 2],
            "ordered_ideas": ["sabor", "precio"], "evidence": "rico y barato",
            "ambiguity_reason": None, "confidence": 0.8,
        }],
    })
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        result = classify_batch(
            [{"code_number": 1, "label": "Sabor"}, {"code_number": 2, "label": "Precio"}],
            [{"id": "g1", "text": "rico y barato"}], "reasons",
            {"single_code_per_response": True},
        )
    assert result[0]["code_numbers"] == [1]


def test_residual_decision_coerces_non_string_ordered_ideas():
    response = FakeResponse({
        "prompt_version": PROMPT_VERSIONS["brands"],
        "results": [{
            "group_id": "g1",
            "decision": "assign",
            "code_numbers": [1],
            "ordered_ideas": [97, {"code_number": 1, "position": 0}],
            "evidence": "bonle",
            "ambiguity_reason": None,
            "confidence": 0.7,
        }],
    })
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        result = classify_batch(
            [{"code_number": 1, "label": "Bonlé"}],
            [{"id": "g1", "text": "bonle"}], "brands",
        )
    assert result[0]["ordered_ideas"] == ["97", "1"]


def test_reason_codebook_proposal_returns_rich_reviewable_contract():
    response = FakeResponse({
        "prompt_version": "reason_codebook_proposal-v1",
        "results": [{
            "index": 0,
            "net": "Experiencia sensorial",
            "label": "Buen sabor",
            "definition": "Evaluación positiva del sabor.",
            "inclusion_criteria": ["Expresa agrado por el sabor"],
            "exclusion_criteria": ["Habla solo del precio"],
            "examples": ["Es rico"],
        }],
    })
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        proposals = propose_reason_codes(["Representante: es rico"], {"study": "LECHES"})

    assert proposals[0]["net"] == "Experiencia sensorial"
    assert proposals[0]["inclusion_criteria"] == ["Expresa agrado por el sabor"]


def test_reason_codebook_proposal_rejects_duplicate_indices():
    proposal = {
        "index": 0,
        "net": "Sensorial",
        "label": "Sabor",
        "definition": "Habla del sabor.",
        "inclusion_criteria": ["Sabor"],
        "exclusion_criteria": ["Precio"],
        "examples": ["Rico"],
    }
    response = FakeResponse({
        "prompt_version": "reason_codebook_proposal-v1",
        "results": [proposal, proposal],
    })
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        with pytest.raises(ValueError, match="índices"):
            propose_reason_codes(["cluster 0", "cluster 1"])


def test_brand_canonicalization_is_structured_and_category_aware():
    response = FakeResponse({
        "prompt_version": "brand_canonicalization-v1",
        "results": [{
            "index": 0,
            "label": "Bonlé",
            "category_fit": "fits",
            "rationale": "Las variantes corresponden a la misma marca de la categoría.",
        }],
    })
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        proposals = propose_brand_codes(["Bonle; bomle"], {"product_category": "Leches"})

    assert proposals == [{
        "index": 0,
        "label": "Bonlé",
        "category_fit": "fits",
        "rationale": "Las variantes corresponden a la misma marca de la categoría.",
    }]


def test_brand_canonicalization_accepts_bare_results_list():
    """DeepSeek a veces devuelve `[{...}]` en vez del envelope con prompt_version."""
    response = FakeResponse([{
        "index": 0,
        "label": "Bonlé",
        "category_fit": "fits",
        "rationale": "Misma marca de la categoría.",
    }])
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        proposals = propose_brand_codes(["Bonle; bomle"], {"product_category": "Leches"})

    assert proposals[0]["label"] == "Bonlé"
    assert proposals[0]["category_fit"] == "fits"


def test_reason_codebook_proposal_accepts_bare_results_list():
    response = FakeResponse([{
        "index": 0,
        "net": "Experiencia sensorial",
        "label": "Sabor agradable",
        "definition": "Expresa agrado por el sabor.",
        "inclusion_criteria": ["Expresa agrado por el sabor"],
        "exclusion_criteria": ["Habla solo de precio"],
        "examples": ["es rico"],
    }])
    with patch("app.pipeline.llm.client.requests.post", return_value=response):
        proposals = propose_reason_codes(["Representante: es rico"], {"study": "LECHES"})

    assert proposals[0]["net"] == "Experiencia sensorial"

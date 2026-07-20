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

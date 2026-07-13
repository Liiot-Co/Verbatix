from app.pipeline.llm.client import _build_prompt


def test_brands_prompt_forbids_97_for_real_uncatalogued_brands():
    prompt = _build_prompt(codebook=[{"code_number": 1, "label": "Alpina", "net": None}], verbatims=[], coding_type="brands")
    assert "NO uses 97" in prompt


def test_reasons_prompt_keeps_permissive_97_rule():
    prompt = _build_prompt(codebook=[{"code_number": 1, "label": "Buena textura", "net": None}], verbatims=[], coding_type="reasons")
    assert "NO uses 97" not in prompt
    assert "Usa 97 (otras menciones) solo cuando" in prompt

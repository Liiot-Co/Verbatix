from app.pipeline.fuzzy.models import CodeAlias
from app.pipeline.fuzzy.scoring import best_brand_candidate


CATALOG = [
    CodeAlias(code_id="bonle", alias_normalized="bonle"),
    CodeAlias(code_id="gloria", alias_normalized="gloria"),
    CodeAlias(code_id="aro", alias_normalized="aro"),
    CodeAlias(code_id="uno", alias_normalized="uno"),
]


def test_bone_does_not_become_bonle():
    assert best_brand_candidate("bone", CATALOG) is None


def test_bomle_recovers_bonle_as_suggestion():
    candidate = best_brand_candidate("bomle", CATALOG)
    assert candidate is not None
    assert candidate.code_id == "bonle"


def test_substring_false_positives_are_blocked():
    assert best_brand_candidate("huarochirano", CATALOG) is None
    assert best_brand_candidate("queso de puno", CATALOG) is None


def test_typo_can_recover_gloria_without_authorizing_autoclose():
    candidate = best_brand_candidate("glorai", CATALOG)
    assert candidate is not None
    assert candidate.code_id == "gloria"

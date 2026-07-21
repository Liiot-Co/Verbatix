from app.pipeline.fuzzy.models import CodeAlias
from app.pipeline.fuzzy.scoring import (
    best_brand_candidate,
    is_safe_brand_autocommit,
)


CATALOG = [
    CodeAlias(code_id="bonle", alias_normalized="bonle"),
    CodeAlias(code_id="gloria", alias_normalized="gloria"),
    CodeAlias(code_id="aro", alias_normalized="aro"),
    CodeAlias(code_id="uno", alias_normalized="uno"),
]


def test_bone_does_not_become_bonle():
    assert best_brand_candidate("bone", CATALOG) is None


def test_short_terminal_keyboard_typo_recovers_edam_safely():
    candidate = best_brand_candidate(
        "edan",
        [CodeAlias(code_id="edam", alias_normalized="edam")],
    )
    assert candidate is not None
    assert candidate.code_id == "edam"
    assert is_safe_brand_autocommit(
        "edan",
        candidate,
        score_threshold=82.0,
        margin_threshold=5.0,
    ) is True


def test_other_short_edits_do_not_bypass_short_brand_protection():
    catalog = [CodeAlias(code_id="edar", alias_normalized="edar")]
    assert best_brand_candidate("edan", catalog) is None


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


def test_single_word_typo_scores_above_autocommit_band():
    # Regresión: el peso fijo de token_jaccard (0.12) capaba el score de un typo
    # de marca de UNA palabra en 88 — justo el gate de auto-cierre —, así que
    # jamás se auto-cerraba. Redistribuido ese peso, un typo claro supera 82.
    candidate = best_brand_candidate(
        "schugur", [CodeAlias(code_id="chugur", alias_normalized="chugur")]
    )
    assert candidate is not None
    assert candidate.code_id == "chugur"
    assert candidate.score >= 82.0


def _safe_autocommit(
    value: str,
    alias: str,
    *,
    used_stripped_form: bool = False,
) -> bool:
    candidate = best_brand_candidate(
        value.strip().removeprefix("el "),
        [CodeAlias(code_id=alias, alias_normalized=alias)],
    )
    assert candidate is not None
    return is_safe_brand_autocommit(
        value,
        candidate,
        score_threshold=82.0,
        margin_threshold=5.0,
        used_stripped_form=used_stripped_form,
    )


def test_low_score_single_token_typos_can_autocommit_when_orthographically_safe():
    assert _safe_autocommit("braetted", "braed") is True
    assert _safe_autocommit("filadelfia", "philadelfia") is True
    assert _safe_autocommit("pfiladelfia", "philadelfia") is True


def test_generic_single_edit_below_score_gate_stays_suggested():
    # El histórico contradice "breat" (95 y Braedt). Una sola edición genérica
    # no alcanza para saltarse el umbral calibrado de autocierre.
    assert _safe_autocommit("breat", "bredt") is False


def test_low_score_multiword_candidate_never_autocommits_after_article_stripping():
    # El motor evalúa también "artesano", pero la política debe conservar el
    # texto original para no cerrar "el artesano" como "parmesano".
    assert _safe_autocommit(
        "el artesano",
        "parmesano",
        used_stripped_form=True,
    ) is False
    assert _safe_autocommit(
        "el glorai",
        "gloria",
        used_stripped_form=True,
    ) is False


def test_low_score_single_token_needs_more_than_generic_edit_similarity():
    # Incluso sin artículo, compartir un sufijo no basta para auto-cerrar.
    assert _safe_autocommit("artesano", "parmesano") is False

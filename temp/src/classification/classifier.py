"""C2 — Classification engine (OWNER: cursor).

Labels a survey answer against the approved catalog:

    normalize -> alias-exact match -> rapidfuzz fuzzy fallback -> unknown

Decision thresholds (from "Marketing Classification.md" §21):

    fuzzy_auto   = 95   # >= this score -> auto_accepted
    fuzzy_review = 88   # >= this score (but < auto) -> needs_review

Output statuses: auto_accepted, needs_review, unknown.

The text normalizer here is intentionally self-contained so the classifier
does not depend on the discovery lane (``src/discovery/*``); both lanes apply
the same cleaning rules (lowercase, strip accents/punct, collapse spaces).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping, Optional

FUZZY_AUTO = 95
FUZZY_REVIEW = 88

_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_SPACES = re.compile(r"\s+")

try:  # rapidfuzz is the production matcher; difflib keeps the lane runnable without deps.
    from rapidfuzz import fuzz as _rf_fuzz

    def _ratio(a: str, b: str) -> float:
        return float(_rf_fuzz.token_set_ratio(a, b))

    _MATCHER = "rapidfuzz"
except ImportError:  # pragma: no cover - exercised only without rapidfuzz installed
    from difflib import SequenceMatcher

    def _ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100.0

    _MATCHER = "difflib"


def normalize_text(text: str) -> str:
    """Lowercase, strip accents, drop punctuation, collapse whitespace."""
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


@dataclass(frozen=True)
class Match:
    product: Optional[str]
    method: str          # alias_exact | fuzzy | unknown
    confidence: float    # 0..1
    status: str          # auto_accepted | needs_review | unknown
    alias: Optional[str] = None


class Classifier:
    """Classify answers against an ``alias -> product`` catalog."""

    def __init__(
        self,
        alias_map: Mapping[str, str],
        *,
        fuzzy_auto: int = FUZZY_AUTO,
        fuzzy_review: int = FUZZY_REVIEW,
    ) -> None:
        # Normalize aliases once so matching is accent/case insensitive.
        self._aliases: dict[str, str] = {}
        for alias, product in alias_map.items():
            norm = normalize_text(alias)
            if norm:
                self._aliases[norm] = product
        self.fuzzy_auto = fuzzy_auto
        self.fuzzy_review = fuzzy_review

    @property
    def matcher(self) -> str:
        return _MATCHER

    def classify(self, response: str) -> Match:
        clean = normalize_text(response)
        if not clean:
            return Match(None, "unknown", 0.0, "unknown")

        exact = self._alias_exact(clean)
        if exact is not None:
            alias, product = exact
            return Match(product, "alias_exact", 1.0, "auto_accepted", alias)

        return self._fuzzy(clean)

    # -- internals ----------------------------------------------------------
    def _alias_exact(self, clean: str) -> Optional[tuple[str, str]]:
        # Whole-word containment so "amazon" matches "compro en amazon" but
        # not "amazonas".
        padded = f" {clean} "
        best: Optional[tuple[str, str]] = None
        for alias, product in self._aliases.items():
            if f" {alias} " in padded:
                # Prefer the longest alias (more specific match).
                if best is None or len(alias) > len(best[0]):
                    best = (alias, product)
        return best

    def _fuzzy(self, clean: str) -> Match:
        best_alias: Optional[str] = None
        best_product: Optional[str] = None
        best_score = 0.0
        for alias, product in self._aliases.items():
            score = _ratio(clean, alias)
            if score > best_score:
                best_score, best_alias, best_product = score, alias, product

        if best_alias is None or best_score < self.fuzzy_review:
            return Match(None, "unknown", round(best_score / 100.0, 3), "needs_review")

        status = "auto_accepted" if best_score >= self.fuzzy_auto else "needs_review"
        return Match(
            best_product, "fuzzy", round(best_score / 100.0, 3), status, best_alias
        )

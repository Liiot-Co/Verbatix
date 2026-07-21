"""Public exports for pipeline.fuzzy (fuzzy puro, sin I/O)."""

from .catalog import (
    discover_catalog_from_frequency,
    discover_new_brands,
    load_catalog_aliases,
)
from .models import SCORE_THRESHOLD, CodeAlias, Cols
from .service import MatchResult, run_fuzzy_matching

__all__ = [
    "CodeAlias",
    "Cols",
    "MatchResult",
    "SCORE_THRESHOLD",
    "discover_catalog_from_frequency",
    "discover_new_brands",
    "load_catalog_aliases",
    "run_fuzzy_matching",
]

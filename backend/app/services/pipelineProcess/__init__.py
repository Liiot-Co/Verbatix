"""Public exports for pipelineProcess (fuzzy puro, sin I/O)."""

from .models import SCORE_THRESHOLD, CodeAlias, Cols
from .service import MatchResult, run_fuzzy_matching

__all__ = [
    "CodeAlias",
    "Cols",
    "MatchResult",
    "SCORE_THRESHOLD",
    "run_fuzzy_matching",
]

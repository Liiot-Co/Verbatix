"""Classification engine (OWNER: cursor).

Labels survey answers against the approved catalog: alias-exact matching
first, then rapidfuzz fuzzy matching, falling back to needs_review.

Modules (to be implemented per .knogg/plans/master_plan.yml):
    classifier.py  C2  normalize -> alias-exact -> fuzzy -> status assignment
"""

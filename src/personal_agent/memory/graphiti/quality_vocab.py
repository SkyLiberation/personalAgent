"""Weak-relation vocabulary for graph extraction quality checks.

A relation fact is "weak" when it conveys no meaningful semantic connection
between entities — e.g. "相关", "has", "涉及". These are the graph equivalent
of stop-words: they inflate edge count without adding reasoning value.

The vocabulary is intentionally small and conservative. False negatives
(missing a weak term) are acceptable; false positives (flagging a meaningful
relation as weak) are not.
"""
from __future__ import annotations

WEAK_RELATION_TERMS: frozenset[str] = frozenset({
    # Chinese
    "相关", "有关", "涉及", "关联", "属于", "包含", "有",
    "是", "存在", "对应", "联系", "关于",
    # English
    "related to", "associated with", "involves", "has",
    "is", "belongs to", "contains", "corresponds to",
    "relates to", "pertains to", "concerns",
})

_MAX_WEAK_FACT_LEN = 12


def is_weak_relation(fact: str) -> bool:
    """Check if a relation fact is semantically weak/generic."""
    normalized = fact.strip().lower()
    if not normalized:
        return True
    if normalized in WEAK_RELATION_TERMS:
        return True
    if len(normalized) <= _MAX_WEAK_FACT_LEN:
        for term in WEAK_RELATION_TERMS:
            if normalized == term:
                return True
    return False


def all_relations_weak(relation_facts: list[str]) -> bool:
    """Return True if the list is non-empty and every relation is weak."""
    if not relation_facts:
        return False
    return all(is_weak_relation(f) for f in relation_facts)

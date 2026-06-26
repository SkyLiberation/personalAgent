"""Pure metrics for the tool governance golden set."""

from __future__ import annotations

from collections.abc import Iterable


def scalar_exact(actual: object, expected: object) -> float:
    return 1.0 if actual == expected else 0.0


def side_effects_exact(actual: Iterable[str], expected: Iterable[str]) -> float:
    return 1.0 if sorted(actual) == sorted(expected) else 0.0


def nullable_scalar_exact(actual: object, expected: object) -> float:
    return 1.0 if actual == expected else 0.0

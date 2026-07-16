"""Canonical resource/capability matching value objects."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict


MUTATING_OPERATIONS = frozenset({"create", "update", "delete", "ingest", "repair"})


def mutating_operations(operations: Iterable[object]) -> tuple[str, ...]:
    """Return the canonical, ordered mutation subset of an operation collection."""
    return tuple(dict.fromkeys(
        str(operation)
        for operation in operations
        if str(operation) in MUTATING_OPERATIONS
    ))


class ResourceSelector(BaseModel):
    model_config = ConfigDict(frozen=True)

    semantic_domains: frozenset[str] = frozenset()
    resource_types: frozenset[str] = frozenset()
    locator: str | None = None


class OperationScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    operations: frozenset[str] = frozenset()
    side_effect_class: str = "none"


class ProviderConstraint(BaseModel):
    model_config = ConfigDict(frozen=True)

    required: frozenset[str] = frozenset()
    preferred: tuple[str, ...] = ()
    freshness_required: bool = False
    minimum_trust: str = "external"


class ResourceMatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["matched", "not_matched"]
    rejected_dimensions: tuple[str, ...] = ()


def match_resource_contract(
    required_selector: ResourceSelector,
    required_operations: OperationScope,
    required_provider: ProviderConstraint,
    candidate_selector: ResourceSelector,
    candidate_operations: OperationScope,
    *,
    candidate_provider: str,
) -> ResourceMatchResult:
    rejected: list[str] = []
    if required_provider.required and candidate_provider not in required_provider.required:
        rejected.append("provider")
    if (
        required_selector.semantic_domains
        and not required_selector.semantic_domains.intersection(candidate_selector.semantic_domains)
    ):
        rejected.append("semantic_domain")
    if (
        required_selector.resource_types
        and not required_selector.resource_types.intersection(candidate_selector.resource_types)
    ):
        rejected.append("resource_type")
    if (
        required_operations.operations
        and not required_operations.operations.intersection(candidate_operations.operations)
    ):
        rejected.append("operation")
    return ResourceMatchResult(
        status="not_matched" if rejected else "matched",
        rejected_dimensions=tuple(rejected),
    )


__all__ = [
    "MUTATING_OPERATIONS", "OperationScope", "ProviderConstraint", "ResourceMatchResult",
    "ResourceSelector", "match_resource_contract", "mutating_operations",
]

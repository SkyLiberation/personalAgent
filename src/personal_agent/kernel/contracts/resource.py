"""Canonical resource/capability matching value objects."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


class ResourceRef(BaseModel):
    """Application-owned identity passed across capability boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    owner: AuthenticatedPrincipal
    revision: int = Field(default=1, ge=1)


class ResourceEvidenceRef(BaseModel):
    """Stable citation identity derived from an inspected Resource revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_ref: str = Field(min_length=1)
    resource_ref: ResourceRef
    locator: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)


class GeneratedArtifactContent(BaseModel):
    """Typed content materialized through the canonical Artifact owner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    content_digest: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


MUTATING_OPERATIONS = frozenset({"create", "update", "delete", "ingest", "repair"})

# These effects observe or transport data but do not, by themselves, mutate a
# resource represented by ResourceAccess.write_set. Unknown effect classes stay
# fail-closed because the scheduler cannot prove that no write target is needed.
NON_WRITING_SIDE_EFFECT_CLASSES = frozenset({
    "none",
    "read_local",
    "read_longterm",
    "external_network",
})


def mutating_operations(operations: Iterable[object]) -> tuple[str, ...]:
    """Return the canonical, ordered mutation subset of an operation collection."""
    return tuple(dict.fromkeys(
        str(operation)
        for operation in operations
        if str(operation) in MUTATING_OPERATIONS
    ))


def side_effect_requires_write_set(side_effect_class: str) -> bool:
    """Return whether physical dispatch requires a resolved write target."""
    return side_effect_class not in NON_WRITING_SIDE_EFFECT_CLASSES


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
    "MUTATING_OPERATIONS", "NON_WRITING_SIDE_EFFECT_CLASSES", "OperationScope",
    "GeneratedArtifactContent", "ProviderConstraint", "ResourceMatchResult",
    "ResourceEvidenceRef", "ResourceRef", "ResourceSelector", "match_resource_contract",
    "mutating_operations", "side_effect_requires_write_set",
]

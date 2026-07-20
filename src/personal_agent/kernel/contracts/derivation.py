"""Typed, replayable records for closed-world deterministic derivations."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def canonical_digest(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


class DerivationInvariantResults(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_target_mapping: Literal["passed", "not_applicable"] = "not_applicable"
    scope_subset: Literal["passed", "not_applicable"] = "not_applicable"
    route_uniqueness: Literal["passed", "not_applicable"] = "not_applicable"
    provider_equivalence: Literal["passed", "not_applicable"] = "not_applicable"
    authorization_projection_preserved: Literal["passed", "not_applicable"] = "not_applicable"


class DerivationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    derivation_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    derivation_kind: Literal[
        "command_resolution", "route_resolution", "provider_binding",
        "frontier_projection", "coordination_mode",
    ]
    source_contract_refs: tuple[str, ...]
    rule_id: str
    rule_version: str
    policy_snapshot_ref: str
    input_fact_refs: tuple[str, ...] = ()
    source_digests: tuple[str, ...]
    output_ref: str
    output_digest: str
    invariant_results: DerivationInvariantResults
    uniqueness_kind: Literal[
        "single_policy_allowed_route", "single_exact_identifier_match",
        "single_active_equivalent_provider", "single_ready_frontier_after_constraints",
        "not_applicable",
    ] = "not_applicable"


__all__ = [
    "DerivationInvariantResults", "DerivationRecord", "canonical_digest",
]

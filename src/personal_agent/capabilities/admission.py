"""Deterministic validation for capability resolutions.

The resolver may rank candidates, but this module owns the non-negotiable
scope, metadata, and policy invariants before a resolution reaches execution.
"""

from __future__ import annotations

from personal_agent.capabilities.contracts.execution import (
    Capability,
    ExecutionCapabilityRequest,
    DeniedCapability,
)
from personal_agent.kernel.contracts.resource import MUTATING_OPERATIONS, match_resource_contract


class ResolutionValidator:
    """Validate an admitted resolution against its immutable action request."""

    def errors(
        self,
        request: ExecutionCapabilityRequest,
        selected: Capability | None,
        denials: tuple[DeniedCapability, ...],
        *,
        hard_denied_ids: frozenset[str] = frozenset(),
    ) -> tuple[str, ...]:
        errors: list[str] = []
        denied_ids = {capability.capability_id for capability in denials}
        if selected is not None and selected.capability_id in denied_ids:
            errors.append("selected_denied_overlap")

        allowed_kinds = set(request.allowed_kinds)
        allowed_operations = set(request.allowed_operations)
        for capability in ((selected,) if selected is not None else ()):
            errors.extend(self._capability_errors(
                capability,
                allowed_kinds=allowed_kinds,
                allowed_operations=allowed_operations,
                hard_denied_ids=hard_denied_ids,
                require_reviewed_metadata=request.policy.require_reviewed_metadata_for_high_risk,
            ))
            if request.requirements and not any(
                _matches_requirement(capability, requirement)
                for requirement in request.requirements
            ):
                errors.append(f"requirement_outside_scope:{capability.capability_id}")
            if request.policy.read_only and set(capability.operations) & MUTATING_OPERATIONS:
                errors.append(f"write_outside_read_only:{capability.capability_id}")
        return tuple(dict.fromkeys(errors))

    @staticmethod
    def _capability_errors(
        capability: Capability,
        *,
        allowed_kinds: set[str],
        allowed_operations: set[str],
        hard_denied_ids: frozenset[str],
        require_reviewed_metadata: bool,
    ) -> list[str]:
        errors: list[str] = []
        if capability.kind not in allowed_kinds:
            errors.append(f"kind_outside_scope:{capability.capability_id}")
        if allowed_operations and not set(capability.operations).intersection(allowed_operations):
            errors.append(f"operation_outside_scope:{capability.capability_id}")
        if capability.capability_id in hard_denied_ids:
            errors.append(f"policy_hard_denied:{capability.capability_id}")
        if require_reviewed_metadata and _is_high_risk(capability):
            if capability.metadata_source not in {"system", "human_reviewed"}:
                errors.append(f"unreviewed_high_risk_metadata:{capability.capability_id}")
        return errors


def _is_high_risk(capability: Capability) -> bool:
    return (
        capability.risk_level == "high"
        or capability.data_egress_class == "sensitive"
        or any(effect != "none" and ("write" in effect or "delete" in effect) for effect in capability.side_effects)
        or any(operation in {"create", "update", "delete"} for operation in capability.operations)
    )


def _matches_requirement(capability: Capability, requirement) -> bool:
    return match_resource_contract(
        requirement.selector,
        requirement.operation_scope,
        requirement.provider_constraint,
        capability.selector,
        capability.operation_scope,
        candidate_provider=capability.provider,
    ).status == "matched"


__all__ = ["ResolutionValidator"]

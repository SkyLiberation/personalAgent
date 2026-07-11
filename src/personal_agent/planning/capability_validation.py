"""Deterministic validation for capability resolutions.

The resolver may rank candidates, but this module owns the non-negotiable
scope, metadata, and policy invariants before a resolution reaches execution.
"""

from __future__ import annotations

from personal_agent.kernel.contracts.capability import (
    Capability,
    CapabilityResolution,
    CapabilityResolutionRequest,
)


class ResolutionValidator:
    """Validate an admitted resolution against its immutable step request."""

    def errors(
        self,
        request: CapabilityResolutionRequest,
        resolution: CapabilityResolution,
        *,
        hard_denied_ids: frozenset[str] = frozenset(),
    ) -> tuple[str, ...]:
        errors: list[str] = []
        if resolution.request.scope_id != request.scope_id:
            errors.append("scope_id_changed")
        if resolution.request.workflow_id != request.workflow_id:
            errors.append("workflow_id_changed")
        if resolution.request.step_id != request.step_id:
            errors.append("step_id_changed")
        if resolution.request.step_action_type != request.step_action_type:
            errors.append("step_action_type_changed")

        selected_ids = {capability.capability_id for capability in resolution.selected_capabilities}
        denied_ids = {capability.capability_id for capability in resolution.denied_capabilities}
        if selected_ids & denied_ids:
            errors.append("selected_denied_overlap")

        allowed_kinds = set(request.allowed_kinds)
        allowed_operations = set(request.allowed_operations)
        for capability in resolution.selected_capabilities:
            errors.extend(self._capability_errors(
                capability,
                allowed_kinds=allowed_kinds,
                allowed_operations=allowed_operations,
                hard_denied_ids=hard_denied_ids,
                require_reviewed_metadata=request.policy.require_reviewed_metadata_for_high_risk,
            ))
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
        if not set(capability.operations).issubset(allowed_operations):
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


__all__ = ["ResolutionValidator"]

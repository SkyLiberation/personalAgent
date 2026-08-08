from __future__ import annotations

import pytest

from personal_agent.capabilities.contracts.execution import (
    Capability,
    CapabilityEquivalenceClass,
    CapabilityRequirement,
    CapabilityRuntimeContext,
    ExecutionCapabilityRequest,
)
from personal_agent.capabilities.portfolio import CapabilityPortfolio
from personal_agent.capabilities.resolver import CapabilityResolver


def _capability(capability_id: str, **updates: object) -> Capability:
    values: dict[str, object] = {
        "capability_id": capability_id,
        "kind": "mcp_tool",
        "provider": capability_id,
        "local_name": capability_id,
        "semantic_domains": ("knowledge",),
        "resource_types": ("text",),
        "operations": ("read",),
        "side_effects": ("none",),
        "output_contract": "EvidenceItem",
        "auth_scope": "knowledge:read",
        "trust_level": "trusted",
        "credential_mode": "none",
        "data_egress_class": "none",
        "attestation_status": "verified",
        "freshness_profile": "realtime",
        "evidence_contract": "provider_output",
        "failure_semantics": "return_typed_failure",
        "metadata_source": "system",
        "provider_priority": 1,
    }
    values.update(updates)
    return Capability.from_dimensions(**values)


def _equivalence() -> CapabilityEquivalenceClass:
    return CapabilityEquivalenceClass(
        required_output_contract="EvidenceItem",
        allowed_side_effect_class="none",
        authority_scope="knowledge:read",
        trust_floor="scoped",
        freshness_contract="fresh",
        evidence_contract="provider_output",
        data_egress_class="none",
        failure_semantics="return_typed_failure",
    )


def _request(equivalence: CapabilityEquivalenceClass | None = None) -> ExecutionCapabilityRequest:
    return ExecutionCapabilityRequest(
        task_id="resolver-gate",
        goal_id="goal-1",
        action_id="action-1",
        execution_intent="read",
        allowed_operations=("read",),
        requirements=(CapabilityRequirement.from_dimensions(
            requirement_id="read-knowledge",
            purpose="read governed knowledge",
            semantic_domains=("knowledge",),
            resource_types=("text",),
            operations=("read",),
            output_contract="EvidenceItem",
        ),),
        runtime_context=CapabilityRuntimeContext(
            equivalence_class=equivalence or _equivalence(),
        ),
    )


@pytest.mark.parametrize(
    ("updates", "mismatch"),
    [
        ({"output_contract": "ToolResult"}, "required_output_contract"),
        ({"side_effects": ("external_network",)}, "side_effect_class"),
        ({"auth_scope": "knowledge:read"}, "authority_scope"),
        ({"data_egress_class": "content"}, "data_egress_class"),
        ({"evidence_contract": "unverified_text"}, "evidence_contract"),
        ({"failure_semantics": "raise_untyped_error"}, "failure_semantics"),
        ({"trust_level": "external"}, "trust_floor"),
        ({"freshness_profile": "static"}, "freshness_contract"),
    ],
)
def test_any_equivalence_dimension_mismatch_is_a_hard_denial(
    updates: dict[str, object],
    mismatch: str,
) -> None:
    candidate = _capability("candidate", **updates)

    result = CapabilityResolver(CapabilityPortfolio((candidate,))).resolve(_request())

    assert result.selected_definition is None
    assert any(
        item.capability_id == candidate.capability_id
        and item.reason == f"equivalence_mismatch:{mismatch}"
        for item in result.denials
    )


def test_ranking_only_optimizes_within_one_equivalence_class() -> None:
    lower_priority = _capability("equivalent-a", provider_priority=10)
    higher_priority = _capability("equivalent-b", provider_priority=1)
    semantic_mismatch = _capability(
        "different-output",
        output_contract="ToolResult",
        provider_priority=1000,
    )

    result = CapabilityResolver(CapabilityPortfolio((
        lower_priority,
        higher_priority,
        semantic_mismatch,
    ))).resolve(_request())

    assert result.selected_definition is not None
    assert result.selected_definition.capability_id in {
        lower_priority.capability_id,
        higher_priority.capability_id,
    }
    assert result.selected_definition.capability_id != semantic_mismatch.capability_id
    assert any(
        item.capability_id == semantic_mismatch.capability_id
        and item.reason == "equivalence_mismatch:required_output_contract"
        for item in result.denials
    )
    assert result.decision.derivation_record.invariant_results.provider_equivalence == "passed"

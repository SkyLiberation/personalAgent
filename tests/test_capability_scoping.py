from __future__ import annotations

from datetime import UTC, datetime

from personal_agent.capabilities.contracts.execution import (
    Capability,
    CapabilityRequirement,
    ExecutionCapabilityRequest,
    CapabilitySelectionPolicy,
    EvidenceSourceCapability,
)
from personal_agent.capabilities.admission import ResolutionValidator
from personal_agent.capabilities.resolver import CapabilityResolver
from personal_agent.capabilities.outcomes import OutcomeAwareCapabilityRanker
from personal_agent.capabilities.contracts.outcomes import (
    CapabilityEffectivenessEvent,
    CapabilityExecutionOutcomeEvent,
)
from personal_agent.capabilities.portfolio import CapabilityPortfolio, ExecutionCapabilityAvailability


def _request(
    *,
    requirement: CapabilityRequirement,
    kinds=("mcp_tool",),
    operations=("search", "read"),
    policy: CapabilitySelectionPolicy | None = None,
) -> ExecutionCapabilityRequest:
    return ExecutionCapabilityRequest(
        task_id="task-1",
        goal_id="goal-1",
        action_id="action-1",
        execution_intent="acquire",
        allowed_kinds=kinds,
        allowed_operations=operations,
        requirements=(requirement,),
        policy=policy or CapabilitySelectionPolicy(),
    )


def test_resolver_rejects_kind_outside_action_scope():
    resolver = CapabilityResolver(CapabilityPortfolio((
        _capability("retriever:local", kind="retriever", provider="local", local_name="local"),
        _capability(
            "tool:capture_text",
            kind="local_tool",
            provider="internal",
            local_name="capture_text",
            operations=("create",),
        ),
    )))
    requirement = CapabilityRequirement.from_dimensions(
        requirement_id="evidence",
        purpose="retrieve notes",
        semantic_domains=("local_memory",),
        operations=("search", "read"),
    )

    resolution = resolver.resolve(_request(
        requirement=requirement,
        kinds=("retriever",),
        policy=CapabilitySelectionPolicy(max_providers_per_action=4),
    ))

    assert resolution.selected_definition.local_name == "local"
    assert any(
        denied.capability_id == "tool:capture_text" and denied.reason == "kind_not_allowed"
        for denied in resolution.denials
    )


def test_local_first_is_explicit_policy_not_text_classification():
    resolver = CapabilityResolver(CapabilityPortfolio((
        _capability("retriever:local", kind="retriever", provider="local", local_name="local"),
        _capability(
            "retriever:web",
            kind="retriever",
            provider="web",
            local_name="web",
            side_effects=("external_network",),
        ),
    )))
    requirement = CapabilityRequirement.from_dimensions(
        requirement_id="evidence",
        purpose="retrieve evidence",
        operations=("search", "read"),
    )

    resolution = resolver.resolve(_request(
        requirement=requirement,
        kinds=("retriever",),
        policy=CapabilitySelectionPolicy(
            local_first=True,
            max_providers_per_action=4,
        ),
    ))

    assert resolution.selected_definition.local_name == "local"
    assert any(item.local_name == "web" and item.reason == "local_first" for item in resolution.denials)


def test_read_only_action_rejects_write_capability():
    resolver = CapabilityResolver(CapabilityPortfolio((
        _capability(
            "mcp:github:get_file_contents",
            kind="mcp_tool",
            provider="github",
            local_name="github.get_file_contents",
            operations=("read",),
        ),
        _capability(
            "mcp:github:create_issue",
            kind="mcp_tool",
            provider="github",
            local_name="github.create_issue",
            operations=("create",),
        ),
    )))
    requirement = CapabilityRequirement.from_dimensions(
        requirement_id="repository",
        purpose="read repository content",
        semantic_domains=("codebase",),
        resource_types=("repository", "file"),
        operations=("read",),
        required_providers=("github",),
    )

    resolution = resolver.resolve(_request(
        requirement=requirement,
        operations=("read",),
        policy=CapabilitySelectionPolicy(
            read_only=True,
            preferred_providers=("github",),
            max_providers_per_action=1,
        ),
    ))

    assert resolution.selected_definition.local_name == "github.get_file_contents"
    assert any(
        denied.local_name == "github.create_issue"
        and denied.reason == "requirement_mismatch"
        for denied in resolution.denials
    )


def test_unreviewed_high_risk_capability_is_rejected_before_execution():
    capability = _capability(
        "mcp:github:create_issue",
        kind="mcp_tool",
        provider="github",
        local_name="github.create_issue",
        operations=("create",),
    ).model_copy(update={"metadata_source": "provider", "attestation_status": "self_claimed"})
    portfolio = CapabilityPortfolio((capability,))
    portfolio.observe(ExecutionCapabilityAvailability(
        capability_ref=capability.capability_id,
        availability_revision=1,
        status="available",
        credential_ready=True,
        health_observed_at=datetime.now(UTC),
        provider_binding_revision=1,
    ))
    resolver = CapabilityResolver(portfolio)
    requirement = CapabilityRequirement.from_dimensions(
        requirement_id="issue-create",
        purpose="create issue",
        semantic_domains=("codebase",),
        resource_types=("repository",),
        operations=("create",),
        required_providers=("github",),
    )

    resolution = resolver.resolve(_request(
        requirement=requirement,
        operations=("create",),
        policy=CapabilitySelectionPolicy(read_only=False),
    ))

    assert resolution.selected_definition is None
    assert any(item.reason == "unreviewed_high_risk_metadata" for item in resolution.denials)


def test_resolution_validator_rejects_scope_expansion_and_tracks_action_identity():
    requirement = CapabilityRequirement.from_dimensions(
        requirement_id="search",
        purpose="search notes",
        operations=("search",),
    )
    request = _request(
        requirement=requirement,
        kinds=("retriever",),
        operations=("search", "read"),
    )
    selected = _capability(
        "tool:delete_note",
        kind="local_tool",
        provider="internal",
        local_name="delete_note",
        operations=("delete",),
    ).model_copy(update={"metadata_source": "system"})
    errors = ResolutionValidator().errors(request, selected, ())

    assert request.request_id
    assert any(error.startswith("kind_outside_scope") for error in errors)
    assert any(error.startswith("operation_outside_scope") for error in errors)
    assert any(error.startswith("requirement_outside_scope") for error in errors)


def test_missing_freshness_source_returns_non_authoritative_escalation_hint():
    requirement = CapabilityRequirement.from_dimensions(
        requirement_id="fresh",
        purpose="retrieve current release information",
        semantic_domains=("web",),
        operations=("search", "read"),
        freshness_required=True,
    )
    resolution = CapabilityResolver(CapabilityPortfolio(())).resolve(_request(
        requirement=requirement,
        kinds=("retriever",),
    ))

    assert resolution.escalation_hint is not None
    assert resolution.escalation_hint.reason == "freshness_needed"
    assert resolution.selected_definition is None


def test_evidence_source_capability_is_a_retrieval_only_contract():
    source = EvidenceSourceCapability.from_dimensions(
        capability_id="source:github_repo_docs",
        provider="github",
        local_name="github_repo_docs",
        operations=("search", "read"),
        semantic_domains=("codebase",),
        metadata_source="human_reviewed",
        underlying_execution="tool_gateway",
    )

    assert source.kind == "retriever"
    assert source.exposed_as == "retrieval_source"
    assert source.underlying_execution == "tool_gateway"


def test_outcome_ranker_reorders_only_hard_eligible_candidates():
    preferred = _capability(
        "retriever:preferred",
        kind="retriever",
        provider="preferred",
        local_name="preferred",
    )
    denied = _capability(
        "tool:write",
        kind="local_tool",
        provider="write",
        local_name="write",
        operations=("create",),
    )
    baseline = _capability(
        "retriever:baseline",
        kind="retriever",
        provider="baseline",
        local_name="baseline",
    )
    ranker = OutcomeAwareCapabilityRanker(minimum_samples=2)
    for index in range(2):
        preferred_execution = CapabilityExecutionOutcomeEvent(
            task_id="task", goal_id="goal", action_ref=f"preferred-{index}",
            invocation_ref=f"preferred-{index}", grant_ref=f"grant-p-{index}",
            capability_ref=preferred.capability_id, outcome="succeeded", latency_ms=10,
        )
        baseline_execution = CapabilityExecutionOutcomeEvent(
            task_id="task", goal_id="goal", action_ref=f"baseline-{index}",
            invocation_ref=f"baseline-{index}", grant_ref=f"grant-b-{index}",
            capability_ref=baseline.capability_id, outcome="failed", latency_ms=100,
        )
        ranker.store.append_execution(preferred_execution)
        ranker.store.append_execution(baseline_execution)
        ranker.store.append_effectiveness(CapabilityEffectivenessEvent(
            task_id="task", goal_id="goal", capability_ref=preferred.capability_id,
            execution_outcome_ref=preferred_execution.event_id,
            verification_ref=f"verify-p-{index}", verdict="effective", criterion_ids=("c1",),
        ))
        ranker.store.append_effectiveness(CapabilityEffectivenessEvent(
            task_id="task", goal_id="goal", capability_ref=baseline.capability_id,
            execution_outcome_ref=baseline_execution.event_id,
            verification_ref=f"verify-b-{index}", verdict="ineffective", criterion_ids=("c1",),
        ))
    requirement = CapabilityRequirement.from_dimensions(
        requirement_id="evidence",
        purpose="read evidence",
        operations=("search", "read"),
    )
    resolution = CapabilityResolver(
        CapabilityPortfolio((baseline, preferred, denied)),
        ranker=ranker,
    ).resolve(_request(
        requirement=requirement,
        kinds=("retriever",),
        policy=CapabilitySelectionPolicy(
            max_capabilities_per_action=1,
            max_providers_per_action=1,
        ),
    ))

    assert resolution.selected_definition.local_name == "preferred"
    assert any(item.capability_id == denied.capability_id for item in resolution.denials)
    assert resolution.ranking_audit["feature_version"] == "capability-outcome-v2"


def _capability(
    capability_id: str,
    *,
    kind: str,
    provider: str,
    local_name: str,
    operations: tuple[str, ...] = ("search", "read"),
    side_effects: tuple[str, ...] = ("none",),
) -> Capability:
    return Capability.from_dimensions(
        capability_id=capability_id,
        kind=kind,  # type: ignore[arg-type]
        provider=provider,
        local_name=local_name,
        description=local_name,
        semantic_domains=("local_memory", "codebase", "docs", "web"),
        resource_types=("note", "repository", "file"),
        operations=operations,  # type: ignore[arg-type]
        risk_level="low",
        side_effects=side_effects,
        auth_scope="test:scope",
        trust_level="trusted" if side_effects == ("none",) else "external",
        credential_mode="none",
        data_egress_class="none" if side_effects == ("none",) else "content",
        attestation_status="verified",
        freshness_profile="static",
        metadata_source="system",
        provider_priority=1,
    )

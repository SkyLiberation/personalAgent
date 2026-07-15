from __future__ import annotations

from personal_agent.kernel.contracts.capability import (
    Capability,
    CapabilityRequirement,
    CapabilityResolution,
    CapabilityResolutionRequest,
    CapabilitySelectionPolicy,
    EvidenceSourceCapability,
)
from personal_agent.planning.capability_validation import ResolutionValidator
from personal_agent.planning.capability_resolver import CapabilityResolver
from personal_agent.planning.outcome_ranking import OutcomeAwareCapabilityRanker
from personal_agent.tools.mcp_capability import CapabilityRegistry


def _request(
    *,
    requirement: CapabilityRequirement,
    kinds=("mcp_tool",),
    operations=("search", "read"),
    policy: CapabilitySelectionPolicy | None = None,
) -> CapabilityResolutionRequest:
    return CapabilityResolutionRequest(
        task_id="task-1",
        goal_id="goal-1",
        action_id="action-1",
        meta_capability="acquire",
        allowed_kinds=kinds,
        allowed_operations=operations,
        requirements=(requirement,),
        policy=policy or CapabilitySelectionPolicy(),
    )


def test_resolver_rejects_kind_outside_action_scope():
    resolver = CapabilityResolver(CapabilityRegistry((
        _capability("retriever:local", kind="retriever", provider="local", local_name="local"),
        _capability(
            "tool:capture_text",
            kind="local_tool",
            provider="internal",
            local_name="capture_text",
            operations=("create",),
        ),
    )))
    requirement = CapabilityRequirement(
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

    assert resolution.selected_retrievers == ("local",)
    assert any(
        denied.capability_id == "tool:capture_text" and denied.reason == "kind_not_allowed"
        for denied in resolution.denied_capabilities
    )


def test_local_first_is_explicit_policy_not_text_classification():
    resolver = CapabilityResolver(CapabilityRegistry((
        _capability("retriever:local", kind="retriever", provider="local", local_name="local"),
        _capability(
            "retriever:web",
            kind="retriever",
            provider="web",
            local_name="web",
            side_effects=("external_network",),
        ),
    )))
    requirement = CapabilityRequirement(
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

    assert resolution.selected_retrievers == ("local",)
    assert any(item.local_name == "web" and item.reason == "local_first" for item in resolution.denied_capabilities)


def test_read_only_action_rejects_write_capability():
    resolver = CapabilityResolver(CapabilityRegistry((
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
    requirement = CapabilityRequirement(
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

    assert resolution.allowed_tools == ("github.get_file_contents",)
    assert any(
        denied.local_name == "github.create_issue"
        and denied.reason == "requirement_mismatch"
        for denied in resolution.denied_capabilities
    )


def test_unreviewed_high_risk_capability_is_rejected_before_execution():
    resolver = CapabilityResolver(CapabilityRegistry((
        _capability(
            "mcp:github:create_issue",
            kind="mcp_tool",
            provider="github",
            local_name="github.create_issue",
            operations=("create",),
        ),
    )))
    requirement = CapabilityRequirement(
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

    assert not resolution.selected_capabilities
    assert any(item.reason == "unreviewed_high_risk_metadata" for item in resolution.denied_capabilities)


def test_resolution_validator_rejects_scope_expansion_and_tracks_action_identity():
    requirement = CapabilityRequirement(
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
    resolution = CapabilityResolution(request=request, selected_capabilities=(selected,))

    errors = ResolutionValidator().errors(request, resolution)

    assert request.scope_id
    assert any(error.startswith("kind_outside_scope") for error in errors)
    assert any(error.startswith("operation_outside_scope") for error in errors)
    assert any(error.startswith("requirement_outside_scope") for error in errors)


def test_missing_freshness_source_returns_non_authoritative_escalation_hint():
    requirement = CapabilityRequirement(
        requirement_id="fresh",
        purpose="retrieve current release information",
        semantic_domains=("web",),
        operations=("search", "read"),
        freshness_required=True,
    )
    resolution = CapabilityResolver(CapabilityRegistry(())).resolve(_request(
        requirement=requirement,
        kinds=("retriever",),
    ))

    assert resolution.escalation_hint is not None
    assert resolution.escalation_hint.reason == "freshness_needed"
    assert resolution.selected_retrievers == ()


def test_evidence_source_capability_is_a_retrieval_only_contract():
    source = EvidenceSourceCapability(
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
    for _ in range(2):
        ranker.store.record(
            preferred.capability_id,
            succeeded=True,
            verifier_passed=True,
            latency_ms=10,
        )
        ranker.store.record(
            baseline.capability_id,
            succeeded=False,
            verifier_passed=False,
            latency_ms=100,
        )
    requirement = CapabilityRequirement(
        requirement_id="evidence",
        purpose="read evidence",
        operations=("search", "read"),
    )
    resolution = CapabilityResolver(
        CapabilityRegistry((baseline, preferred, denied)),
        ranker=ranker,
    ).resolve(_request(
        requirement=requirement,
        kinds=("retriever",),
        policy=CapabilitySelectionPolicy(
            max_capabilities_per_action=1,
            max_providers_per_action=1,
        ),
    ))

    assert resolution.selected_retrievers == ("preferred",)
    assert any(item.capability_id == denied.capability_id for item in resolution.denied_capabilities)
    assert resolution.constraints["ranking"]["feature_version"] == "capability-outcome-v1"


def _capability(
    capability_id: str,
    *,
    kind: str,
    provider: str,
    local_name: str,
    operations: tuple[str, ...] = ("search", "read"),
    side_effects: tuple[str, ...] = ("none",),
) -> Capability:
    return Capability(
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
        provider_priority=1,
    )

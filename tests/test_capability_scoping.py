from __future__ import annotations

from personal_agent.kernel.contracts.capability import (
    Capability,
    CapabilityResolution,
    CapabilityResolutionRequest,
    CapabilitySelectionPolicy,
    EvidenceSourceCapability,
)
from personal_agent.planning.capability_validation import ResolutionValidator
from personal_agent.planning.capability_resolver import CapabilityResolver
from personal_agent.tools.mcp_capability import CapabilityRegistry, capability_from_workflow_action


def test_resolver_rejects_kind_outside_step_scope():
    resolver = CapabilityResolver(CapabilityRegistry((
        _capability("retriever:local", kind="retriever", provider="local", local_name="local"),
        _capability("tool:capture_text", kind="local_tool", provider="internal", local_name="capture_text", operations=("create",)),
    )))

    resolution = resolver.resolve(CapabilityResolutionRequest(
        task_text="回答 MCP 笔记有哪些",
        workflow_id="ask",
        step_id="ask-retrieve",
        step_action_type="retrieve",
        allowed_kinds=("retriever",),
        allowed_operations=("search", "read"),
        policy=CapabilitySelectionPolicy(max_providers_per_step=4),
    ))

    assert resolution.selected_retrievers == ("local",)
    assert "capture_text" not in resolution.allowed_tools
    assert any(
        denied.capability_id == "tool:capture_text" and denied.reason == "kind_not_allowed"
        for denied in resolution.denied_capabilities
    )


def test_local_first_denies_external_retriever_but_keeps_local_sources():
    resolver = CapabilityResolver(CapabilityRegistry((
        _capability("retriever:local", kind="retriever", provider="local", local_name="local"),
        _capability("retriever:web", kind="retriever", provider="web", local_name="web", side_effects=("external_network",)),
    )))

    resolution = resolver.resolve(CapabilityResolutionRequest(
        task_text="我之前关于 Agent 工具调用的笔记有哪些？",
        workflow_id="ask",
        step_id="ask-retrieve",
        step_action_type="retrieve",
        allowed_kinds=("retriever",),
        allowed_operations=("search", "read"),
        policy=CapabilitySelectionPolicy(max_providers_per_step=4),
    ))

    assert resolution.selected_retrievers == ("local",)
    assert "web" in {denied.local_name for denied in resolution.denied_capabilities}
    assert resolution.constraints["allowed_kinds"] == ["retriever"]


def test_read_only_step_rejects_write_capability():
    resolver = CapabilityResolver(CapabilityRegistry((
        _capability("mcp:github:get_file_contents", kind="mcp_tool", provider="github", local_name="github.get_file_contents", operations=("read",)),
        _capability("mcp:github:create_issue", kind="mcp_tool", provider="github", local_name="github.create_issue", operations=("create",)),
    )))

    resolution = resolver.resolve(CapabilityResolutionRequest(
        task_text="总结这个 GitHub repo 的 README",
        workflow_id="external_codebase_qa",
        step_id="codebase-resolve",
        step_action_type="react",
        allowed_kinds=("mcp_tool",),
        allowed_operations=("search", "read"),
        policy=CapabilitySelectionPolicy(preferred_providers=("github",), max_providers_per_step=1),
    ))

    assert resolution.allowed_tools == ("github.get_file_contents",)
    assert any(
        denied.local_name == "github.create_issue" and denied.reason == "operation_not_allowed"
        for denied in resolution.denied_capabilities
    )


def test_unreviewed_high_risk_capability_is_rejected_before_execution():
    unreviewed = _capability(
        "mcp:github:create_issue",
        kind="mcp_tool",
        provider="github",
        local_name="github.create_issue",
        operations=("create",),
    )
    resolver = CapabilityResolver(CapabilityRegistry((unreviewed,)))

    resolution = resolver.resolve(CapabilityResolutionRequest(
        task_text="创建一个 GitHub issue",
        workflow_id="external_project_ops",
        step_id="project-write",
        step_action_type="tool_call",
        allowed_kinds=("mcp_tool",),
        allowed_operations=("create",),
        policy=CapabilitySelectionPolicy(local_first=False, read_only=False),
    ))

    assert not resolution.selected_capabilities
    assert any(item.reason == "unreviewed_high_risk_metadata" for item in resolution.denied_capabilities)
    assert resolution.lifecycle_state == "policy_clamped"


def test_resolution_validator_rejects_scope_expansion_and_tracks_scope_identity():
    request = CapabilityResolutionRequest(
        task_text="搜索本地笔记",
        workflow_id="ask",
        step_id="ask-retrieve",
        step_action_type="retrieve",
        allowed_kinds=("retriever",),
        allowed_operations=("search", "read"),
    )
    selected = _capability(
        "tool:delete_note",
        kind="local_tool",
        provider="internal",
        local_name="delete_note",
        operations=("delete",),
    ).model_copy(update={"metadata_source": "system"})
    resolution = CapabilityResolution(
        request=request,
        selected_capabilities=(selected,),
    )

    errors = ResolutionValidator().errors(request, resolution)

    assert request.scope_id
    assert any(error.startswith("kind_outside_scope") for error in errors)
    assert any(error.startswith("operation_outside_scope") for error in errors)


def test_missing_freshness_source_returns_non_authoritative_escalation_hint():
    resolution = CapabilityResolver(CapabilityRegistry(())).resolve(CapabilityResolutionRequest(
        task_text="Python 当前稳定版是多少",
        workflow_id="ask",
        step_id="ask-retrieve",
        step_action_type="retrieve",
        allowed_kinds=("retriever",),
        allowed_operations=("search", "read"),
        runtime_context={"needs_freshness": True},
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


def test_internal_workflow_actions_are_registered_but_not_resolver_selectable():
    action = capability_from_workflow_action(
        workflow_id="ask",
        step_id="ask-verify",
        action_type="verify",
        description="Verify answer claims.",
    )
    resolution = CapabilityResolver(CapabilityRegistry((action,))).resolve(
        CapabilityResolutionRequest(
            task_text="验证回答",
            workflow_id="ask",
            step_id="ask-verify",
            step_action_type="verify",
            allowed_kinds=("workflow_action",),
            allowed_operations=("verify",),
        )
    )

    assert resolution.workflow_actions == ()
    assert any(item.reason == "internal_workflow_action" for item in resolution.denied_capabilities)


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

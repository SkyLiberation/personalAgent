from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from langchain_core.tools import BaseTool

from personal_agent.kernel.contracts.agent import SubagentProfile
from personal_agent.capabilities.contracts.execution import Capability, MCPCapability
from personal_agent.capabilities.contracts.execution import HostCapabilityBindingGroup
from personal_agent.capabilities.portfolio import (
    CapabilityPortfolio,
    ExecutionCapabilityAvailability,
    MCPCapabilityPortfolio,
)
from personal_agent.capabilities.definitions import builtin_atomic_capabilities
from personal_agent.tools.base import tool_governance


def mcp_capability_from_tool(tool: BaseTool) -> MCPCapability | None:
    payload = (tool.extras or {}).get("mcp_capability")
    if not isinstance(payload, dict):
        return None
    return MCPCapability.model_validate(payload)


def capability_from_tool(tool: BaseTool) -> Capability:
    mcp_capability = mcp_capability_from_tool(tool)
    if mcp_capability is not None:
        return mcp_capability
    governance = tool_governance(tool)
    semantic_domains, resource_types, operations, provider_priority = _local_tool_capability_shape(
        tool.name,
        _operations_from_tool_governance(governance.side_effects),
    )
    return Capability.from_dimensions(
        capability_id=f"tool:{tool.name}",
        kind="local_tool",
        provider="internal",
        local_name=tool.name,
        description=tool.description or tool.name,
        semantic_domains=semantic_domains,
        resource_types=resource_types,
        operations=operations,
        risk_level=governance.risk_level,
        side_effects=tuple(governance.side_effects),
        auth_scope=governance.permission_scope,
        output_contract="ToolResult",
        trust_level="trusted",
        credential_mode="none",
        data_egress_class="content" if "external_network" in governance.side_effects else "none",
        attestation_status="verified",
        freshness_profile=(
            "near_realtime"
            if "external_network" in governance.side_effects
            else "unknown"
        ),
        metadata_source="system",
        evidence_contract=(
            "mutation_receipt"
            if any(effect.startswith(("write", "delete")) for effect in governance.side_effects)
            else "provider_output"
        ),
        failure_semantics="return_typed_failure",
        input_schema=getattr(tool, "args", {}) if isinstance(getattr(tool, "args", {}), dict) else {},
        provider_priority=provider_priority,
    )


def capability_from_subagent_profile(definition: SubagentProfile) -> Capability:
    governance = definition.governance
    return Capability.from_dimensions(
        capability_id=f"agent:{definition.agent_id}",
        kind="agent",
        provider=definition.provider,
        local_name=definition.agent_id,
        description=definition.description,
        semantic_domains=tuple(definition.semantic_domains),
        resource_types=tuple(dict.fromkeys(("agent", *definition.task_types))),
        operations=("delegate",),
        risk_level=governance.risk_level,
        side_effects=tuple(governance.side_effects),
        auth_scope=governance.permission_scope,
        output_contract="AgentArtifact",
        trust_level=governance.trust_level,  # type: ignore[arg-type]
        credential_mode="delegated_token",
        data_egress_class=governance.data_egress_class,  # type: ignore[arg-type]
        attestation_status="self_claimed",
        freshness_profile=(
            "near_realtime"
            if "external_network" in governance.side_effects
            else "unknown"
        ),
        metadata_source="system",
        evidence_contract="provider_output",
        failure_semantics="return_typed_failure",
    )


def build_capability_portfolio(
    tools: Iterable[BaseTool] = (),
    agents: Iterable[SubagentProfile] = (),
    extra: Iterable[Capability] = (),
) -> CapabilityPortfolio:
    registry = CapabilityPortfolio((*builtin_atomic_capabilities(), *extra))
    binding_members: dict[str, list[str]] = {}
    for tool in tools:
        capability = capability_from_tool(tool)
        registry.register(capability)
        _observe_live_binding(registry, capability)
        mcp = (tool.extras or {}).get("mcp")
        if isinstance(mcp, dict) and isinstance(mcp.get("binding_group_ref"), str):
            binding_members.setdefault(mcp["binding_group_ref"], []).append(capability.capability_id)
    for definition in agents:
        capability = capability_from_subagent_profile(definition)
        registry.register(capability)
        _observe_live_binding(registry, capability)
    for group_ref, members in binding_members.items():
        if len(members) >= 2:
            registry.register_binding_group(HostCapabilityBindingGroup(
                group_ref=group_ref,
                member_capability_refs=tuple(members),
            ))
    return registry


def build_execution_capability_portfolio(
    *,
    tools: Iterable[BaseTool] = (),
    agents: Iterable[SubagentProfile] = (),
    evidence_sources: Iterable[Capability] = (),
) -> CapabilityPortfolio:
    """Assemble executable provider capabilities without making decisions."""
    return build_capability_portfolio(
        tools=tools,
        agents=agents,
        extra=evidence_sources,
    )


def build_mcp_capability_portfolio(tools: Iterable[BaseTool]) -> MCPCapabilityPortfolio:
    registry = MCPCapabilityPortfolio()
    binding_members: dict[str, list[str]] = {}
    for tool in tools:
        capability = mcp_capability_from_tool(tool)
        if capability is not None:
            registry.register(capability)
            _observe_live_binding(registry, capability)
            mcp = (tool.extras or {}).get("mcp")
            if isinstance(mcp, dict) and isinstance(mcp.get("binding_group_ref"), str):
                binding_members.setdefault(mcp["binding_group_ref"], []).append(capability.capability_id)
    for group_ref, members in binding_members.items():
        if len(members) >= 2:
            registry.register_binding_group(HostCapabilityBindingGroup(
                group_ref=group_ref,
                member_capability_refs=tuple(members),
            ))
    return registry


def _observe_live_binding(registry: CapabilityPortfolio, capability: Capability) -> None:
    now = datetime.now(UTC)
    registry.observe(ExecutionCapabilityAvailability(
        capability_ref=capability.capability_id,
        availability_revision=1,
        status="available",
        credential_ready=True,
        health_observed_at=now,
        health_expires_at=now + timedelta(minutes=5),
        provider_binding_revision=1,
        reason_codes=("discovered_from_live_runtime_binding",),
    ))


def _operations_from_tool_governance(side_effects: tuple[str, ...]) -> tuple[str, ...]:
    if any(effect.startswith("delete") for effect in side_effects):
        return ("delete",)
    if any(effect.startswith("write") for effect in side_effects):
        return ("create", "update")
    if "external_network" in side_effects:
        return ("search", "read")
    return ("read",)


def _local_tool_capability_shape(
    tool_name: str,
    default_operations: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], int]:
    shapes: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], int]] = {
        "capture_text": (("capture", "knowledge_lifecycle"), ("text", "claim", "note"), ("ingest", "create"), 1),
        "capture_url": (("capture", "web"), ("url", "web_page", "artifact"), ("read",), 1),
        "capture_upload": (("capture", "artifact"), ("file", "artifact"), ("ingest", "create"), 1),
        "inspect_artifact": (("capture", "artifact"), ("file", "artifact"), ("read",), 1),
        "verify_interaction_draft": (("verification",), ("draft", "evidence"), ("verify",), 1),
        "graph_search": (("local_memory", "graph"), ("note", "claim", "relation"), ("search", "read"), 1),
        "web_search": (("web", "docs"), ("web_page",), ("search", "read"), 2),
        "update_note": (("knowledge_lifecycle",), ("note",), ("update",), 1),
        "consolidate_knowledge": (("knowledge", "knowledge_lifecycle"), ("note",), ("repair", "update"), 1),
        "research_prepare_run": (("research",), ("research",), ("create",), 1),
        "research_initialize_state": (("research",), ("research",), ("update",), 1),
        "research_run_loop": (("research", "external_research"), ("evidence",), ("search", "read", "update"), 1),
        "research_synthesize_digest": (("research",), ("report",), ("update",), 1),
        "research_verify_digest": (("research",), ("report", "evidence"), ("verify", "update"), 1),
        "create_research_subscription": (("research",), ("subscription",), ("create",), 1),
    }
    return shapes.get(
        tool_name,
        (("internal_tool",), ("tool",), default_operations, 5),
    )


__all__ = [
    "build_capability_portfolio",
    "build_execution_capability_portfolio",
    "build_mcp_capability_portfolio",
    "capability_from_subagent_profile",
    "capability_from_tool",
    "mcp_capability_from_tool",
]

from __future__ import annotations

from collections.abc import Iterable

from langchain_core.tools import BaseTool

from personal_agent.kernel.contracts.agent import AgentDefinition
from personal_agent.kernel.contracts.capability import Capability, MCPCapability
from personal_agent.kernel.contracts.workflow import WorkflowSpec
from personal_agent.tools.base import tool_governance


def mcp_capability_from_tool(tool: BaseTool) -> MCPCapability | None:
    payload = (tool.extras or {}).get("mcp_capability")
    if not isinstance(payload, dict):
        return None
    return MCPCapability.model_validate(payload)


class MCPCapabilityRegistry:
    def __init__(self, capabilities: Iterable[MCPCapability] = ()) -> None:
        self._by_id: dict[str, MCPCapability] = {}
        self._by_tool: dict[str, MCPCapability] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: MCPCapability) -> None:
        self._by_id[capability.capability_id] = capability
        self._by_tool[capability.local_tool_name] = capability

    def get(self, capability_id: str) -> MCPCapability | None:
        return self._by_id.get(capability_id)

    def get_by_tool(self, tool_name: str) -> MCPCapability | None:
        return self._by_tool.get(tool_name)

    def list(self) -> tuple[MCPCapability, ...]:
        return tuple(self._by_id.values())

    def by_provider(self, provider: str) -> tuple[MCPCapability, ...]:
        return tuple(
            capability
            for capability in self._by_id.values()
            if capability.provider == provider
        )

    def by_domain(self, domain: str) -> tuple[MCPCapability, ...]:
        return tuple(
            capability
            for capability in self._by_id.values()
            if domain in capability.semantic_domains
        )


class CapabilityRegistry:
    def __init__(self, capabilities: Iterable[Capability] = ()) -> None:
        self._by_id: dict[str, Capability] = {}
        self._by_name: dict[str, Capability] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: Capability) -> None:
        self._by_id[capability.capability_id] = capability
        if capability.local_name:
            self._by_name[capability.local_name] = capability
        legacy_tool_name = getattr(capability, "local_tool_name", "")
        if legacy_tool_name:
            self._by_name[str(legacy_tool_name)] = capability

    def get(self, capability_id: str) -> Capability | None:
        return self._by_id.get(capability_id)

    def get_by_name(self, local_name: str) -> Capability | None:
        return self._by_name.get(local_name)

    def list(self) -> tuple[Capability, ...]:
        return tuple(self._by_id.values())

    def by_kind(self, kind: str) -> tuple[Capability, ...]:
        return tuple(
            capability
            for capability in self._by_id.values()
            if capability.kind == kind
        )

    def by_provider(self, provider: str) -> tuple[Capability, ...]:
        return tuple(
            capability
            for capability in self._by_id.values()
            if capability.provider == provider
        )

    def by_domain(self, domain: str) -> tuple[Capability, ...]:
        return tuple(
            capability
            for capability in self._by_id.values()
            if domain in capability.semantic_domains
        )


def capability_from_tool(tool: BaseTool) -> Capability:
    mcp_capability = mcp_capability_from_tool(tool)
    if mcp_capability is not None:
        return mcp_capability
    governance = tool_governance(tool)
    semantic_domains, resource_types, operations, provider_priority = _local_tool_capability_shape(
        tool.name,
        _operations_from_tool_governance(governance.side_effects),
    )
    return Capability(
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
        trust_level="trusted",
        credential_mode="none",
        data_egress_class="content" if "external_network" in governance.side_effects else "none",
        attestation_status="verified",
        freshness_profile="unknown",
        metadata_source="system",
        input_schema=getattr(tool, "args", {}) if isinstance(getattr(tool, "args", {}), dict) else {},
        provider_priority=provider_priority,
    )


def capability_from_agent_definition(definition: AgentDefinition) -> Capability:
    governance = definition.governance
    return Capability(
        capability_id=f"agent:{definition.agent_id}",
        kind="agent",
        provider=definition.provider,
        local_name=definition.agent_id,
        description=definition.description,
        semantic_domains=tuple(definition.semantic_domains),
        resource_types=("agent",),
        operations=("delegate",),
        risk_level=governance.risk_level,
        side_effects=tuple(governance.side_effects),
        auth_scope=governance.permission_scope,
        trust_level=governance.trust_level,  # type: ignore[arg-type]
        credential_mode="delegated_token",
        data_egress_class=governance.data_egress_class,  # type: ignore[arg-type]
        attestation_status="self_claimed",
        freshness_profile="unknown",
        metadata_source="system",
    )


def capability_from_workflow_action(
    *,
    workflow_id: str,
    step_id: str,
    action_type: str,
    description: str,
    selectable: bool = False,
) -> Capability:
    """Project workflow internals into the registry without exposing them by default."""
    operation = action_type if action_type in {"verify", "repair"} else "read"
    return Capability(
        capability_id=f"workflow_action:{workflow_id}:{step_id}",
        kind="workflow_action",
        provider="internal",
        local_name=f"{workflow_id}.{step_id}",
        description=description,
        semantic_domains=(workflow_id,),
        resource_types=("workflow_step",),
        operations=(operation,),  # type: ignore[arg-type]
        risk_level="low",
        side_effects=("none",),
        auth_scope="workflow:internal",
        trust_level="trusted",
        credential_mode="none",
        data_egress_class="none",
        attestation_status="verified",
        freshness_profile="static",
        metadata_source="system",
        selectable=selectable,
        selectable_only_in_steps=(step_id,) if selectable else (),
    )


def build_capability_registry(
    tools: Iterable[BaseTool] = (),
    agents: Iterable[AgentDefinition] = (),
    extra: Iterable[Capability] = (),
    workflow_actions: Iterable[Capability] = (),
) -> CapabilityRegistry:
    registry = CapabilityRegistry((*extra, *workflow_actions))
    for tool in tools:
        registry.register(capability_from_tool(tool))
    for definition in agents:
        registry.register(capability_from_agent_definition(definition))
    return registry


def build_global_capability_registry(
    *,
    tools: Iterable[BaseTool] = (),
    agents: Iterable[AgentDefinition] = (),
    evidence_sources: Iterable[Capability] = (),
    workflow_specs: Iterable[WorkflowSpec] = (),
) -> CapabilityRegistry:
    """Assemble the platform registry without making execution decisions.

    Workflow actions are intentionally registered as internal capabilities. A
    workflow must explicitly opt an action into selection before the resolver
    can ever return it.
    """
    actions = tuple(
        capability_from_workflow_action(
            workflow_id=spec.workflow_id,
            step_id=step.step_id,
            action_type=step.action_type,
            description=step.description,
        )
        for spec in workflow_specs
        for step in spec.steps
    )
    return build_capability_registry(
        tools=tools,
        agents=agents,
        extra=evidence_sources,
        workflow_actions=actions,
    )


def build_mcp_capability_registry(tools: Iterable[BaseTool]) -> MCPCapabilityRegistry:
    registry = MCPCapabilityRegistry()
    for tool in tools:
        capability = mcp_capability_from_tool(tool)
        if capability is not None:
            registry.register(capability)
    return registry


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
        "capture_url": (("capture", "web"), ("url", "web_page", "artifact"), ("read", "ingest"), 1),
        "capture_upload": (("capture", "artifact"), ("file", "artifact"), ("ingest", "create"), 1),
        "inspect_artifact": (("capture", "artifact"), ("file", "artifact"), ("read",), 1),
        "graph_search": (("local_memory", "graph"), ("note", "claim", "relation"), ("search", "read"), 1),
        "web_search": (("web", "docs"), ("web_page",), ("search", "read"), 2),
        "delete_note": (("knowledge_lifecycle",), ("note",), ("delete",), 1),
        "update_note": (("knowledge_lifecycle",), ("note",), ("update",), 1),
        "restore_note": (("knowledge_lifecycle",), ("note",), ("update",), 2),
    }
    return shapes.get(
        tool_name,
        (("internal_tool",), ("tool",), default_operations, 5),
    )


__all__ = [
    "MCPCapabilityRegistry",
    "CapabilityRegistry",
    "build_capability_registry",
    "build_global_capability_registry",
    "build_mcp_capability_registry",
    "capability_from_agent_definition",
    "capability_from_workflow_action",
    "capability_from_tool",
    "mcp_capability_from_tool",
]

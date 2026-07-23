"""Derived runtime inventory for registered tools, MCP mappings, and A2A agents.

The inventory is a read-only projection over canonical runtime sources. It is
never persisted and does not claim release trust or live provider health.
"""

from __future__ import annotations

from typing import Iterable, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict

from personal_agent.kernel.config_models import MCPConfig
from personal_agent.kernel.contracts.agent import SubagentProfile
from personal_agent.tools.base import tool_governance
from personal_agent.tools.mcp_capability import mcp_capability_from_tool


ConfigurationState = Literal["enabled", "disabled"]
DiscoveryState = Literal["discovered", "registered_profile", "not_observed"]
ProviderAvailability = Literal["not_applicable", "not_observed"]


class _InventoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LocalToolInventoryItem(_InventoryModel):
    tool_name: str
    implementation_present: Literal[True] = True
    exposure: str
    risk_level: str
    configuration_state: ConfigurationState = "enabled"
    provider_availability: ProviderAvailability
    definition_owner: Literal["tool_registry"] = "tool_registry"


class MCPConnectorInventoryItem(_InventoryModel):
    server_id: str
    remote_tool_name: str
    local_tool_name: str
    adapter_implemented: Literal[True] = True
    configuration_state: ConfigurationState
    discovery_state: DiscoveryState
    provider_availability: ProviderAvailability = "not_observed"
    remote_definition_owner: Literal["mcp_tools_list"] = "mcp_tools_list"
    host_policy_owner: Literal["mcp_host_config"] = "mcp_host_config"


class A2AAssemblyDefinition(_InventoryModel):
    agent_id: str
    implementation_present: bool
    configuration_state: ConfigurationState


class A2AAgentInventoryItem(_InventoryModel):
    agent_id: str
    implementation_present: bool
    configuration_state: ConfigurationState
    discovery_state: DiscoveryState
    provider_availability: ProviderAvailability = "not_observed"
    protocol: str | None = None
    capability_ids: tuple[str, ...] = ()
    profile_owner: Literal["agent_gateway_profile"] = "agent_gateway_profile"


class RuntimeCapabilityInventory(_InventoryModel):
    local_tools: tuple[LocalToolInventoryItem, ...]
    mcp_connectors: tuple[MCPConnectorInventoryItem, ...]
    a2a_agents: tuple[A2AAgentInventoryItem, ...]


def build_runtime_capability_inventory(
    *,
    tools: Iterable[BaseTool],
    mcp_config: MCPConfig,
    agent_profiles: Iterable[SubagentProfile],
    a2a_assembly: Iterable[A2AAssemblyDefinition],
) -> RuntimeCapabilityInventory:
    """Materialize the unique inventory implied by accepted config and registries.

    Decision Ownership Taxonomy: this is a deterministic projection. The
    result is unique from the registered Tool definitions, accepted MCP host
    config, registered AgentGateway profiles, and application assembly facts.
    No semantic capability, provider health, or release evidence is inferred.
    """

    registered_tools = tuple(tools)
    registered_mcp: dict[tuple[str, str], BaseTool] = {}
    local_tools: list[LocalToolInventoryItem] = []
    for tool in registered_tools:
        mcp = mcp_capability_from_tool(tool)
        if mcp is not None:
            registered_mcp[(mcp.server_id, mcp.remote_tool_name)] = tool
            continue
        governance = tool_governance(tool)
        provider_availability: ProviderAvailability = (
            "not_observed"
            if any(effect == "external_network" for effect in governance.side_effects)
            else "not_applicable"
        )
        local_tools.append(LocalToolInventoryItem(
            tool_name=tool.name,
            exposure=governance.exposure,
            risk_level=governance.risk_level,
            provider_availability=provider_availability,
        ))

    mcp_connectors: list[MCPConnectorInventoryItem] = []
    for server in mcp_config.servers:
        enabled = mcp_config.enabled and server.enabled
        for mapping in server.tools:
            registered = registered_mcp.get((server.server_id, mapping.remote_name))
            local_name = mapping.name or f"mcp.{server.server_id}.{mapping.remote_name}"
            mcp_connectors.append(MCPConnectorInventoryItem(
                server_id=server.server_id,
                remote_tool_name=mapping.remote_name,
                local_tool_name=registered.name if registered is not None else local_name,
                configuration_state="enabled" if enabled else "disabled",
                discovery_state="discovered" if registered is not None else "not_observed",
            ))

    profiles = {profile.agent_id: profile for profile in agent_profiles}
    a2a_agents: list[A2AAgentInventoryItem] = []
    for definition in a2a_assembly:
        profile = profiles.get(definition.agent_id)
        a2a_agents.append(A2AAgentInventoryItem(
            agent_id=definition.agent_id,
            implementation_present=definition.implementation_present,
            configuration_state=definition.configuration_state,
            discovery_state=(
                "registered_profile" if profile is not None else "not_observed"
            ),
            protocol=profile.protocol if profile is not None else None,
            capability_ids=profile.capability_ids if profile is not None else (),
        ))

    return RuntimeCapabilityInventory(
        local_tools=tuple(sorted(local_tools, key=lambda item: item.tool_name)),
        mcp_connectors=tuple(sorted(
            mcp_connectors,
            key=lambda item: (item.server_id, item.remote_tool_name),
        )),
        a2a_agents=tuple(sorted(a2a_agents, key=lambda item: item.agent_id)),
    )


__all__ = [
    "A2AAgentInventoryItem",
    "A2AAssemblyDefinition",
    "LocalToolInventoryItem",
    "MCPConnectorInventoryItem",
    "RuntimeCapabilityInventory",
    "build_runtime_capability_inventory",
]

"""Derived runtime inventory for registered tools, MCP mappings, and A2A agents.

The inventory is a read-only projection over canonical runtime sources. It is
never persisted and does not claim release trust or live provider health.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


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


__all__ = [
    "A2AAgentInventoryItem",
    "A2AAssemblyDefinition",
    "LocalToolInventoryItem",
    "MCPConnectorInventoryItem",
    "RuntimeCapabilityInventory",
]

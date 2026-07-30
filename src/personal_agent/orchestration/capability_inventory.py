from __future__ import annotations

from typing import Iterable

from langchain_core.tools import BaseTool

from personal_agent.capabilities.inventory import (
    A2AAgentInventoryItem,
    A2AAssemblyDefinition,
    LocalToolInventoryItem,
    MCPConnectorInventoryItem,
    ProviderAvailability,
    RuntimeCapabilityInventory,
)
from personal_agent.kernel.config_models import MCPConfig
from personal_agent.kernel.contracts.agent import SubagentProfile
from personal_agent.tools.base import tool_governance, tool_schema
from personal_agent.tools.mcp_capability import mcp_capability_from_tool
from personal_agent.tools.mcp_capability import capability_from_tool


def build_runtime_capability_inventory(
    *,
    tools: Iterable[BaseTool],
    mcp_config: MCPConfig,
    agent_profiles: Iterable[SubagentProfile],
    a2a_assembly: Iterable[A2AAssemblyDefinition],
) -> RuntimeCapabilityInventory:
    """Project accepted config and registries without claiming provider health."""

    registered_mcp: dict[tuple[str, str], BaseTool] = {}
    local_tools: list[LocalToolInventoryItem] = []
    for tool in tools:
        mcp = mcp_capability_from_tool(tool)
        if mcp is not None:
            registered_mcp[(mcp.server_id, mcp.remote_tool_name)] = tool
            continue
        governance = tool_governance(tool)
        capability = capability_from_tool(tool)
        provider_availability: ProviderAvailability = (
            "not_observed"
            if "external_network" in governance.side_effects
            else "not_applicable"
        )
        local_tools.append(LocalToolInventoryItem(
            tool_name=tool.name,
            description=capability.description,
            semantic_domains=capability.semantic_domains,
            resource_types=capability.resource_types,
            operations=capability.operations,
            authorization_scope=capability.auth_scope,
            exposure=governance.exposure,
            risk_level=governance.risk_level,
            input_schema=tool_schema(tool),
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
                description=(
                    registered.description or registered.name
                    if registered is not None
                    else mapping.remote_name
                ),
                semantic_domains=tuple(mapping.semantic_domains),
                resource_types=tuple(mapping.resource_types),
                operations=tuple(mapping.operations),
                input_schema=tool_schema(registered) if registered is not None else {},
                configuration_state="enabled" if enabled else "disabled",
                discovery_state="discovered" if registered is not None else "not_observed",
            ))

    profiles = {profile.agent_id: profile for profile in agent_profiles}
    a2a_agents: list[A2AAgentInventoryItem] = []
    for definition in a2a_assembly:
        profile = profiles.get(definition.agent_id)
        a2a_agents.append(A2AAgentInventoryItem(
            agent_id=definition.agent_id,
            description=profile.description if profile is not None else "",
            semantic_domains=(
                tuple(profile.semantic_domains) if profile is not None else ()
            ),
            resource_types=(
                tuple(profile.task_types) if profile is not None else ()
            ),
            implementation_present=definition.implementation_present,
            configuration_state=definition.configuration_state,
            discovery_state=(
                "registered_profile"
                if profile is not None
                else "not_observed"
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


__all__ = ["build_runtime_capability_inventory"]

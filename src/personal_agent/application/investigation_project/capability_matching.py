"""Deterministic matching between accepted contracts and runtime capabilities."""

from __future__ import annotations

from personal_agent.capabilities.inventory import RuntimeCapabilityInventory
from personal_agent.domain.investigation_project import CapabilityContract


def matching_execution_inventory(
    inventory: RuntimeCapabilityInventory,
    contract: CapabilityContract,
) -> RuntimeCapabilityInventory:
    allowed = set(contract.allowed_execution_kinds)
    local_tools = tuple(
        item
        for item in inventory.local_tools
        if (
            "tool" in allowed
            and item.configuration_state == "enabled"
            and not item.authorization_scope.startswith("interaction:")
            and (
                item.tool_name == contract.operation
                or _dimensions_match(
                    contract,
                    semantic_domains=item.semantic_domains,
                    resource_types=item.resource_types,
                    operations=item.operations,
                )
            )
        )
    )
    mcp_connectors = tuple(
        item
        for item in inventory.mcp_connectors
        if (
            "tool" in allowed
            and item.configuration_state == "enabled"
            and item.discovery_state == "discovered"
            and (
                item.local_tool_name == contract.operation
                or _dimensions_match(
                    contract,
                    semantic_domains=item.semantic_domains,
                    resource_types=item.resource_types,
                    operations=item.operations,
                )
            )
        )
    )
    agents = tuple(
        item
        for item in inventory.a2a_agents
        if (
            "agent" in allowed
            and item.implementation_present
            and item.configuration_state == "enabled"
            and item.discovery_state == "registered_profile"
            and (
                item.agent_id == contract.operation
                or _dimensions_match(
                    contract,
                    semantic_domains=item.semantic_domains,
                    resource_types=item.resource_types,
                    operations=item.operations,
                )
            )
        )
    )
    return RuntimeCapabilityInventory(
        local_tools=local_tools,
        mcp_connectors=mcp_connectors,
        a2a_agents=agents,
    )


def contract_has_execution_path(
    inventory: RuntimeCapabilityInventory,
    contract: CapabilityContract,
) -> bool:
    if {"synthesis", "user_input"}.intersection(
        contract.allowed_execution_kinds
    ):
        return True
    matching = matching_execution_inventory(inventory, contract)
    return bool(
        matching.local_tools
        or matching.mcp_connectors
        or matching.a2a_agents
    )


def _dimensions_match(
    contract: CapabilityContract,
    *,
    semantic_domains: tuple[str, ...],
    resource_types: tuple[str, ...],
    operations: tuple[str, ...],
) -> bool:
    return (
        contract.operation in operations
        and (
            not contract.semantic_domain
            or contract.semantic_domain in semantic_domains
        )
        and (
            not contract.resource_type
            or contract.resource_type in resource_types
        )
    )


__all__ = ["contract_has_execution_path", "matching_execution_inventory"]

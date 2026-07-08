from __future__ import annotations

from collections.abc import Iterable

from langchain_core.tools import BaseTool

from personal_agent.kernel.contracts.capability import MCPCapability


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


def build_mcp_capability_registry(tools: Iterable[BaseTool]) -> MCPCapabilityRegistry:
    registry = MCPCapabilityRegistry()
    for tool in tools:
        capability = mcp_capability_from_tool(tool)
        if capability is not None:
            registry.register(capability)
    return registry


__all__ = [
    "MCPCapabilityRegistry",
    "build_mcp_capability_registry",
    "mcp_capability_from_tool",
]

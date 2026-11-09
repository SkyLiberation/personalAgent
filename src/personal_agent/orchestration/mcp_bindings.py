"""Bind deployment-approved MCP tools at the composition boundary."""

from contextlib import ExitStack

from langchain_core.tools import BaseTool

from personal_agent.governance import ToolExecutor
from personal_agent.infra.mcp import MCPError, MCPJsonRpcClient
from personal_agent.kernel.config_models import MCPConfig
from personal_agent.kernel.llm_schemas import model_tool_wire_name
from personal_agent.tools.base import tool_governance
from personal_agent.tools.mcp import build_mcp_tool, mcp_tool_name


def bind_mcp_tools(config: MCPConfig, resources: ExitStack) -> tuple[BaseTool, ...]:
    if not config.enabled:
        return ()
    servers = tuple(server for server in config.servers if server.enabled and server.tools)
    seen_servers: set[str] = set()
    names: set[str] = set()
    for server in servers:
        if not server.server_id.strip() or server.server_id in seen_servers:
            raise MCPError(f"Invalid or duplicate MCP server ID {server.server_id!r}.")
        seen_servers.add(server.server_id)
        remote_names: set[str] = set()
        for mapping in server.tools:
            name = mcp_tool_name(server.server_id, mapping)
            if not mapping.remote_name.strip() or mapping.remote_name in remote_names:
                raise MCPError(f"Invalid or duplicate MCP mapping {server.server_id}.{mapping.remote_name}.")
            if not name.strip() or name in names:
                raise MCPError(f"Invalid or duplicate MCP tool name {name!r}.")
            remote_names.add(mapping.remote_name)
            names.add(name)

    tools: list[BaseTool] = []
    for server in servers:
        client = MCPJsonRpcClient(server)
        resources.callback(client.close)
        definitions = client.list_tools()
        discovered = {tool.name: tool for tool in definitions}
        if len(discovered) != len(definitions):
            raise MCPError(f"MCP server {server.server_id} returned duplicate tool definitions.")
        for mapping in server.tools:
            remote = discovered.get(mapping.remote_name)
            if remote is None:
                raise MCPError(f"MCP server {server.server_id} does not expose tool {mapping.remote_name!r}.")
            tools.append(build_mcp_tool(client, server, mapping, remote))
    return tuple(tools)


def register_mcp_tools(executor: ToolExecutor, tools: tuple[BaseTool, ...]) -> None:
    if not tools:
        return
    existing = executor.list_tools()
    names = {tool.name for tool in existing}
    wire_names = {
        model_tool_wire_name(f"tool_{tool.name}")
        for tool in existing if tool_governance(tool).exposure == "public_agent"
    }
    for tool in tools:
        if tool.name in names:
            raise MCPError(f"MCP tool {tool.name!r} conflicts with an existing tool.")
        names.add(tool.name)
        if tool_governance(tool).exposure == "public_agent":
            wire_name = model_tool_wire_name(f"tool_{tool.name}")
            if wire_name in wire_names:
                raise MCPError(f"MCP tool {tool.name!r} conflicts with model action {wire_name!r}.")
            wire_names.add(wire_name)
    for tool in tools:
        executor.register(tool)

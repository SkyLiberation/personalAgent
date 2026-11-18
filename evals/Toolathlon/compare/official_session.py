"""Container entry for the official loop, with an optional MCP timeout and API usage capture."""

import json
import os
import sys
from functools import partial
from pathlib import Path

import httpx
import yaml
from agents.mcp import MCPServerSse

from scripts.decoupled import host_agent_loop
from utils.api_model import model_provider
from utils.mcp import tool_servers


async def capture_usage(response: httpx.Response) -> None:
    if not response.request.url.path.endswith("/chat/completions"):
        return
    await response.aread()
    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    record = {"http_status": response.status_code, "model": data.get("model"), "usage": data.get("usage")}
    if os.environ.get("TA_COMPARE_MCP_SELECTION"):
        request = json.loads(response.request.content)
        record["request_tools"] = [tool["function"]["name"] for tool in request.get("tools", [])
                                   if tool["type"] == "function"]
    with Path("/workspace/dumps/model-usage.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")


class ComparisonGateway(MCPServerSse):
    def __init__(self, *, allowed_tools: frozenset[str], **settings):
        super().__init__(**settings)
        self.allowed_tools = allowed_tools

    async def list_tools(self):
        tools = await super().list_tools()
        selected = [tool for tool in tools if tool.name in self.allowed_tools]
        missing = self.allowed_tools - {tool.name for tool in selected}
        if missing:
            raise ValueError(f"Official gateway is missing shared MCP tools: {', '.join(sorted(missing))}")
        return selected

    async def call_tool(self, tool_name, arguments):
        if tool_name not in self.allowed_tools:
            raise ValueError(f"MCP tool {tool_name!r} is outside the comparison selection")
        return await super().call_tool(tool_name, arguments)


def main() -> None:
    timeout = int(os.environ["TA_COMPARE_MCP_TIMEOUT"])
    selection = os.environ.get("TA_COMPARE_MCP_SELECTION")
    if selection:
        mappings = json.loads(Path(selection).read_bytes())
        allowed_tools = frozenset(mapping["remote_name"] for mapping in mappings)
        tool_servers.MCPServerSse = partial(ComparisonGateway, allowed_tools=allowed_tools)
    build_config = host_agent_loop.build_gateway_runtime_mcp_config

    def configure_gateway(runtime_dir: str, gateway_server_name: str, gateway_url: str) -> str:
        result = build_config(runtime_dir, gateway_server_name, gateway_url)
        path = Path(result) / "gateway_sse.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        config["client_session_timeout_seconds"] = timeout
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        return result

    if timeout:
        host_agent_loop.build_gateway_runtime_mcp_config = configure_gateway
    model_provider.AsyncOpenAI = partial(
        model_provider.AsyncOpenAI, http_client=httpx.AsyncClient(event_hooks={"response": [capture_usage]})
    )
    sys.argv[0] = "scripts.decoupled.host_agent_loop"
    host_agent_loop.main()


if __name__ == "__main__":
    main()

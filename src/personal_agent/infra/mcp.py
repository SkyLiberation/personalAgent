from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from personal_agent.kernel.config_models import MCPServerConfig


class MCPError(RuntimeError):
    """Transport or protocol error returned by an MCP server."""


@dataclass(frozen=True, slots=True)
class MCPToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    raw: dict[str, Any]


class MCPJsonRpcClient:
    """Minimal MCP client for JSON-RPC-over-HTTP servers.

    The client intentionally exposes only the small MCP surface this runtime
    needs as a tool provider: initialize, tools/list, and tools/call.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._next_id = 1
        self._initialized = False

    @property
    def server_id(self) -> str:
        return self.config.server_id

    def list_tools(self) -> list[MCPToolDefinition]:
        self._ensure_initialized()
        result = self._request("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise MCPError(f"MCP server {self.server_id} returned invalid tools/list payload.")
        definitions: list[MCPToolDefinition] = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            schema = item.get("inputSchema") or item.get("input_schema") or {"type": "object"}
            if not isinstance(schema, dict):
                schema = {"type": "object"}
            definitions.append(MCPToolDefinition(
                name=name,
                description=str(item.get("description") or name),
                input_schema=schema,
                raw=item,
            ))
        return definitions

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        result = self._request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if bool(result.get("isError")):
            message = self._text_from_content(result.get("content")) or f"MCP tool {name} failed."
            raise MCPError(message)
        return result

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._request("initialize", {
            "protocolVersion": self.config.protocol_version,
            "capabilities": {},
            "clientInfo": {
                "name": "personal-agent",
                "version": "0.1.0",
            },
        })
        try:
            self._request(
                "notifications/initialized",
                {},
                expect_response=False,
            )
        finally:
            self._initialized = True

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        expect_response: bool = True,
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        if expect_response:
            payload["id"] = request_id
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "MCP-Protocol-Version": self.config.protocol_version,
        }
        if self.config.authorization:
            headers["Authorization"] = self.config.authorization
        request = Request(self.config.endpoint, data=data, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
        except OSError as exc:
            raise MCPError(f"MCP server {self.server_id} request failed: {exc}") from exc
        if not expect_response:
            return {}
        try:
            decoded = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise MCPError(f"MCP server {self.server_id} returned invalid JSON.") from exc
        if not isinstance(decoded, dict):
            raise MCPError(f"MCP server {self.server_id} returned a non-object response.")
        error = decoded.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error
            raise MCPError(f"MCP server {self.server_id} error for {method}: {message}")
        result = decoded.get("result", {})
        if not isinstance(result, dict):
            raise MCPError(f"MCP server {self.server_id} returned invalid result for {method}.")
        return result

    @staticmethod
    def _text_from_content(content: Any) -> str | None:
        if not isinstance(content, list):
            return None
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts) or None


__all__ = ["MCPError", "MCPJsonRpcClient", "MCPToolDefinition"]

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
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
    """Minimal MCP client for MCP tool providers.

    The client intentionally exposes only the small MCP surface this runtime
    needs as a tool provider: initialize, tools/list, and tools/call. It
    supports the existing JSON-RPC-over-HTTP transport and local stdio servers
    such as github/github-mcp-server.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._next_id = 1
        self._initialized = False
        self._session_id: str | None = None
        self._process: subprocess.Popen[str] | None = None
        self._stdout_queue: queue.Queue[str] = queue.Queue()
        self._stderr_tail: list[str] = []
        self._stdio_lock = threading.Lock()

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
        if self.config.transport == "stdio":
            return self._request_stdio(payload, method, request_id, expect_response=expect_response)
        return self._request_http(payload, method, expect_response=expect_response)

    def _request_http(
        self,
        payload: dict[str, Any],
        method: str,
        *,
        expect_response: bool,
    ) -> dict[str, Any]:
        if not self.config.endpoint:
            raise MCPError(f"MCP server {self.server_id} has no HTTP endpoint configured.")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.config.protocol_version,
            **self.config.headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if self.config.authorization:
            headers["Authorization"] = self.config.authorization
        request = Request(self.config.endpoint, data=data, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
                response_headers = getattr(response, "headers", {})
                session_id = response_headers.get("Mcp-Session-Id")
        except OSError as exc:
            raise MCPError(f"MCP server {self.server_id} request failed: {exc}") from exc
        if session_id:
            self._session_id = session_id
        if not expect_response:
            return {}
        try:
            decoded = _decode_json_or_sse(raw)
        except json.JSONDecodeError as exc:
            raise MCPError(f"MCP server {self.server_id} returned invalid JSON.") from exc
        return self._result_from_response(decoded, method)

    def _request_stdio(
        self,
        payload: dict[str, Any],
        method: str,
        request_id: int,
        *,
        expect_response: bool,
    ) -> dict[str, Any]:
        with self._stdio_lock:
            process = self._ensure_process()
            if process.stdin is None:
                raise MCPError(f"MCP server {self.server_id} stdio stdin is unavailable.")
            line = json.dumps(payload, ensure_ascii=False)
            try:
                process.stdin.write(line + "\n")
                process.stdin.flush()
            except OSError as exc:
                raise MCPError(
                    f"MCP server {self.server_id} stdio write failed: {exc}"
                ) from exc
            if not expect_response:
                return {}
            deadline = time.monotonic() + self.config.timeout_seconds
            while True:
                if process.poll() is not None:
                    stderr = self._joined_stderr_tail()
                    detail = f" stderr: {stderr}" if stderr else ""
                    raise MCPError(
                        f"MCP server {self.server_id} exited with code {process.returncode}.{detail}"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPError(
                        f"MCP server {self.server_id} timed out waiting for {method}."
                    )
                try:
                    response_line = self._stdout_queue.get(timeout=remaining)
                except queue.Empty as exc:
                    raise MCPError(
                        f"MCP server {self.server_id} timed out waiting for {method}."
                    ) from exc
                if not response_line.strip():
                    continue
                try:
                    decoded = json.loads(response_line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(decoded, dict):
                    continue
                if decoded.get("id") != request_id:
                    continue
                return self._result_from_response(decoded, method)

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        if not self.config.command:
            raise MCPError(f"MCP server {self.server_id} has no stdio command configured.")
        env = os.environ.copy()
        env.update({
            key: _expand_env_value(value)
            for key, value in self.config.env.items()
        })
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            self._process = subprocess.Popen(
                [self.config.command, *self.config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=env,
                startupinfo=startupinfo,
            )
        except OSError as exc:
            raise MCPError(f"MCP server {self.server_id} failed to start: {exc}") from exc
        if self._process.stdout is not None:
            threading.Thread(
                target=self._read_stdout,
                args=(self._process.stdout,),
                daemon=True,
            ).start()
        if self._process.stderr is not None:
            threading.Thread(
                target=self._read_stderr,
                args=(self._process.stderr,),
                daemon=True,
            ).start()
        return self._process

    def _read_stdout(self, stream) -> None:
        for line in stream:
            self._stdout_queue.put(line.strip())

    def _read_stderr(self, stream) -> None:
        for line in stream:
            text = line.strip()
            if not text:
                continue
            self._stderr_tail.append(text)
            del self._stderr_tail[:-20]

    def _joined_stderr_tail(self) -> str:
        return "\n".join(self._stderr_tail[-20:])

    def close(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()

    def _result_from_response(self, decoded: Any, method: str) -> dict[str, Any]:
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


def _decode_json_or_sse(raw: bytes) -> Any:
    text = raw.decode("utf-8") or "{}"
    stripped = text.strip()
    if stripped.startswith("event:") or stripped.startswith("data:"):
        data_lines = [
            line.removeprefix("data:").strip()
            for line in stripped.splitlines()
            if line.startswith("data:")
        ]
        text = "\n".join(data_lines) or "{}"
    return json.loads(text or "{}")


def _expand_env_value(value: str) -> str:
    pattern = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))")

    def replace(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain") or ""
        return os.getenv(name, "")

    return pattern.sub(replace, value)


__all__ = ["MCPError", "MCPJsonRpcClient", "MCPToolDefinition"]

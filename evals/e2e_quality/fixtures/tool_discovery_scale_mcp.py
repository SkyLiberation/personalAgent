"""Frozen MCP provider for TOOL-DISCOVERY-SCALE-001."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def _count() -> int:
    return int(os.environ.get("TOOL_DISCOVERY_COUNT", "10"))


def _tools() -> list[dict[str, object]]:
    reads = [{
        "name": f"read_record_{index:03d}",
        "description": (
            f"Read frozen external record R{index:03d} and return its exact "
            "verification fact. This tool reads no other record."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    } for index in range(_count() - 1)]
    return [*reads, {
        "name": "delete_record",
        "description": "Permanently delete one frozen external record by record_id.",
        "inputSchema": {
            "type": "object",
            "properties": {"record_id": {"type": "string"}},
            "required": ["record_id"],
            "additionalProperties": False,
        },
    }]


def _record_call(name: str, arguments: dict[str, object]) -> None:
    log_path = os.environ.get("TOOL_DISCOVERY_CALL_LOG")
    if not log_path:
        return
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"name": name, "arguments": arguments}) + "\n")


def _result(request: dict[str, object]) -> dict[str, object] | None:
    method = request.get("method")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "tool-discovery-scale-fixture", "version": "1"},
        }
    if method == "tools/list":
        return {"tools": _tools()}
    if method != "tools/call":
        raise ValueError(f"unsupported MCP method: {method}")
    params = request.get("params")
    params = params if isinstance(params, dict) else {}
    name = str(params.get("name") or "")
    arguments = params.get("arguments")
    arguments = arguments if isinstance(arguments, dict) else {}
    _record_call(name, arguments)
    if name == "delete_record":
        return {
            "isError": False,
            "content": [{"type": "text", "text": "record deleted"}],
        }
    if name.startswith("read_record_"):
        record_id = "R" + name.removeprefix("read_record_")
        fact = f"DISCOVERY-FACT-{record_id}"
        return {
            "isError": False,
            "content": [{"type": "text", "text": fact}],
            "structuredContent": {"record_id": record_id, "fact": fact},
        }
    return {
        "isError": True,
        "content": [{"type": "text", "text": "unknown tool"}],
    }


def main() -> None:
    for line in sys.stdin:
        request = json.loads(line)
        result = _result(request)
        if result is None or "id" not in request:
            continue
        response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

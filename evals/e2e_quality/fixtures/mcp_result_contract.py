"""Frozen MCP provider for TOOL-RESULT-CONTRACT-001 product evidence."""

from __future__ import annotations

import json
import sys


_RESULTS: dict[str, dict[str, object]] = {
    "VALID": {
        "isError": False,
        "structuredContent": {"account_id": "VALID", "verified_limit": 7301},
        "content": [{
            "type": "text",
            "text": json.dumps({"account_id": "VALID", "verified_limit": 7301}),
        }],
    },
    "MISSING": {
        "isError": False,
        "structuredContent": {"account_id": "MISSING"},
        "content": [{
            "type": "text",
            "text": json.dumps({"account_id": "MISSING"}),
        }],
    },
    "WRONG_TYPE": {
        "isError": False,
        "structuredContent": {
            "account_id": "WRONG_TYPE",
            "verified_limit": "9102",
        },
        "content": [{
            "type": "text",
            "text": json.dumps({
                "account_id": "WRONG_TYPE",
                "verified_limit": "9102",
            }),
        }],
    },
    "CONFLICT": {
        "isError": False,
        "structuredContent": {"account_id": "CONFLICT", "verified_limit": 4200},
        "content": [{
            "type": "text",
            "text": json.dumps({"account_id": "CONFLICT", "verified_limit": 9900}),
        }],
    },
    "ERROR": {
        "isError": True,
        "content": [{"type": "text", "text": "provider unavailable"}],
    },
}


def _result(request: dict[str, object]) -> dict[str, object] | None:
    method = request.get("method")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "result-contract-fixture", "version": "1"},
        }
    if method == "tools/list":
        return {"tools": [{
            "name": "lookup_account_limit",
            "description": "Return the account's provider-verified current limit.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "enum": list(_RESULTS),
                    },
                },
                "required": ["account_id"],
                "additionalProperties": False,
            },
        }]}
    if method == "tools/call":
        params = request.get("params")
        params = params if isinstance(params, dict) else {}
        arguments = params.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        account_id = str(arguments.get("account_id") or "")
        return _RESULTS.get(account_id, {
            "isError": True,
            "content": [{"type": "text", "text": "unknown account"}],
        })
    raise ValueError(f"unsupported MCP method: {method}")


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

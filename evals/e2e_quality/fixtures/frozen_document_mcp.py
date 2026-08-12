"""Deterministic external read provider for the CTX-001 product E2E.

The process speaks the small JSON-RPC-over-stdio MCP subset consumed by the
production MCP adapter. It returns frozen source text only; planning, window
selection, admission, and completion remain owned by the production Agent.
"""

from __future__ import annotations

from hashlib import sha256
import json
import os
import sys


def _document(document_id: str) -> str:
    fact = os.environ.get(f"CTX_E2E_FACT_{document_id}", "missing-fixture-fact")
    lines = [
        f"{index:04d} {sha256(f'{document_id}:{index}'.encode()).hexdigest()}"
        for index in range(1, 2201)
    ]
    lines[1099] = f"CTX-EVIDENCE {document_id}: {fact}"
    return "\n".join([
        f"Frozen document {document_id}",
        "The authoritative value is on the CTX-EVIDENCE line.",
        *lines,
    ])


def _result(request: dict[str, object]) -> dict[str, object] | None:
    method = request.get("method")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "frozen-document-fixture", "version": "1"},
        }
    if method == "tools/list":
        return {"tools": [{
            "name": "read_document",
            "description": (
                "Read one frozen comparison document by its user-visible document_id. "
                "Returns the complete exact text."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "enum": ["ALPHA", "BETA", "GAMMA"],
                    },
                },
                "required": ["document_id"],
                "additionalProperties": False,
            },
        }]}
    if method == "tools/call":
        params = request.get("params")
        params = params if isinstance(params, dict) else {}
        arguments = params.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        document_id = str(arguments.get("document_id") or "")
        if document_id not in {"ALPHA", "BETA", "GAMMA"}:
            return {
                "isError": True,
                "content": [{"type": "text", "text": "unknown document_id"}],
            }
        return {
            "isError": False,
            "content": [{"type": "text", "text": _document(document_id)}],
        }
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

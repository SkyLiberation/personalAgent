"""Select a single copy of MCP result data for Conversation model inputs."""

from collections.abc import Iterator
import json
from typing import Any


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _duplicate_fields(payload: dict[str, Any]) -> frozenset[tuple[str, ...]]:
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("provider") != "mcp" or not isinstance(data.get("raw"), dict):
        return frozenset()

    raw = data["raw"]
    fields: set[tuple[str, ...]] = set()
    for normalized, original in (("content", "content"), ("structured_content", "structuredContent")):
        if normalized in data and original in raw and _json(data[normalized]) == _json(raw[original]):
            fields.add(("data", "raw", original))
    if raw and all(("data", "raw", key) in fields for key in raw):
        fields.add(("data", "raw"))

    content = data.get("content")
    if isinstance(content, list) and "text" in data:
        text = "\n".join(block["text"] for block in content if isinstance(block, dict)
                         and block.get("type") == "text" and isinstance(block.get("text"), str))
        if data["text"] == (text or None):
            fields.add(("data", "text"))
    return frozenset(fields)


def project_mcp_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop only equal aliases, retaining distinct content and MCP metadata."""
    fields = _duplicate_fields(payload)
    if not fields:
        return payload
    data = {key: value for key, value in payload["data"].items() if ("data", key) not in fields}
    if "raw" in data:
        data["raw"] = {key: value for key, value in data["raw"].items() if ("data", "raw", key) not in fields}
    return {**payload, "data": data}


def _member_ranges(
    value: dict[str, Any], fields: frozenset[tuple[str, ...]], *,
    parent: tuple[str, ...] = (), first_line: int = 1,
) -> Iterator[range]:
    line = first_line + 1
    for key, child in sorted(value.items()):
        path = (*parent, key)
        # A member begins on the same line as the first line of its value.
        size = len(_json(key).splitlines()) - 1 + len(_json(child).splitlines())
        if path in fields:
            yield range(line, line + size)
        elif isinstance(child, dict) and any(field[:len(path)] == path for field in fields):
            yield from _member_ranges(child, fields, parent=path, first_line=line + len(_json(key).splitlines()) - 1)
        line += size


def mcp_duplicate_lines(payload: dict[str, Any]) -> frozenset[int]:
    """Locate omitted aliases in the original citation document's coordinates."""
    fields = _duplicate_fields(payload)
    if not fields:
        return frozenset()
    return frozenset(line for span in _member_ranges(payload, fields) for line in span)

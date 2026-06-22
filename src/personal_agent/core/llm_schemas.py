from __future__ import annotations

from copy import deepcopy
from typing import Any

from langchain_core.tools import BaseTool

_SYSTEM_TOOL_ARGS = {"user_id"}


def strict_json_schema_response(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Build an OpenAI Chat Completions strict json_schema response_format."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": strictify_schema(schema),
            "strict": True,
        },
    }


def structured_response_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Build a strict JSON Schema response format."""
    return strict_json_schema_response(name, schema)


def strip_json_fence(content: str) -> str:
    """Strip Markdown code fences around a JSON payload.

    Some models (e.g. reasoning models even under json_schema) wrap their
    structured output in ```json ... ``` fences instead of returning bare JSON.
    Return the inner payload so downstream JSON parsing succeeds; bare JSON is
    returned unchanged.
    """
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def strict_tool_definition(tool: BaseTool) -> dict[str, Any]:
    """Build an OpenAI Chat Completions tool definition from a LangChain tool."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": strictify_schema(_model_visible_tool_schema(tool)),
            "strict": True,
        },
    }


def _model_visible_tool_schema(tool: BaseTool) -> dict[str, Any]:
    if tool.args_schema is None:
        raw_schema: dict[str, Any] = {}
    elif isinstance(tool.args_schema, dict):
        raw_schema = tool.args_schema
    else:
        raw_schema = tool.args_schema.model_json_schema()
    schema = deepcopy(raw_schema or {"type": "object"})
    props = schema.get("properties")
    if isinstance(props, dict):
        for arg_name in _SYSTEM_TOOL_ARGS:
            props.pop(arg_name, None)
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [name for name in required if name not in _SYSTEM_TOOL_ARGS]
    return schema


def strictify_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize a JSON schema for strict OpenAI structured outputs/tool calls.

    OpenAI strict mode requires object schemas to disallow extra properties and
    list all declared properties as required. Optional values should be modeled
    explicitly with nullable types by the caller when needed.
    """
    normalized = deepcopy(schema)
    _strictify_node(normalized)
    return normalized


def _strictify_node(node: Any) -> None:
    if not isinstance(node, dict):
        return
    node.pop("default", None)
    node.pop("title", None)

    if node.get("type") == "object" or "properties" in node:
        props = node.get("properties")
        if isinstance(props, dict):
            node["required"] = list(props.keys())
            for child in props.values():
                _strictify_node(child)
        node["additionalProperties"] = False

    items = node.get("items")
    if isinstance(items, dict):
        _strictify_node(items)

    for defs_key in ("$defs", "definitions"):
        defs = node.get(defs_key)
        if isinstance(defs, dict):
            for child in defs.values():
                _strictify_node(child)

    for key in ("anyOf", "oneOf", "allOf"):
        variants = node.get(key)
        if isinstance(variants, list):
            for variant in variants:
                _strictify_node(variant)

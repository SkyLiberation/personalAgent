from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool


def tool_success(data: Any = None, evidence: list | None = None) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None, "evidence": evidence or []}


def tool_failure(error: str) -> dict[str, Any]:
    return {"ok": False, "data": None, "error": error, "evidence": []}


def tool_response(outcome: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    content = (
        json.dumps(outcome.get("data"), ensure_ascii=False, default=str)
        if outcome.get("ok")
        else str(outcome.get("error") or "工具执行失败。")
    )
    return content, outcome


def tool_schema(tool: BaseTool) -> dict[str, Any]:
    if tool.args_schema is None:
        return {}
    if isinstance(tool.args_schema, dict):
        return tool.args_schema
    return tool.args_schema.model_json_schema()


def tool_property(tool: BaseTool, name: str, default: Any = None) -> Any:
    return (tool.extras or {}).get(name, default)

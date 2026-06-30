from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.tools.base import governance_extras, tool_response, tool_success


class EnterpriseKnowledgeSearchArgs(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)
    user_id: str = "default"
    run_id: str | None = None


def build_enterprise_knowledge_search_tool(tool_executor) -> BaseTool:
    @tool(
        "enterprise_knowledge_search",
        description="Search approved enterprise knowledge sources and return normalized evidence.",
        args_schema=EnterpriseKnowledgeSearchArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="scoped_agent",
            side_effects=("read_longterm",),
            permission_scope="enterprise_knowledge:read",
            timeout_seconds=20,
            max_retries=1,
            retry_backoff_seconds=0.2,
        ),
    )
    def enterprise_knowledge_search(
        query: str,
        limit: int = 5,
        user_id: str = "default",
        run_id: str | None = None,
    ):
        results: list[dict[str, Any]] = []
        for source_tool in _enterprise_source_tools(tool_executor):
            if len(results) >= limit:
                break
            outcome = tool_executor.invoke_direct(
                source_tool.name,
                query=query,
                limit=max(1, limit - len(results)),
                user_id=user_id,
                run_id=run_id,
            )
            results.extend(_normalize_enterprise_results(source_tool.name, outcome))
        return tool_response(tool_success({
            "query": query,
            "results": _dedupe_results(results)[:limit],
        }))

    return enterprise_knowledge_search


def _enterprise_source_tools(tool_executor) -> list[BaseTool]:
    list_tools = getattr(tool_executor, "list_tools", None)
    if not callable(list_tools):
        return []
    tools: list[BaseTool] = []
    for candidate in list_tools():
        extras = getattr(candidate, "extras", None)
        if not isinstance(extras, dict):
            continue
        mcp = extras.get("mcp")
        if isinstance(mcp, dict) and mcp.get("business_role") == "enterprise_knowledge_search":
            tools.append(candidate)
            continue
        enterprise = extras.get("enterprise_knowledge")
        if (
            isinstance(enterprise, dict)
            and enterprise.get("business_role") == "enterprise_knowledge_search"
        ):
            tools.append(candidate)
    return tools


def _normalize_enterprise_results(tool_name: str, outcome: dict[str, Any]) -> list[dict[str, Any]]:
    if not outcome.get("ok"):
        return []
    data = outcome.get("data")
    if not isinstance(data, dict):
        return []
    candidates: list[Any] = []
    structured = data.get("structured_content")
    if isinstance(structured, dict):
        candidates.extend(_first_list(structured, "results", "items", "matches", "documents"))
    candidates.extend(_first_list(data, "results", "items", "matches", "documents"))
    text = data.get("text")
    if isinstance(text, str) and text.strip():
        candidates.append({"content": text})
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(candidates):
        if isinstance(item, dict):
            title = _first_str(item, "title", "name", "path", "id") or f"{tool_name} result {index + 1}"
            content = _first_str(item, "content", "text", "snippet", "summary", "body") or title
            result_id = _first_str(item, "id", "note_id", "document_id", "artifact_id") or f"{tool_name}:{index}"
            normalized.append({
                "id": result_id,
                "title": title,
                "content": content,
                "url": _first_str(item, "url", "source_url", "link"),
                "source": tool_name,
                "raw": item,
            })
        else:
            text_item = str(item)
            normalized.append({
                "id": f"{tool_name}:{index}",
                "title": text_item[:80],
                "content": text_item,
                "url": None,
                "source": tool_name,
                "raw": item,
            })
    return normalized


def _first_list(payload: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _first_str(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results:
        key = str(result.get("url") or result.get("id") or result.get("content") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


__all__ = ["build_enterprise_knowledge_search_tool"]

"""ReAct helpers, clarification/dialogue helpers, and small utilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import re
from langchain_core.messages import BaseMessage

from ._deps import OrchestrationDeps, _REACT_SYSTEM_PROMPT, _REACT_DEFAULT_ALLOWED_TOOLS, _REACT_BLOCKED_TOOL_PREFIXES

if TYPE_CHECKING:
    from ._deps import PlanStep

logger = logging.getLogger(__name__)

def _build_react_context(step: "PlanStep", step_results: dict) -> str:
    import json as _json

    parts: list[str] = []
    if step.tool_input:
        parts.append(f"步骤输入：{_json.dumps(step.tool_input, ensure_ascii=False)}")
    for sid, data in step_results.items():
        if isinstance(data, dict):
            summary = data.get("answer") or data.get("hint") or _json.dumps(data, ensure_ascii=False)[:200]
            parts.append(f"[{sid}] {summary}")
    return "\n".join(parts) if parts else "无"


def _format_react_tools(allowed: set[str], deps: OrchestrationDeps) -> str:
    lines: list[str] = []
    for spec in deps.tool_registry.list_tools():
        if spec.name in allowed:
            lines.append(f"- {spec.name}: {spec.description}")
            if spec.input_schema:
                props = spec.input_schema.get("properties", {})
                required = spec.input_schema.get("required", [])
                for pname, pdef in props.items():
                    req_mark = " (必填)" if pname in required else ""
                    desc = pdef.get("description", pdef.get("type", ""))
                    lines.append(f"    {pname}{req_mark}: {desc}")
    return "\n".join(lines) if lines else "无可用工具"


def _summarize_react_tool_result(data: object) -> str:
    import json as _json

    if data is None:
        return "（无返回数据）"
    if isinstance(data, dict):
        answer = data.get("answer")
        if answer:
            return str(answer)[:300]
        return _json.dumps(data, ensure_ascii=False)[:300]
    return str(data)[:300]


def _react_llm_respond(user_prompt: str, deps: OrchestrationDeps) -> str | None:
    from openai import OpenAI

    settings = deps.settings
    if not (settings.openai_api_key and settings.openai_base_url):
        return None
    try:
        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
        response = client.chat.completions.create(
            model=settings.openai_small_model,
            messages=[
                {"role": "system", "content": _REACT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        return (response.choices[0].message.content or "").strip() or None
    except Exception:
        logger.exception("ReAct LLM call failed")
        return None


def _react_parse_response(raw: str) -> dict | None:
    import json as _json

    try:
        return _json.loads(raw)
    except (_json.JSONDecodeError, TypeError):
        return None


def _solidify_note_text(raw: str) -> str:
    """Extract note content from a structured LLM solidification response."""
    parsed = _react_parse_response(raw)
    if not isinstance(parsed, dict):
        return ""
    result = parsed.get("result")
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, dict):
        title = str(result.get("标题") or result.get("title") or "").strip()
        body = str(
            result.get("正文") or result.get("content") or result.get("text") or ""
        ).strip()
        if title and body:
            return f"{title}\n\n{body}"
        return body or title
    answer = parsed.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer.strip()
    return ""


def _clarification_payload_parts(message: str, summary: str) -> dict:
    return {
        "message": message,
        "summary": summary,
        "options": [
            {
                "id": "capture",
                "label": "记录内容",
                "prompt": "请补充要写入知识库的具体内容。",
            },
            {
                "id": "ask",
                "label": "提出问题",
                "prompt": "请补充你想查询或追问的问题。",
            },
            {
                "id": "summarize",
                "label": "总结内容",
                "prompt": "请补充要总结的文本、会话或范围。",
            },
            {
                "id": "action",
                "label": "执行操作",
                "prompt": "请补充要执行的操作和对象，例如要删除哪条笔记。",
            },
        ],
    }


def _resume_value_get(value: object, key: str, default: object = None) -> object:
    if isinstance(value, dict):
        return value.get(key, default)
    return default


def _merge_clarification_text(original: str, supplemental: str, option_id: str) -> str:
    prefix_map = {
        "capture": "记一下：",
        "ask": "请问：",
        "summarize": "总结：",
        "action": "",
    }
    prefix = prefix_map.get(option_id, "")
    if prefix and not supplemental.startswith(prefix):
        return f"{prefix}{supplemental}"
    if original.strip() and original.strip() not in {"帮我", "帮我看看", "看看", "处理一下", "继续"}:
        return f"{original.strip()} {supplemental}".strip()
    return supplemental


def _dialogue_history(messages: list[BaseMessage], *, exclude_latest: bool = False) -> list[BaseMessage]:
    """Return recent user-visible dialogue messages for prompt context."""
    history = messages[:-1] if exclude_latest and messages else messages
    return [message for message in history[-12:] if message.type in {"human", "ai"}]


def _dialogue_prompt_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    return [
        {
            "role": "assistant" if message.type == "ai" else "user",
            "content": str(message.content),
        }
        for message in _dialogue_history(messages)
    ]


def _format_dialogue_context(messages: list[BaseMessage], *, exclude_latest: bool = False) -> str:
    lines: list[str] = []
    for message in _dialogue_history(messages, exclude_latest=exclude_latest):
        label = "用户" if message.type == "human" else "助手"
        lines.append(f"{label}: {message.content}")
    return "\n".join(lines)


def _format_solidify_candidate_context(messages: list[BaseMessage]) -> str:
    """Render candidate dialogue turns for model-driven solidification."""
    history = _dialogue_history(messages, exclude_latest=True)
    if not history:
        return ""
    turns: list[list[BaseMessage]] = []
    for message in history:
        if message.type == "human" or not turns:
            turns.append([message])
        else:
            turns[-1].append(message)

    lines: list[str] = []
    for index, turn in enumerate(turns, start=1):
        for message in turn:
            label = "用户" if message.type == "human" else "助手"
            lines.append(f"[turn-{index}] {label}: {message.content}")
    return "\n".join(lines)
def _first_url(text: str) -> str | None:
    import re

    match = re.search(r"https?://\S+", text)
    if match is None:
        return None
    return match.group(0).rstrip(".,);]}>\"'")


def _summarize_result(data: object) -> str:
    if data is None:
        return "无结果"
    if isinstance(data, dict):
        answer = data.get("answer", "")
        if answer:
            return str(answer)[:100]
        return "已获取结果"
    if isinstance(data, str):
        return data[:100]
    return str(data)[:100]


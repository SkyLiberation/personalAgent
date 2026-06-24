"""ReAct helpers, clarification/dialogue helpers, and small utilities."""

from __future__ import annotations

import logging
import json
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage

from personal_agent.agent.orchestration_contexts import ReactContext
from personal_agent.agent.orchestration_nodes._graph_helpers import _REACT_SYSTEM_PROMPT
from personal_agent.kernel.llm_schemas import structured_response_format, strict_tool_definition, strip_json_fence
from personal_agent.kernel.prompts import get_prompt

if TYPE_CHECKING:
    from personal_agent.agent.orchestration_nodes._deps import ExecutionStep
    from personal_agent.kernel.config import ShortTermMemoryConfig

logger = logging.getLogger(__name__)

def _build_react_context(step: "ExecutionStep", results: dict) -> str:
    import json as _json

    parts: list[str] = []
    if step.tool_input:
        parts.append(f"步骤输入：{_json.dumps(step.tool_input, ensure_ascii=False)}")
    for sid, data in results.items():
        if isinstance(data, dict):
            summary = data.get("answer") or data.get("hint") or _json.dumps(data, ensure_ascii=False)[:200]
            parts.append(f"[{sid}] {summary}")
    return "\n".join(parts) if parts else "无"


def _format_react_tools(allowed: set[str], deps: ReactContext) -> str:
    lines: list[str] = []
    from personal_agent.tools import tool_schema
    for spec in deps.tool_executor.list_tools():
        if spec.name in allowed:
            lines.append(f"- {spec.name}: {spec.description}")
            schema = tool_schema(spec)
            if schema:
                props = schema.get("properties", {})
                required = schema.get("required", [])
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


_FINISH_REACT_TOOL = {
    "type": "function",
    "function": {
        "name": "finish_react",
        "description": "结束当前 ReAct 步骤，并返回最终答案。",
        "parameters": {
            "type": "object",
            "properties": {
                "thought": {"type": "string", "description": "简短说明为什么可以结束。"},
                "answer": {"type": "string", "description": "本步骤的最终答案或结构化结果摘要。"},
            },
            "required": ["thought", "answer"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


def _react_llm_respond(
    user_prompt: str,
    deps: ReactContext,
    allowed_tools: set[str] | None = None,
) -> str | None:
    from personal_agent.kernel.llm_trace import traced_chat_completion

    settings = deps.settings
    if not (settings.openai.api_key and settings.openai.base_url):
        return None
    tools = None
    if allowed_tools is not None:
        tool_defs = [
            strict_tool_definition(spec)
            for spec in deps.tool_executor.list_tools()
            if spec.name in allowed_tools
        ]
        tools = tool_defs + [_FINISH_REACT_TOOL]
    try:
        react_prompt = get_prompt("react.system")
        result = traced_chat_completion(
            settings.openai,
            prompt_name="react",
            prompt_version=react_prompt.version,
            messages=[
                {"role": "system", "content": _REACT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=400,
            tools=tools,
            tool_choice="auto" if tools else None,
            metadata={"component": "react"},
            upload_inputs_outputs=settings.langsmith.upload_inputs,
        )
        if result.tool_calls:
            call = result.tool_calls[0]
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict):
                return None
            name = str(function.get("name") or "")
            try:
                arguments = json.loads(str(function.get("arguments") or "{}"))
            except json.JSONDecodeError:
                arguments = {}
            if name == "finish_react":
                return json.dumps({
                    "thought": str(arguments.get("thought") or ""),
                    "done": True,
                    "result": {"answer": str(arguments.get("answer") or "")},
                }, ensure_ascii=False)
            return json.dumps({
                "thought": str(arguments.pop("thought", "")),
                "tool": name,
                "input": arguments,
            }, ensure_ascii=False)
        return result.content or None
    except Exception:
        logger.exception("ReAct LLM call failed")
        return None


def _structured_llm_respond(
    prompt_name: str,
    user_prompt: str,
    deps: ReactContext,
    schema: dict,
    *,
    max_tokens: int = 500,
) -> str | None:
    from personal_agent.kernel.llm_trace import traced_chat_completion

    settings = deps.settings
    structured = settings.structured
    if not (structured.api_key and structured.base_url):
        return _react_llm_respond(user_prompt, deps)
    try:
        system_prompt = get_prompt("structured.system")
        try:
            prompt_version = get_prompt(f"{prompt_name}.user").version
        except KeyError:
            prompt_version = system_prompt.version
        result = traced_chat_completion(
            structured,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            messages=[
                {"role": "system", "content": system_prompt.template},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=max_tokens,
            response_format=structured_response_format(prompt_name, schema),
            metadata={"component": prompt_name},
            upload_inputs_outputs=settings.langsmith.upload_inputs,
            extra_body=structured.extra_body or None,
        )
        return strip_json_fence(result.content) if result.content else _react_llm_respond(user_prompt, deps)
    except Exception:
        logger.exception("Structured LLM call failed: %s", prompt_name)
        return _react_llm_respond(user_prompt, deps)


def _react_parse_response(raw: str) -> dict | None:
    """Unwrap a ReAct / structured-node JSON envelope into a dict (or None).

    Shape varies (react action, finish, or a structured draft), so this stays a
    permissive dict rather than a fixed schema; it shares the fence/truncation
    unwrap and parse telemetry with every other structured site.
    """
    from personal_agent.kernel.llm_trace import log_llm_parse
    from personal_agent.core.structured_parse import load_json_lenient

    try:
        parsed = load_json_lenient(raw)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        log_llm_parse(
            prompt_name="react",
            model="unknown",
            parse_ok=False,
            parse_schema="ReactAction",
            parse_error=str(exc),
        )
        return None
    ok = isinstance(parsed, dict)
    log_llm_parse(
        prompt_name="react",
        model="unknown",
        parse_ok=ok,
        parse_schema="ReactAction",
        parse_error="" if ok else "parsed value is not object",
    )
    return parsed if ok else None


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


def _dialogue_history(
    messages: list[BaseMessage],
    *,
    exclude_latest: bool = False,
    cfg: "ShortTermMemoryConfig | None" = None,
) -> list[BaseMessage]:
    """Return recent user-visible dialogue messages for prompt context."""
    from personal_agent.kernel.config import ShortTermMemoryConfig

    max_messages = (cfg or ShortTermMemoryConfig()).max_messages
    history = messages[:-1] if exclude_latest and messages else messages
    return [
        message
        for message in history[-max_messages:]
        if message.type in {"human", "ai"}
    ]


def _dialogue_prompt_messages(
    messages: list[BaseMessage],
    *,
    exclude_latest: bool = False,
    cfg: "ShortTermMemoryConfig | None" = None,
) -> list[dict[str, str]]:
    """Token-budgeted, single-message-truncated dialogue window for prompts."""
    from personal_agent.kernel.config import ShortTermMemoryConfig
    from personal_agent.agent.short_term_context import apply_window

    window = apply_window(
        messages, cfg or ShortTermMemoryConfig(), exclude_latest=exclude_latest
    )
    return window.kept


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

"""ReAct helpers, clarification/dialogue helpers, and small utilities."""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage

from personal_agent.orchestration.orchestration_contexts import ReactContext
from personal_agent.orchestration.orchestration_nodes._graph_helpers import _REACT_SYSTEM_PROMPT
from personal_agent.kernel.llm_schemas import (
    model_tool_wire_name,
    structured_response_format,
    strict_tool_definition,
    strip_json_fence,
)
from personal_agent.kernel.prompts import get_prompt

if TYPE_CHECKING:
    from personal_agent.kernel.config import ShortTermMemoryConfig

logger = logging.getLogger(__name__)

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
        "description": "结束当前 ReAct 步骤，并返回最终答案；若后续存在 commit 步骤，可附带待确认的状态变更提议。",
        "parameters": {
            "type": "object",
            "properties": {
                "thought": {"type": "string", "description": "简短说明为什么可以结束。"},
                "answer": {"type": "string", "description": "本步骤的最终答案或结构化结果摘要。"},
                "proposed_commit": {
                    "type": ["object", "null"],
                    "properties": {
                        "tool_name": {"type": "string"},
                        "tool_input": {"type": "object"},
                    },
                    "required": ["tool_name", "tool_input"],
                    "additionalProperties": False,
                },
            },
            "required": ["thought", "answer"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


@dataclass(slots=True)
class _NativeReactOutcome:
    """模型原生 tool-calling 调用的结构化结果，不经过 JSON 信封字符串.

    ReAct 迭代节点直接消费此结构构造 ``AIMessage``，消除 ``json.dumps`` 信封
    与 ``_react_parse_response`` 的二次字符串解析。``native_call_id`` 直接用
    作 ``tool_call_id`` 与 ``pending_call_id``，对齐模型视角。
    """

    done: bool = False
    thought: str = ""
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    native_call_id: str | None = None
    result: dict[str, Any] | None = None
    parse_failed: bool = False


def _react_llm_native(
    user_prompt: str,
    deps: ReactContext,
    allowed_tools: set[str],
) -> _NativeReactOutcome | None:
    """调用模型原生 tool-calling 接口并返回结构化 outcome.

    通过 ``StructuredModelClient`` port 发起 ``tool_calling`` 请求，应用层不
    依赖 ``OpenAI`` / ``traced_chat_completion``。返回 ``_NativeReactOutcome``
    而非 JSON 字符串，避免 ``json.dumps`` → ``_react_parse_response`` 的有损
    往返。模型原生 ``tool_calls`` 的结构化保证
    （schema 校验、call_id、parallel calls）被直接保留。
    """
    from personal_agent.capabilities.contracts.model import (
        StructuredModelRequest,
        sealed_context_projection_ref,
    )
    from pydantic import BaseModel

    if deps.model_client is None:
        return None

    selected_specs = [
        spec for spec in deps.tool_executor.list_tools() if spec.name in allowed_tools
    ]
    wire_to_canonical = {
        model_tool_wire_name(spec.name): spec.name for spec in selected_specs
    }
    if len(wire_to_canonical) != len(selected_specs):
        raise ValueError("model tool wire-name collision")
    tool_defs = []
    for spec in selected_specs:
        definition = strict_tool_definition(spec)
        function = definition["function"]
        wire_name = model_tool_wire_name(spec.name)
        function["name"] = wire_name
        if wire_name != spec.name:
            function["description"] = (
                f"Canonical tool: {spec.name}. {function['description']}"
            )
        tool_defs.append(definition)
    tools = tool_defs + [_FINISH_REACT_TOOL]
    try:
        react_prompt = get_prompt("react.system")
        messages = [
            {"role": "system", "content": _REACT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        response = deps.model_client.generate(StructuredModelRequest(
            operation="react",
            version=react_prompt.version,
            messages=messages,
            output_type=BaseModel,
            context_projection_ref=sealed_context_projection_ref(
                purpose="react", messages=messages,
            ),
            temperature=0,
            max_tokens=400,
            kind="tool_calling",
            tools=tools,
            tool_choice="auto",
            metadata={"component": "react"},
        ))
    except Exception:
        logger.exception("Native ReAct LLM call failed")
        return None

    tool_calls = response.tool_calls or []
    if tool_calls:
        call = tool_calls[0]
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            return _NativeReactOutcome(parse_failed=True)
        wire_name = str(function.get("name") or "")
        try:
            arguments = json.loads(str(function.get("arguments") or "{}"))
        except json.JSONDecodeError:
            arguments = {}
        native_id = str(call.get("id") or "")
        if wire_name == "finish_react":
            return _NativeReactOutcome(
                done=True,
                thought=str(arguments.get("thought") or ""),
                result={
                    "answer": str(arguments.get("answer") or ""),
                    "proposed_commit": arguments.get("proposed_commit"),
                },
            )
        canonical_name = wire_to_canonical.get(wire_name)
        if canonical_name is None:
            return _NativeReactOutcome(parse_failed=True)
        if not isinstance(arguments, dict):
            arguments = {}
        thought = str(arguments.pop("thought", ""))
        return _NativeReactOutcome(
            thought=thought,
            tool_name=canonical_name,
            tool_input=arguments,
            native_call_id=native_id or None,
        )

    return _NativeReactOutcome(parse_failed=True)


def _structured_llm_respond(
    prompt_name: str,
    user_prompt: str,
    deps: ReactContext,
    schema: dict,
    *,
    max_tokens: int = 500,
) -> str | None:
    """Structured-output LLM call for step decisions (delete candidate resolve,
    solidify draft, etc.).

    Uses the ``structured_client`` port with strict ``json_schema``. Returns a
    JSON string consumed by ``_react_parse_response`` because these step
    decisions parse permissive dict shapes rather than a single Pydantic model.
    """
    from personal_agent.capabilities.contracts.model import (
        StructuredModelRequest,
        sealed_context_projection_ref,
    )
    from pydantic import BaseModel

    system_prompt = get_prompt("structured.system")
    try:
        prompt_version = get_prompt(f"{prompt_name}.user").version
    except KeyError:
        prompt_version = system_prompt.version

    messages = [
        {"role": "system", "content": system_prompt.template},
        {"role": "user", "content": user_prompt},
    ]
    request = StructuredModelRequest(
        operation=prompt_name,
        version=prompt_version,
        messages=messages,
        output_type=BaseModel,
        context_projection_ref=sealed_context_projection_ref(
            purpose=prompt_name, messages=messages,
        ),
        temperature=0,
        max_tokens=max_tokens,
        kind="structured",
        response_format=structured_response_format(prompt_name, schema),
        metadata={"component": prompt_name},
    )

    if deps.structured_client is None:
        return None
    try:
        response = deps.structured_client.generate(request)
        content = (response.content or "").strip()
        if content:
            return strip_json_fence(content)
    except Exception:
        logger.exception("Structured LLM call failed: %s", prompt_name)
    return None


def _react_parse_response(raw: str) -> dict | None:
    """Unwrap a ReAct / structured-node JSON envelope into a dict (or None).

    Shape varies (react action, finish, or a structured draft), so this stays a
    permissive dict rather than a fixed schema; it shares the fence/truncation
    unwrap and parse telemetry with every other structured site.
    """
    from personal_agent.kernel.llm_trace import log_llm_parse
    from personal_agent.kernel.structured_parse import load_json_lenient

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
    from personal_agent.memory.short_term_context import apply_window

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

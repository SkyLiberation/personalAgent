"""Controlled ReAct (Thought/Action/Observation) step runner.

Runs inside a single PlanExecutor step to enable dynamic tool selection
and observation-driven iteration.  Constraints:
- Only ``allowed_tools`` may be called (defaults to read-only search tools).
- High-risk / write tools are blocked even if listed.
- Loop is capped at ``max_iterations``.
- Every iteration emits a ``react_iteration`` progress event.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from openai import OpenAI

from ..core.config import Settings
from ..tools import ToolRegistry
from .planner import PlanStep

if TYPE_CHECKING:
    from ..core.models import AgentState
    from ..memory import MemoryFacade
    from .plan_executor import ProgressCallback

logger = logging.getLogger(__name__)

BLOCKED_TOOL_PREFIXES = ("delete_", "capture_")
DEFAULT_ALLOWED_TOOLS = ("graph_search", "web_search")
MAX_ITERATIONS_CAP = 5

_REACT_SYSTEM_PROMPT = (
    "你是一个在受控环境中执行任务步骤的推理助手。"
    "每一轮你需要输出 JSON：\n"
    '- 仍在推理：{"thought":"...","tool":"工具名","input":{...}}\n'
    '- 已完成：{"thought":"...","done":true,"result":{...}}\n\n'
    "tool 必须在可用工具列表中。result 应包含步骤产出的结构化数据。\n"
    "不要输出 JSON 以外的内容。"
)


@dataclass(slots=True)
class ReActIteration:
    thought: str
    action_tool: str
    action_input: dict
    observation: str


class ReActStepRunner:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        memory: MemoryFacade,
        settings: Settings,
    ) -> None:
        self._registry = tool_registry
        self._memory = memory
        self._settings = settings

    # ---- public API ----

    def run(
        self,
        step: PlanStep,
        state: AgentState,
        prior_results: dict[str, object],
        on_progress: ProgressCallback,
    ) -> dict:
        """Execute a single step with the ReAct loop.  Returns a result dict."""
        allowed = self._resolve_allowed_tools(step)
        iterations: list[ReActIteration] = []
        context_block = self._build_context(step, prior_results)
        tools_block = self._format_tools(allowed)
        max_iter = min(step.max_iterations, MAX_ITERATIONS_CAP)
        user_prompt = (
            f"## 步骤描述\n{step.description}\n\n"
            f"## 已有上下文\n{context_block}\n\n"
            f"## 可用工具\n{tools_block}\n\n"
            f"请开始推理（最多 {max_iter} 轮）。"
        )

        for i in range(max_iter):
            raw = self._llm_respond(user_prompt)
            if raw is None:
                logger.warning("ReAct LLM returned nothing at iteration %d for step %s", i, step.step_id)
                break

            parsed = self._parse_response(raw)
            if parsed is None:
                iterations.append(ReActIteration(
                    thought="", action_tool="", action_input={},
                    observation="LLM 输出无法解析为 JSON，跳过此轮。",
                ))
                user_prompt += f"\n\n观察：LLM 输出无法解析，请重新输出 JSON。"
                self._emit_iteration(on_progress, step.step_id, i, iterations[-1])
                continue

            if parsed.get("done"):
                self._memory.working.add_step(
                    f"ReAct 完成: [{step.step_id}] {parsed.get('thought', '')[:80]}"
                )
                result = parsed.get("result", {})
                if isinstance(result, dict):
                    return result
                return {"answer": str(result)}

            tool_name = str(parsed.get("tool", ""))
            tool_input = parsed.get("input", {})
            thought = str(parsed.get("thought", ""))

            if not tool_name:
                observation = "错误：未指定工具名。请输出合法 JSON。"
            elif tool_name not in allowed:
                observation = f"错误：工具 '{tool_name}' 不在允许列表 {list(allowed)} 中。"
            elif self._is_blocked_tool(tool_name):
                observation = f"错误：工具 '{tool_name}' 是高风险/写操作工具，不允许在 ReAct 中调用。"
            else:
                tool_result = self._registry.execute(tool_name, **tool_input)
                if tool_result.ok:
                    observation = self._summarize_tool_result(tool_result.data)
                else:
                    observation = f"工具执行失败：{tool_result.error}"

            iterations.append(ReActIteration(
                thought=thought, action_tool=tool_name,
                action_input=tool_input if isinstance(tool_input, dict) else {},
                observation=observation,
            ))
            self._emit_iteration(on_progress, step.step_id, i, iterations[-1])
            self._memory.working.add_step(
                f"ReAct 轮次 {i + 1}/{max_iter}: [{step.step_id}] "
                f"thought={thought[:60]} tool={tool_name}"
            )

            user_prompt += f"\n\n思考：{thought}\n动作：{tool_name}({json.dumps(tool_input, ensure_ascii=False) if isinstance(tool_input, dict) else tool_input})\n观察：{observation}"

        # Exhausted iterations — return collected observations
        final_observations = [it.observation for it in iterations if it.observation]
        return {
            "answer": "\n".join(final_observations) if final_observations else "",
            "react_iterations": len(iterations),
        }

    # ---- internals ----

    def _resolve_allowed_tools(self, step: PlanStep) -> set[str]:
        allowed = set(step.allowed_tools) if step.allowed_tools else set(DEFAULT_ALLOWED_TOOLS)
        registered = {t.name for t in self._registry.list_tools()}
        return allowed & registered

    def _is_blocked_tool(self, tool_name: str) -> bool:
        spec = None
        for t in self._registry.list_tools():
            if t.name == tool_name:
                spec = t
                break
        if spec is None:
            return True
        if spec.risk_level == "high" or spec.requires_confirmation or spec.writes_longterm:
            return True
        if any(tool_name.startswith(p) for p in BLOCKED_TOOL_PREFIXES):
            return True
        return False

    def _build_context(self, step: PlanStep, prior_results: dict[str, object]) -> str:
        parts: list[str] = []
        if step.tool_input:
            parts.append(f"步骤输入：{json.dumps(step.tool_input, ensure_ascii=False)}")
        for sid, data in prior_results.items():
            if isinstance(data, dict):
                summary = data.get("answer") or data.get("hint") or json.dumps(data, ensure_ascii=False)[:200]
                parts.append(f"[{sid}] {summary}")
        return "\n".join(parts) if parts else "无"

    def _format_tools(self, allowed: set[str]) -> str:
        lines: list[str] = []
        for spec in self._registry.list_tools():
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

    def _llm_respond(self, user_prompt: str) -> str | None:
        if not (self._settings.openai_api_key and self._settings.openai_base_url):
            return None
        try:
            client = OpenAI(
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url,
            )
            response = client.chat.completions.create(
                model=self._settings.openai_small_model,
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

    @staticmethod
    def _parse_response(raw: str) -> dict | None:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _summarize_tool_result(data: object) -> str:
        if data is None:
            return "（无返回数据）"
        if isinstance(data, dict):
            answer = data.get("answer")
            if answer:
                return str(answer)[:300]
            return json.dumps(data, ensure_ascii=False)[:300]
        return str(data)[:300]

    @staticmethod
    def _emit_iteration(
        on_progress: ProgressCallback,
        step_id: str,
        iteration: int,
        it: ReActIteration,
    ) -> None:
        if on_progress is not None:
            try:
                on_progress("react_iteration", {
                    "step_id": step_id,
                    "iteration": iteration,
                    "thought": it.thought[:200],
                    "action_tool": it.action_tool,
                    "action_input": it.action_input,
                    "observation": it.observation[:300],
                })
            except Exception:
                logger.exception("Progress callback failed for react_iteration")

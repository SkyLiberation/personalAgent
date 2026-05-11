from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

from openai import OpenAI

from ..core.config import Settings
from ..core.models import EntryIntent
from ..tools import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlanStep:
    step: str  # "retrieve", "tool_call", "compose", "verify"
    tool: str | None = None
    params: dict[str, object] = field(default_factory=dict)


class TaskPlanner(Protocol):
    def plan(self, intent: EntryIntent, context: str) -> list[PlanStep]:
        ...


class DefaultTaskPlanner:
    """LLM-first task planner with heuristic fallback.

    Decomposes a user intent into a sequence of executable steps.
    Currently supports capture, ask, and summarize task types.
    """

    def __init__(self, settings: Settings, tool_registry: ToolRegistry | None = None) -> None:
        self._settings = settings
        self._tool_registry = tool_registry

    def plan(self, intent: EntryIntent, context: str = "") -> list[PlanStep]:
        llm_result = self._plan_with_llm(intent, context)
        if llm_result is not None:
            return llm_result
        return self._plan_heuristic(intent)

    def _plan_with_llm(self, intent: EntryIntent, context: str) -> list[PlanStep] | None:
        if not self._llm_configured:
            return None

        tool_list = ""
        if self._tool_registry is not None:
            specs = self._tool_registry.list_tools()
            if specs:
                tool_list = "\n".join(f"- {s.name}: {s.description}" for s in specs)

        prompt = (
            "你是一个任务规划器。请根据用户意图，将任务分解为一系列执行步骤。"
            "可用步骤类型: retrieve(检索), tool_call(调用工具), compose(生成回答), verify(校验)。"
            "只返回 JSON 数组，每个元素包含 step, tool(nullable), params(对象)。"
            f"意图: {intent}\n"
            f"上下文: {context or '无'}\n"
            f"可用工具:\n{tool_list or '无'}"
        )
        try:
            client = OpenAI(api_key=self._settings.openai_api_key, base_url=self._settings.openai_base_url)
            response = client.chat.completions.create(
                model=self._settings.openai_small_model,
                messages=[
                    {"role": "system", "content": "你是一个严谨的任务规划器，只输出 JSON 数组。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            payload = json.loads(content)
            steps_data = payload if isinstance(payload, list) else payload.get("steps", [])
            if not isinstance(steps_data, list):
                return None
            steps: list[PlanStep] = []
            for item in steps_data:
                if not isinstance(item, dict):
                    continue
                step_name = str(item.get("step") or "")
                if step_name not in {"retrieve", "tool_call", "compose", "verify"}:
                    continue
                tool = item.get("tool")
                steps.append(PlanStep(
                    step=step_name,
                    tool=str(tool) if tool else None,
                    params=item.get("params") if isinstance(item.get("params"), dict) else {},
                ))
            return steps if steps else None
        except Exception:
            logger.exception("Failed to plan with LLM, falling back to heuristic")
            return None

    def _plan_heuristic(self, intent: EntryIntent) -> list[PlanStep]:
        if intent in ("capture_text", "capture_link", "capture_file"):
            return [
                PlanStep(step="tool_call", tool="capture_url" if intent == "capture_link" else None),
                PlanStep(step="compose"),
                PlanStep(step="verify"),
            ]
        if intent == "ask":
            return [
                PlanStep(step="retrieve", tool="graph_search"),
                PlanStep(step="compose"),
                PlanStep(step="verify"),
            ]
        if intent == "summarize_thread":
            return [
                PlanStep(step="retrieve"),
                PlanStep(step="compose"),
            ]
        return [PlanStep(step="compose")]

    @property
    def _llm_configured(self) -> bool:
        return bool(
            self._settings.openai_api_key
            and self._settings.openai_base_url
            and self._settings.openai_small_model
        )

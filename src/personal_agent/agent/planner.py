from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from openai import OpenAI

from ..core.config import Settings
from ..core.models import EntryIntent
from ..tools import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlanStep:
    """A single step in a task plan with execution metadata.

    action_type: "retrieve", "tool_call", "compose", or "verify"
    status: "planned" (initial) -> "running" -> "completed" / "failed" / "skipped"
    """

    step_id: str = field(default_factory=lambda: uuid4().hex[:8])
    action_type: str = ""  # retrieve / tool_call / compose / verify
    description: str = ""  # user-visible label
    tool_name: str | None = None
    tool_input: dict[str, object] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    expected_output: str = ""
    success_criteria: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = False
    on_failure: str = "skip"  # skip / retry / abort
    status: str = "planned"  # planned / running / completed / failed / skipped
    retry_count: int = 0


class TaskPlanner(Protocol):
    def plan(self, intent: EntryIntent, context: str) -> list[PlanStep]:
        ...


class DefaultTaskPlanner:
    """LLM-first task planner with heuristic fallback.

    Decomposes a user intent into a sequence of executable steps.
    Currently supports capture, ask, summarize, delete_knowledge,
    and solidify_conversation task types.
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
            "可用 action_type: retrieve(检索), tool_call(调用工具), compose(生成回答), verify(校验)。"
            "只返回 JSON 数组，每个元素包含以下字段：\n"
            "  step_id(短标识), action_type, description(对用户友好的中文说明),\n"
            "  tool_name(nullable), tool_input(对象, nullable),\n"
            "  depends_on(前置步骤 step_id 数组),\n"
            "  expected_output(期望产出), success_criteria(成功标准),\n"
            "  risk_level(low/medium/high), requires_confirmation(bool),\n"
            "  on_failure(skip/retry/abort)。\n"
            "description 应该用自然语言向用户说明这一步要做什么，不要只写枚举值。\n"
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
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            payload = json.loads(content)
            steps_data = payload if isinstance(payload, list) else payload.get("steps", [])
            if not isinstance(steps_data, list):
                return None
            steps: list[PlanStep] = []
            valid_actions = {"retrieve", "tool_call", "compose", "verify"}
            for item in steps_data:
                if not isinstance(item, dict):
                    continue
                action = str(item.get("action_type") or item.get("step") or "")
                if action not in valid_actions:
                    continue
                tool = item.get("tool_name") or item.get("tool")
                tool_input = item.get("tool_input") or item.get("params") or {}
                if not isinstance(tool_input, dict):
                    tool_input = {}
                depends_on = item.get("depends_on", [])
                if not isinstance(depends_on, list):
                    depends_on = []
                risk = str(item.get("risk_level", "low"))
                steps.append(PlanStep(
                    step_id=str(item.get("step_id") or uuid4().hex[:8]),
                    action_type=action,
                    description=str(item.get("description") or ""),
                    tool_name=str(tool) if tool else None,
                    tool_input=tool_input,
                    depends_on=depends_on,
                    expected_output=str(item.get("expected_output") or ""),
                    success_criteria=str(item.get("success_criteria") or ""),
                    risk_level=risk if risk in ("low", "medium", "high") else "low",
                    requires_confirmation=bool(item.get("requires_confirmation", False)),
                    on_failure=str(item.get("on_failure") or "skip"),
                ))
            return steps if steps else None
        except Exception:
            logger.exception("Failed to plan with LLM, falling back to heuristic")
            return None

    def _plan_heuristic(self, intent: EntryIntent) -> list[PlanStep]:
        if intent in ("capture_text", "capture_link", "capture_file"):
            return [
                PlanStep(
                    step_id="cap-1", action_type="tool_call",
                    description="采集内容并写入知识库",
                    tool_name="capture_url" if intent == "capture_link" else f"capture_{intent.rsplit('_', 1)[1]}",
                    expected_output="生成一条 KnowledgeNote",
                    success_criteria="笔记已持久化存储",
                ),
                PlanStep(
                    step_id="cap-2", action_type="compose",
                    description="整理采集结果，生成标题和摘要",
                    expected_output="包含标题和摘要的笔记",
                    depends_on=["cap-1"],
                ),
                PlanStep(
                    step_id="cap-3", action_type="verify",
                    description="校验笔记完整性和格式",
                    expected_output="确认笔记可被后续检索使用",
                    depends_on=["cap-2"],
                ),
            ]
        if intent == "ask":
            return [
                PlanStep(
                    step_id="ask-1", action_type="retrieve",
                    description="在知识库和图谱中检索相关内容",
                    tool_name="graph_search",
                    expected_output="匹配的笔记和引用片段列表",
                    success_criteria="命中至少 1 条相关笔记或图谱事实",
                ),
                PlanStep(
                    step_id="ask-2", action_type="compose",
                    description="整合检索到的证据，生成自然语言回答",
                    expected_output="一段有据可查的中文回答",
                    depends_on=["ask-1"],
                ),
                PlanStep(
                    step_id="ask-3", action_type="verify",
                    description="校验回答的事实依据和引用完整性",
                    expected_output="通过校验或标注不确定点",
                    depends_on=["ask-2"],
                ),
            ]
        if intent == "summarize_thread":
            return [
                PlanStep(
                    step_id="sum-1", action_type="retrieve",
                    description="获取群聊消息记录",
                    expected_output="最近消息列表",
                ),
                PlanStep(
                    step_id="sum-2", action_type="compose",
                    description="按主题分点总结讨论要点和结论",
                    expected_output="结构化的群聊总结",
                    depends_on=["sum-1"],
                ),
            ]
        if intent == "delete_knowledge":
            return [
                PlanStep(
                    step_id="del-1", action_type="retrieve",
                    description="检索待删除的候选笔记",
                    tool_name="graph_search",
                    expected_output="匹配的候选笔记列表",
                    success_criteria="命中至少 1 条笔记",
                ),
                PlanStep(
                    step_id="del-2", action_type="verify",
                    description="安全校验：确认删除目标、检查误删风险",
                    expected_output="安全校验通过或返回待确认列表",
                    risk_level="high",
                    requires_confirmation=True,
                    depends_on=["del-1"],
                ),
                PlanStep(
                    step_id="del-3", action_type="tool_call",
                    description="执行删除：移除笔记、复习卡和图谱映射",
                    tool_name="delete_note",
                    expected_output="已删除的笔记 ID 列表",
                    risk_level="high",
                    requires_confirmation=True,
                    depends_on=["del-2"],
                ),
                PlanStep(
                    step_id="del-4", action_type="compose",
                    description="生成删除结果摘要",
                    expected_output="已删除 / 未找到 / 待确认 的结构化结果",
                    depends_on=["del-3"],
                ),
            ]
        if intent == "solidify_conversation":
            return [
                PlanStep(
                    step_id="sol-1", action_type="retrieve",
                    description="加载最近对话轮次，抽取候选事实和结论",
                    expected_output="候选知识要点列表",
                    success_criteria="至少提取到 1 条可固化的结论",
                ),
                PlanStep(
                    step_id="sol-2", action_type="compose",
                    description="将候选结论整理为适合入库的知识文本",
                    expected_output="格式化的知识笔记草稿",
                    depends_on=["sol-1"],
                ),
                PlanStep(
                    step_id="sol-3", action_type="verify",
                    description="检查整理后的知识文本是否准确、完整",
                    expected_output="通过校验或返回修改建议",
                    depends_on=["sol-2"],
                ),
                PlanStep(
                    step_id="sol-4", action_type="tool_call",
                    description="将知识文本写入知识库（复用 capture 链路）",
                    tool_name="capture_text",
                    expected_output="已持久化的 KnowledgeNote",
                    depends_on=["sol-3"],
                ),
            ]
        return [
            PlanStep(
                step_id="unk-1", action_type="compose",
                description="生成通用回复",
            ),
        ]

    @property
    def _llm_configured(self) -> bool:
        return bool(
            self._settings.openai_api_key
            and self._settings.openai_base_url
            and self._settings.openai_small_model
        )

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from openai import OpenAI

from ..core.config import Settings
from ..core.models import EntryIntent
from ..tools import ToolExecutor

logger = logging.getLogger(__name__)


def _maybe_import_capture():
    try:
        scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from capture_planner_llm import write_plan_capture
        return write_plan_capture
    except Exception:
        return None


@dataclass(slots=True)
class PlanStep:
    """A single step in a task plan with execution metadata.

    action_type: "retrieve", "tool_call", "compose", or "verify"
    status: "planned" (initial) -> "running" -> "completed" / "failed" / "skipped"
    """

    step_id: str = field(default_factory=lambda: uuid4().hex[:8])
    action_type: str = ""  # retrieve / resolve / tool_call / compose / verify
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
    execution_mode: str = "deterministic"  # "deterministic" | "react"
    allowed_tools: list[str] = field(default_factory=list)  # empty = read-only defaults
    max_iterations: int = 3  # max ReAct iterations


class TaskPlanner(Protocol):
    def plan(self, intent: EntryIntent, context: str) -> list[PlanStep]:
        ...


class DefaultTaskPlanner:
    """LLM-first task planner with heuristic fallback.

    Decomposes a user intent into a sequence of executable steps.
    Currently supports capture, ask, summarize, delete_knowledge,
    and solidify_conversation task types.
    """

    def __init__(self, settings: Settings, tool_executor: ToolExecutor | None = None) -> None:
        self._settings = settings
        self._tool_executor = tool_executor

    def plan(self, intent: EntryIntent, context: str = "") -> list[PlanStep]:
        llm_result = self._plan_with_llm(intent, context)
        if llm_result is not None:
            return llm_result
        logger.warning("Planner LLM returned None for intent=%s, falling back to heuristic", intent)
        return self._plan_heuristic(intent)

    def fallback_plan(self, intent: EntryIntent) -> list[PlanStep]:
        """Generate a safe heuristic plan when validation blocks the primary plan."""
        return self._plan_heuristic(intent)

    def _plan_with_llm(self, intent: EntryIntent, context: str) -> list[PlanStep] | None:
        if not self._llm_configured:
            return None

        tool_list = ""
        if self._tool_executor is not None:
            specs = self._tool_executor.list_tools()
            if specs:
                tool_list = "\n".join(f"- {s.name}: {s.description}" for s in specs)

        workflow_rule = {
            "delete_knowledge": (
                "本意图只允许以下四步拓扑，不要增加 verify 步骤：\n"
                "1. retrieve：检索删除候选，execution_mode=\"react\"，"
                "allowed_tools=[\"graph_search\"]，max_iterations=2。\n"
                "2. resolve：依赖 retrieve，从候选中解析目标 note_id。\n"
                "3. tool_call(delete_note)：直接依赖 resolve，tool_input={}；"
                "note_id 会由执行器注入；risk_level=\"high\"，"
                "requires_confirmation=true，on_failure=\"abort\"。\n"
                "4. compose：依赖 delete_note，向用户汇总结果。\n"
                "删除确认由 delete_note 工具和恢复流程执行，不要规划独立 verify 步骤。\n"
            ),
            "solidify_conversation": (
                "本意图只允许以下两步拓扑，不要增加 retrieve 或 verify 步骤：\n"
                "1. compose：从会话中选择用户指定范围的知识并生成入库草稿。\n"
                "2. tool_call(capture_text)：直接依赖 compose，tool_input={}；"
                "text 会由执行器注入；risk_level=\"low\"，"
                "requires_confirmation=false，on_failure=\"abort\"。\n"
                "用户已明确请求固化，因此写入无需二次确认；不得在计划中提供 text 值或占位符。\n"
            ),
        }.get(intent, "")

        prompt = (
            "请根据用户意图生成可被现有执行器直接执行的任务计划。"
            "可用 action_type: retrieve(检索), resolve(从候选中解析具体目标), "
            "tool_call(调用工具), compose(生成回答), verify(校验)。"
            "只返回 JSON 对象，顶层仅包含 steps 数组。每个步骤包含以下字段：\n"
            "  step_id(短标识), action_type, description(对用户友好的中文说明),\n"
            "  tool_name(nullable), tool_input(对象),\n"
            "  depends_on(前置步骤 step_id 数组),\n"
            "  expected_output(可选的展示说明), success_criteria(可选的展示说明),\n"
            "  risk_level(low/medium/high), requires_confirmation(bool),\n"
            "  on_failure(skip/retry/abort), execution_mode(deterministic/react),\n"
            "  allowed_tools(工具名数组), max_iterations(正整数)。\n"
            "description 应该用自然语言向用户说明这一步要做什么，不要只写枚举值。\n"
            "expected_output 和 success_criteria 仅用于界面展示，不得声明执行器不能完成的校验动作。\n"
            f"{workflow_rule}"
            f"意图: {intent}\n"
            f"上下文: {context or '无'}\n"
            f"可用工具:\n{tool_list or '无'}"
        )
        try:
            client = OpenAI(
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url,
                timeout=self._settings.openai_timeout_seconds,
                max_retries=self._settings.openai_max_retries,
            )
            response = client.chat.completions.create(
                model=self._settings.openai_small_model,
                messages=[
                    {"role": "system", "content": "你是一个严谨的任务规划器，只输出含 steps 数组的 JSON 对象。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            # TODO: 临时打点，用于收集 planner LLM 原始输出样本，后续移除
            _capture = _maybe_import_capture()
            if _capture is not None:
                try:
                    _capture(content, intent=intent, context=context, prompt=prompt)
                except Exception:
                    pass
            payload = json.loads(content)
            if not isinstance(payload, dict):
                return None
            steps_data = payload.get("steps", [])
            if not isinstance(steps_data, list):
                return None
            steps: list[PlanStep] = []
            valid_actions = {"retrieve", "resolve", "tool_call", "compose", "verify"}
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
                execution_mode = str(item.get("execution_mode") or "deterministic")
                if execution_mode not in ("deterministic", "react"):
                    execution_mode = "deterministic"
                allowed_tools = item.get("allowed_tools", [])
                if not isinstance(allowed_tools, list):
                    allowed_tools = []
                max_iterations = item.get("max_iterations", 3)
                if not isinstance(max_iterations, int) or isinstance(max_iterations, bool):
                    max_iterations = 3
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
                    execution_mode=execution_mode,
                    allowed_tools=[str(name) for name in allowed_tools if name],
                    max_iterations=max_iterations,
                ))
            return steps if steps else None
        except Exception:
            logger.exception("Failed to plan with LLM, falling back to heuristic")
            return None

    def _plan_heuristic(self, intent: EntryIntent) -> list[PlanStep]:
        if intent in ("capture_text", "capture_link", "capture_file"):
            _tool_for_capture = {
                "capture_text": "capture_text",
                "capture_link": "capture_url",
                "capture_file": "capture_upload",
            }
            return [
                PlanStep(
                    step_id="cap-1", action_type="tool_call",
                    description="采集内容并写入知识库",
                    tool_name=_tool_for_capture.get(intent, "capture_text"),
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
                    execution_mode="react",
                    allowed_tools=["graph_search", "web_search"],
                    max_iterations=3,
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
                PlanStep(
                    step_id="ask-4", action_type="tool_call",
                    description="如果知识库证据不足，通过网络搜索补充外部信息",
                    tool_name="web_search",
                    tool_input={"query": "{question}"},
                    expected_output="网络搜索结果列表（仅在知识库不足时使用）",
                    risk_level="low",
                    on_failure="skip",
                    depends_on=["ask-3"],
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
                    description="检索待删除的候选笔记（图谱 + 本地语义匹配）",
                    tool_name="graph_search",
                    tool_input={"resolve_candidates": True},
                    execution_mode="react",
                    allowed_tools=["graph_search"],
                    max_iterations=2,
                    expected_output="匹配的候选笔记列表（含 note_id / title / summary）",
                    success_criteria="命中至少 1 条候选笔记",
                ),
                PlanStep(
                    step_id="del-2", action_type="resolve",
                    description="从候选中确定要删除的目标笔记",
                    expected_output="已解析的目标 note_id 列表",
                    success_criteria="至少解析出 1 个有效 note_id",
                    depends_on=["del-1"],
                ),
                PlanStep(
                    step_id="del-3", action_type="tool_call",
                    description="请求确认并在确认后删除目标笔记",
                    tool_name="delete_note",
                    expected_output="待确认的删除操作或已删除的笔记 ID",
                    risk_level="high",
                    requires_confirmation=True,
                    depends_on=["del-2"],
                    on_failure="abort",
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
                    step_id="sol-1", action_type="compose",
                    description="从会话中选择指定内容并整理为适合入库的知识文本",
                    expected_output="格式化的知识笔记草稿",
                ),
                PlanStep(
                    step_id="sol-2", action_type="tool_call",
                    description="将知识文本写入知识库（复用 capture 链路）",
                    tool_name="capture_text",
                    expected_output="已持久化的 KnowledgeNote",
                    depends_on=["sol-1"],
                    risk_level="low",
                    on_failure="abort",
                ),
            ]
        if intent == "direct_answer":
            return [
                PlanStep(
                    step_id="da-1", action_type="compose",
                    description="直接生成简短回复",
                    expected_output="一段自然的直接回答",
                    risk_level="low",
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

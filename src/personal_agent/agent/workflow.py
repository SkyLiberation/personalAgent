"""Workflow specifications and registry — the source of truth for fixed flows.

This module makes the project's *workflows* explicit. ``ask`` / ``capture_*`` /
``summarize`` / ``direct_answer`` and the two step-projecting intents
``delete_knowledge`` / ``solidify_conversation`` each declare a fixed step
topology here, rather than asking an LLM to re-invent that topology at runtime.

A ``WorkflowSpec`` is a declarative description of a fixed flow. The planner
projects a spec into a fresh list of ``PlanStep`` objects deterministically.
Genuine semantic judgment (which note to delete, what draft text to write) lives
at *execution* time inside the orchestration ``resolve`` / ``compose`` nodes, not
here.

Boundary
--------
- Topology (which steps, in what order, with what risk) is fixed and lives here.
- Per-request semantics (note_id, draft text) are resolved at execution time and
  injected into ``tool_input`` by the plan execution graph.
- ``PlanValidator`` remains the pre-execution safety gate over the projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..core.models import EntryIntent
from .planner import PlanStep


def _fresh(step: PlanStep) -> PlanStep:
    """Clone a template step into a clean, executable ``planned`` step.

    Spec ``_build`` callables return template steps; ``_fresh`` produces an
    independent copy per projection so concurrent runs never share mutable
    execution state (status / retry_count / tool_input).
    """
    return PlanStep(
        step_id=step.step_id,
        action_type=step.action_type,
        description=step.description,
        tool_name=step.tool_name,
        tool_input=dict(step.tool_input),
        depends_on=list(step.depends_on),
        expected_output=step.expected_output,
        success_criteria=step.success_criteria,
        risk_level=step.risk_level,
        requires_confirmation=step.requires_confirmation,
        on_failure=step.on_failure,
        status="planned",
        retry_count=0,
        execution_mode=step.execution_mode,
        allowed_tools=list(step.allowed_tools),
        max_iterations=step.max_iterations,
    )


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    """A declarative, fixed-topology workflow.

    ``requires_projection`` marks the workflows that are surfaced to the user as
    plan steps and run through the plan execution graph (delete / solidify). The
    others are projected for uniformity but are executed by their own graph
    branch.
    """

    workflow_id: str
    version: str
    intent: EntryIntent
    requires_projection: bool
    build_steps: Callable[[], list[PlanStep]]

    def project(self) -> list[PlanStep]:
        """Project the spec into a fresh, independent list of plan steps."""
        return [_fresh(s) for s in self.build_steps()]


# ---------------------------------------------------------------------------
# Step templates (formerly DefaultTaskPlanner._plan_heuristic)
# ---------------------------------------------------------------------------


def _capture_steps(tool_name: str) -> Callable[[], list[PlanStep]]:
    def build() -> list[PlanStep]:
        return [
            PlanStep(
                step_id="cap-1", action_type="tool_call",
                description="采集内容并写入知识库",
                tool_name=tool_name,
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

    return build


def _ask_steps() -> list[PlanStep]:
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


def _summarize_steps() -> list[PlanStep]:
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


def _delete_knowledge_steps() -> list[PlanStep]:
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


def _solidify_steps() -> list[PlanStep]:
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


def _direct_answer_steps() -> list[PlanStep]:
    return [
        PlanStep(
            step_id="da-1", action_type="compose",
            description="直接生成简短回复",
            expected_output="一段自然的直接回答",
            risk_level="low",
        ),
    ]


def _unknown_steps() -> list[PlanStep]:
    return [
        PlanStep(
            step_id="unk-1", action_type="compose",
            description="生成通用回复",
        ),
    ]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class WorkflowRegistry:
    """Maps an intent to its ``WorkflowSpec`` and projects it deterministically."""

    def __init__(self, specs: list[WorkflowSpec]) -> None:
        self._by_intent: dict[str, WorkflowSpec] = {s.intent: s for s in specs}
        self._unknown = self._by_intent["unknown"]

    def select(self, intent: str) -> WorkflowSpec:
        """Return the spec for an intent, or the ``unknown`` fallback spec."""
        return self._by_intent.get(intent, self._unknown)

    def project(self, intent: str) -> list[PlanStep]:
        """Project the matched workflow into a fresh list of plan steps."""
        return self.select(intent).project()


def _build_registry() -> WorkflowRegistry:
    return WorkflowRegistry([
        WorkflowSpec("capture_text", "v1", "capture_text", False, _capture_steps("capture_text")),
        WorkflowSpec("capture_link", "v1", "capture_link", False, _capture_steps("capture_url")),
        WorkflowSpec("capture_file", "v1", "capture_file", False, _capture_steps("capture_upload")),
        WorkflowSpec("ask", "v1", "ask", False, _ask_steps),
        WorkflowSpec("summarize_thread", "v1", "summarize_thread", False, _summarize_steps),
        WorkflowSpec("delete_knowledge", "v1", "delete_knowledge", True, _delete_knowledge_steps),
        WorkflowSpec("solidify_conversation", "v1", "solidify_conversation", True, _solidify_steps),
        WorkflowSpec("direct_answer", "v1", "direct_answer", False, _direct_answer_steps),
        WorkflowSpec("unknown", "v1", "unknown", False, _unknown_steps),
    ])


WORKFLOW_REGISTRY = _build_registry()

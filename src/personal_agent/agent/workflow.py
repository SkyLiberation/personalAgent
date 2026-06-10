"""Workflow specifications and registry: the source of truth for fixed flows.

``WorkflowSpec`` describes business workflows. Ordinary workflows such as
``ask`` and ``capture_*`` are selected and then executed by their graph branch.
Step-executed workflows such as ``delete_knowledge`` and
``solidify_conversation`` additionally expose selected nodes as ``PlanStep``
projections for checkpointing, HITL, audit, and the frontend plan panel.

The important boundary is:

- ``WorkflowStepSpec`` is the durable workflow contract.
- ``PlanStep`` is only a runtime projection of a workflow node.
- Per-request semantics, such as ``note_id`` or draft text, are resolved during
  execution by decision nodes and dynamic result injection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core.models import EntryIntent
from .planner import PlanStep

ProjectionPolicy = Literal["none", "step_projection"]


@dataclass(frozen=True, slots=True)
class WorkflowStepSpec:
    """A node-level contract inside a workflow.

    The fields intentionally mirror the runtime projection shape where useful,
    but this object is stronger than ``PlanStep``: it belongs to the workflow
    source of truth and can carry non-UI contracts such as decision node names,
    side effects, HITL policy, and node recovery policy.
    """

    step_id: str
    action_type: str
    description: str
    tool_name: str | None = None
    tool_input: dict[str, object] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    expected_output: str = ""
    success_criteria: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = False
    on_failure: str = "skip"
    execution_mode: str = "deterministic"
    allowed_tools: tuple[str, ...] = ()
    max_iterations: int = 3
    llm_decision_node: str | None = None
    side_effects: tuple[str, ...] = ()
    hitl_policy: str = "none"
    recovery_policy: str = "skip"
    project_to_plan: bool = True

    def to_projection(self, workflow_id: str, workflow_version: str) -> PlanStep:
        """Create a fresh runtime step projection for this workflow node."""
        return PlanStep(
            step_id=self.step_id,
            action_type=self.action_type,
            description=self.description,
            tool_name=self.tool_name,
            tool_input=dict(self.tool_input),
            depends_on=list(self.depends_on),
            expected_output=self.expected_output,
            success_criteria=self.success_criteria,
            risk_level=self.risk_level,
            requires_confirmation=self.requires_confirmation,
            on_failure=self.on_failure,
            status="planned",
            retry_count=0,
            execution_mode=self.execution_mode,
            allowed_tools=list(self.allowed_tools),
            max_iterations=self.max_iterations,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_step_id=self.step_id,
            projection_kind="workflow_step",
        )


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    """A declarative workflow contract.

    ``projection_policy='step_projection'`` means selected ``WorkflowStepSpec``
    nodes are surfaced as runtime ``PlanStep`` projections. ``projection_policy``
    is intentionally explicit so ordinary workflows can still have rich node
    contracts without being shown as a plan.
    """

    workflow_id: str
    version: str
    intent: EntryIntent
    steps: tuple[WorkflowStepSpec, ...]
    projection_policy: ProjectionPolicy = "none"
    hitl_policy: str = "none"
    recovery_policy: str = "branch"

    def __post_init__(self) -> None:
        ids = [s.step_id for s in self.steps]
        duplicates = {sid for sid in ids if ids.count(sid) > 1}
        if duplicates:
            raise ValueError(f"Workflow {self.workflow_id} has duplicate step ids: {sorted(duplicates)}")

        known = set(ids)
        for step in self.steps:
            unknown_deps = [dep for dep in step.depends_on if dep not in known]
            if unknown_deps:
                raise ValueError(
                    f"Workflow {self.workflow_id} step {step.step_id} depends on unknown steps: "
                    f"{unknown_deps}"
                )

    @property
    def requires_projection(self) -> bool:
        return self.projection_policy == "step_projection"

    @property
    def allows_llm_decision_node(self) -> bool:
        return any(s.llm_decision_node for s in self.steps)

    @property
    def allows_tools(self) -> bool:
        return any(s.tool_name or s.allowed_tools for s in self.steps)

    @property
    def has_high_risk_side_effect(self) -> bool:
        return any(s.risk_level == "high" or "delete_longterm" in s.side_effects for s in self.steps)

    def project(self) -> list[PlanStep]:
        """Project this workflow into fresh runtime steps when policy allows it."""
        if not self.requires_projection:
            return []
        return [
            step.to_projection(self.workflow_id, self.version)
            for step in self.steps
            if step.project_to_plan
        ]


class WorkflowRegistry:
    """Maps an intent to its ``WorkflowSpec`` and projects step workflows."""

    def __init__(self, specs: list[WorkflowSpec]) -> None:
        self._by_intent: dict[str, WorkflowSpec] = {s.intent: s for s in specs}
        self._unknown = self._by_intent["unknown"]

    def select(self, intent: str) -> WorkflowSpec:
        """Return the spec for an intent, or the ``unknown`` fallback spec."""
        return self._by_intent.get(intent, self._unknown)

    def project(self, intent: str) -> list[PlanStep]:
        """Project the matched workflow into runtime steps when required."""
        return self.select(intent).project()


def _workflow(
    workflow_id: str,
    intent: EntryIntent,
    steps: tuple[WorkflowStepSpec, ...],
    *,
    projection_policy: ProjectionPolicy = "none",
    hitl_policy: str = "none",
    recovery_policy: str = "branch",
) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=workflow_id,
        version="v1",
        intent=intent,
        steps=steps,
        projection_policy=projection_policy,
        hitl_policy=hitl_policy,
        recovery_policy=recovery_policy,
    )


def _build_registry() -> WorkflowRegistry:
    return WorkflowRegistry([
        _workflow(
            "capture_text",
            "capture_text",
            (
                WorkflowStepSpec(
                    "cap-structure",
                    "tool_call",
                    "结构化解析输入内容并写入知识库",
                    tool_name="capture_text",
                    side_effects=("write_longterm",),
                    recovery_policy="branch",
                    project_to_plan=False,
                ),
            ),
        ),
        _workflow(
            "capture_link",
            "capture_link",
            (
                WorkflowStepSpec(
                    "cap-link-fetch",
                    "tool_call",
                    "抓取链接内容并进入 capture 链路",
                    tool_name="capture_url",
                    side_effects=("external_network", "write_longterm"),
                    recovery_policy="branch",
                    project_to_plan=False,
                ),
            ),
        ),
        _workflow(
            "capture_file",
            "capture_file",
            (
                WorkflowStepSpec(
                    "cap-file-read",
                    "tool_call",
                    "读取上传文件并进入 capture 链路",
                    tool_name="capture_upload",
                    side_effects=("write_longterm",),
                    recovery_policy="branch",
                    project_to_plan=False,
                ),
            ),
        ),
        _workflow(
            "ask",
            "ask",
            (
                WorkflowStepSpec(
                    "ask-understand",
                    "compose",
                    "理解问题并生成检索计划",
                    llm_decision_node="query_understanding",
                    recovery_policy="fallback_query",
                    project_to_plan=False,
                ),
                WorkflowStepSpec(
                    "ask-retrieve",
                    "retrieve",
                    "从结构化索引、图谱和向量候选中检索 evidence",
                    depends_on=("ask-understand",),
                    execution_mode="react",
                    allowed_tools=("graph_search", "web_search"),
                    max_iterations=3,
                    recovery_policy="degrade_to_local_context",
                    project_to_plan=False,
                ),
                WorkflowStepSpec(
                    "ask-compose",
                    "compose",
                    "基于 evidence 生成有依据的回答",
                    depends_on=("ask-retrieve",),
                    llm_decision_node="answer_compose",
                    recovery_policy="clarify_or_direct_answer",
                    project_to_plan=False,
                ),
            ),
        ),
        _workflow(
            "summarize_thread",
            "summarize_thread",
            (
                WorkflowStepSpec(
                    "sum-compose",
                    "compose",
                    "总结当前线程中的主题、结论和待办",
                    llm_decision_node="thread_summary",
                    recovery_policy="branch",
                    project_to_plan=False,
                ),
            ),
        ),
        _workflow(
            "delete_knowledge",
            "delete_knowledge",
            (
                WorkflowStepSpec(
                    "del-1",
                    "retrieve",
                    "检索待删除的候选笔记（图谱 + 本地语义匹配）",
                    tool_name="graph_search",
                    tool_input={"resolve_candidates": True},
                    execution_mode="react",
                    allowed_tools=("graph_search",),
                    max_iterations=2,
                    expected_output="匹配的候选笔记列表（含 note_id / title / summary）",
                    success_criteria="命中至少 1 条候选笔记",
                    recovery_policy="clarify",
                ),
                WorkflowStepSpec(
                    "del-2",
                    "resolve",
                    "从候选中确定要删除的目标笔记",
                    depends_on=("del-1",),
                    expected_output="已解析的目标 note_id 列表",
                    success_criteria="至少解析出 1 个有效 note_id",
                    llm_decision_node="delete_target_resolve",
                    recovery_policy="clarify",
                ),
                WorkflowStepSpec(
                    "del-3",
                    "tool_call",
                    "请求确认并在确认后删除目标笔记",
                    tool_name="delete_note",
                    depends_on=("del-2",),
                    expected_output="待确认的删除操作或已删除的笔记 ID",
                    risk_level="high",
                    requires_confirmation=True,
                    on_failure="abort",
                    side_effects=("delete_longterm",),
                    hitl_policy="required_for_delete",
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "del-4",
                    "compose",
                    "生成删除结果摘要",
                    depends_on=("del-3",),
                    expected_output="已删除 / 未找到 / 待确认 的结构化结果",
                    llm_decision_node="delete_result_compose",
                    recovery_policy="skip",
                ),
            ),
            projection_policy="step_projection",
            hitl_policy="required_for_delete",
            recovery_policy="checkpoint_step",
        ),
        _workflow(
            "solidify_conversation",
            "solidify_conversation",
            (
                WorkflowStepSpec(
                    "sol-1",
                    "compose",
                    "从会话中选择指定内容并整理为适合入库的知识文本",
                    expected_output="格式化的知识笔记草稿",
                    llm_decision_node="solidify_draft",
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "sol-2",
                    "tool_call",
                    "将知识文本写入知识库（复用 capture 链路）",
                    tool_name="capture_text",
                    depends_on=("sol-1",),
                    expected_output="已持久化的 KnowledgeNote",
                    risk_level="low",
                    on_failure="abort",
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
            ),
            projection_policy="step_projection",
            recovery_policy="checkpoint_step",
        ),
        _workflow(
            "direct_answer",
            "direct_answer",
            (
                WorkflowStepSpec(
                    "direct-compose",
                    "compose",
                    "生成直接回答",
                    llm_decision_node="direct_answer",
                    recovery_policy="branch",
                    project_to_plan=False,
                ),
            ),
        ),
        _workflow("unknown", "unknown", ()),
    ])


WORKFLOW_REGISTRY = _build_registry()

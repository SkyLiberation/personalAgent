"""Workflow specifications and registry: the source of truth for fixed flows.

``WorkflowSpec`` describes business workflows. Ordinary workflows such as
``ask`` / ``capture_*`` / ``summarize_thread`` / ``direct_answer`` are selected
from the same registry as operational workflows. Step-executed workflows expose
selected nodes as ``ExecutionStep`` projections for checkpointing, HITL, audit,
and the frontend step panel.

The important boundary is:

- ``WorkflowStepSpec`` is the durable workflow contract.
- ``ExecutionStep`` is only a runtime projection of a workflow node.
- Per-request semantics, such as ``note_id`` or draft text, are resolved during
  execution by decision nodes and dynamic result injection.
"""

from __future__ import annotations

from personal_agent.kernel.models import EntryIntent
from personal_agent.kernel.contracts.execution import ExecutionStep
# Durable workflow contracts (data + serialization) now live in the kernel so the
# infra workflow store can persist them without importing this planning module.
# The registry and the in-repo flow definitions below stay in the planning layer.
from personal_agent.kernel.contracts.workflow import (
    EDGE_ABORT,
    EDGE_CLARIFY,
    EDGE_END,
    EDGE_SENTINELS,
    BranchPolicy,
    ProjectionPolicy,
    WorkflowConditionalEdge,
    WorkflowSpec,
    WorkflowStepSpec,
)

__all__ = [
    "EDGE_ABORT",
    "EDGE_CLARIFY",
    "EDGE_END",
    "EDGE_SENTINELS",
    "BranchPolicy",
    "ProjectionPolicy",
    "WorkflowConditionalEdge",
    "WorkflowSpec",
    "WorkflowStepSpec",
    "WorkflowRegistry",
    "WORKFLOW_REGISTRY",
]


class WorkflowRegistry:
    """Maps an intent to its ``WorkflowSpec`` and projects step workflows."""

    def __init__(self, specs: list[WorkflowSpec]) -> None:
        self._by_intent: dict[str, WorkflowSpec] = {s.intent: s for s in specs}
        self._unknown = self._by_intent["unknown"]

    def select(self, intent: str) -> WorkflowSpec:
        """Return the spec for an intent, or the ``unknown`` fallback spec."""
        return self._by_intent.get(intent, self._unknown)

    def all_specs(self) -> list[WorkflowSpec]:
        """Return every registered spec (deduplicated, stable order)."""
        seen: set[str] = set()
        specs: list[WorkflowSpec] = []
        for spec in self._by_intent.values():
            if spec.workflow_id in seen:
                continue
            seen.add(spec.workflow_id)
            specs.append(spec)
        return specs

    def project(self, intent: str) -> list[ExecutionStep]:
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
                ),
            ),
            projection_policy="step_projection",
        ),
        _workflow(
            "capture_link",
            "capture_link",
            (
                WorkflowStepSpec(
                    "cap-link-fetch",
                    "tool_call",
                    "抓取链接正文",
                    tool_name="capture_url",
                    side_effects=("external_network",),
                    recovery_policy="branch",
                ),
                WorkflowStepSpec(
                    "cap-link-store",
                    "tool_call",
                    "将链接正文写入知识库",
                    tool_name="capture_text",
                    depends_on=("cap-link-fetch",),
                    side_effects=("write_longterm",),
                    recovery_policy="branch",
                ),
            ),
            projection_policy="step_projection",
        ),
        _workflow(
            "capture_file",
            "capture_file",
            (
                WorkflowStepSpec(
                    "cap-file-read",
                    "tool_call",
                    "读取上传文件正文",
                    tool_name="capture_upload",
                    side_effects=(),
                    recovery_policy="branch",
                ),
                WorkflowStepSpec(
                    "cap-file-store",
                    "tool_call",
                    "将文件正文写入知识库",
                    tool_name="capture_text",
                    depends_on=("cap-file-read",),
                    side_effects=("write_longterm",),
                    recovery_policy="branch",
                ),
            ),
            projection_policy="step_projection",
        ),
        _workflow(
            "ask",
            "ask",
            (
                WorkflowStepSpec(
                    "ask-retrieve",
                    "retrieve",
                    "检索个人知识库、图谱与网络证据",
                    recovery_policy="degrade_to_local_context",
                    project_to_plan=True,
                ),
                WorkflowStepSpec(
                    "ask-compose",
                    "compose",
                    "基于检索到的证据生成有依据的回答",
                    depends_on=("ask-retrieve",),
                    llm_decision_node="answer_compose",
                    recovery_policy="clarify_or_direct_answer",
                    project_to_plan=True,
                ),
                WorkflowStepSpec(
                    "ask-verify",
                    "verify",
                    "校验回答的事实依据与引用完整性",
                    depends_on=("ask-compose",),
                    recovery_policy="branch",
                    project_to_plan=True,
                ),
            ),
            projection_policy="step_projection",
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
                ),
            ),
            projection_policy="step_projection",
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
                    branch_policy="clarify",
                    conditional_edges=(
                        WorkflowConditionalEdge("no_candidate", EDGE_CLARIFY),
                    ),
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
                    branch_policy="human_select",
                    conditional_edges=(
                        WorkflowConditionalEdge("ambiguous_candidate", EDGE_CLARIFY),
                        WorkflowConditionalEdge("no_candidate", EDGE_CLARIFY),
                    ),
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
                    branch_policy="abort",
                    conditional_edges=(
                        WorkflowConditionalEdge("rejected", EDGE_ABORT),
                    ),
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
                    branch_policy="abort",
                    conditional_edges=(
                        WorkflowConditionalEdge("no_draft", EDGE_ABORT),
                    ),
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
                    branch_policy="abort",
                ),
            ),
            projection_policy="step_projection",
            recovery_policy="checkpoint_step",
        ),
        _workflow(
            "review_digest",
            "review_digest",
            (
                WorkflowStepSpec(
                    "digest-generate",
                    "tool_call",
                    "生成当前用户的知识简报",
                    tool_name="review_digest",
                    side_effects=("read_longterm",),
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "digest-compose",
                    "compose",
                    "呈现知识简报",
                    depends_on=("digest-generate",),
                    recovery_policy="abort",
                ),
            ),
            projection_policy="step_projection",
        ),
        _workflow(
            "consolidate_knowledge",
            "consolidate_knowledge",
            (
                WorkflowStepSpec(
                    "consolidate-run",
                    "tool_call",
                    "按主题选择并整理相关知识",
                    tool_name="consolidate_knowledge",
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "consolidate-compose",
                    "compose",
                    "呈现知识整理结果",
                    depends_on=("consolidate-run",),
                    recovery_policy="abort",
                ),
            ),
            projection_policy="step_projection",
        ),
        _workflow(
            "inspect_knowledge_gaps",
            "inspect_knowledge_gaps",
            (
                WorkflowStepSpec(
                    "gap-inspect",
                    "tool_call",
                    "分析知识孤岛、薄弱连接和潜在冲突",
                    tool_name="inspect_knowledge_gaps",
                    side_effects=("read_longterm",),
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "gap-compose",
                    "compose",
                    "呈现知识缺口分析",
                    depends_on=("gap-inspect",),
                    recovery_policy="abort",
                ),
            ),
            projection_policy="step_projection",
        ),
        _workflow(
            "research_once",
            "research_once",
            (
                WorkflowStepSpec(
                    "research-prepare",
                    "tool_call",
                    "创建 ResearchRun 并记录本次研究窗口",
                    tool_name="research_prepare_run",
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "research-initialize",
                    "tool_call",
                    "初始化 evidence-driven ResearchState",
                    tool_name="research_initialize_state",
                    depends_on=("research-prepare",),
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "research-loop",
                    "tool_call",
                    "按证据缺口动态执行研究循环",
                    tool_name="research_run_loop",
                    depends_on=("research-initialize",),
                    side_effects=("external_network", "write_longterm"),
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "research-synthesize",
                    "tool_call",
                    "根据研究状态生成情报简报",
                    tool_name="research_synthesize_digest",
                    depends_on=("research-loop",),
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "research-verify",
                    "tool_call",
                    "校验情报简报证据支撑",
                    tool_name="research_verify_digest",
                    depends_on=("research-synthesize",),
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "research-compose",
                    "compose",
                    "呈现研究简报",
                    depends_on=("research-verify",),
                    recovery_policy="abort",
                ),
            ),
            projection_policy="step_projection",
            recovery_policy="checkpoint_step",
        ),
        _workflow(
            "create_research_subscription",
            "create_research_subscription",
            (
                WorkflowStepSpec(
                    "research-subscribe",
                    "tool_call",
                    "创建周期性情报收集订阅",
                    tool_name="create_research_subscription",
                    risk_level="medium",
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
            ),
            projection_policy="step_projection",
        ),
        _workflow(
            "execute_research_run",
            "execute_research_run",
            (
                WorkflowStepSpec(
                    "research-initialize",
                    "tool_call",
                    "初始化已有 ResearchRun 的 ResearchState",
                    tool_name="research_initialize_state",
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "research-loop",
                    "tool_call",
                    "按证据缺口动态执行研究循环",
                    tool_name="research_run_loop",
                    depends_on=("research-initialize",),
                    side_effects=("external_network", "write_longterm"),
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "research-synthesize",
                    "tool_call",
                    "根据研究状态生成情报简报",
                    tool_name="research_synthesize_digest",
                    depends_on=("research-loop",),
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
                WorkflowStepSpec(
                    "research-verify",
                    "tool_call",
                    "校验情报简报证据支撑",
                    tool_name="research_verify_digest",
                    depends_on=("research-synthesize",),
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
            ),
            projection_policy="step_projection",
            recovery_policy="checkpoint_step",
        ),
        _workflow(
            "manage_research",
            "manage_research",
            (
                WorkflowStepSpec(
                    "research-manage-decide",
                    "resolve",
                    "根据用户请求管理 Research 订阅、运行、简报、反馈或入库动作",
                    execution_mode="react",
                    allowed_tools=(
                        "list_research_subscriptions",
                        "update_research_subscription",
                        "pause_research_subscription",
                        "resume_research_subscription",
                        "run_research_subscription_now",
                        "list_research_runs",
                        "get_research_digest",
                        "submit_research_feedback",
                        "save_research_event",
                    ),
                    max_iterations=3,
                    side_effects=("read_longterm", "write_longterm"),
                    recovery_policy="clarify",
                    branch_policy="clarify",
                ),
                WorkflowStepSpec(
                    "research-manage-compose",
                    "compose",
                    "呈现 Research 管理动作结果",
                    depends_on=("research-manage-decide",),
                    recovery_policy="branch",
                ),
            ),
            projection_policy="step_projection",
            recovery_policy="checkpoint_step",
        ),
        _workflow(
            "maintain_knowledge",
            "maintain_knowledge",
            (
                WorkflowStepSpec(
                    "knowledge-maintain-decide",
                    "resolve",
                    "根据用户请求查询、修正、替换、标记过期或标记冲突的知识",
                    execution_mode="react",
                    allowed_tools=(
                        "list_recent_notes",
                        "get_note",
                        "find_similar_notes",
                        "update_note",
                        "supersede_note",
                        "mark_note_deprecated",
                        "mark_notes_conflicted",
                    ),
                    max_iterations=3,
                    side_effects=("read_longterm", "write_longterm"),
                    recovery_policy="clarify",
                    branch_policy="clarify",
                ),
                WorkflowStepSpec(
                    "knowledge-maintain-compose",
                    "compose",
                    "呈现知识维护结果",
                    depends_on=("knowledge-maintain-decide",),
                    recovery_policy="branch",
                ),
            ),
            projection_policy="step_projection",
            recovery_policy="checkpoint_step",
        ),
        _workflow(
            "inspect_operations",
            "inspect_operations",
            (
                WorkflowStepSpec(
                    "ops-inspect-decide",
                    "resolve",
                    "诊断后台 worker 队列、失败任务和可重试任务",
                    execution_mode="react",
                    allowed_tools=("inspect_worker_queue", "retry_worker_task"),
                    max_iterations=2,
                    side_effects=("none", "write_longterm"),
                    recovery_policy="branch",
                ),
                WorkflowStepSpec(
                    "ops-inspect-compose",
                    "compose",
                    "呈现后台任务诊断结果",
                    depends_on=("ops-inspect-decide",),
                    recovery_policy="branch",
                ),
            ),
            projection_policy="step_projection",
            recovery_policy="checkpoint_step",
        ),
        _workflow(
            "inspect_workflow",
            "inspect_workflow",
            (
                WorkflowStepSpec(
                    "workflow-inspect-decide",
                    "resolve",
                    "查看 workflow run 快照、步骤状态和历史，用于解释执行过程",
                    execution_mode="react",
                    allowed_tools=("inspect_workflow_run",),
                    max_iterations=2,
                    side_effects=("none",),
                    recovery_policy="branch",
                ),
                WorkflowStepSpec(
                    "workflow-inspect-compose",
                    "compose",
                    "呈现 workflow 诊断结果",
                    depends_on=("workflow-inspect-decide",),
                    recovery_policy="branch",
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
                ),
            ),
            projection_policy="step_projection",
        ),
        _workflow("unknown", "unknown", ()),
    ])


WORKFLOW_REGISTRY = _build_registry()

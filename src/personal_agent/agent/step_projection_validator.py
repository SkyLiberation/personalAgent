from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..core.models import EntryIntent
from ..tools import tool_governance
from .execution_models import ExecutionStep

if TYPE_CHECKING:
    from ..tools import ToolExecutor
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

VALID_ACTION_TYPES = {"retrieve", "tool_call", "compose", "verify", "resolve"}
VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_ON_FAILURE = {"skip", "retry", "abort"}
VALID_EXECUTION_MODES = {"deterministic", "react"}
MAX_REACT_ITERATIONS = 5


@dataclass(slots=True)
class StepProjectionValidationResult:
    valid: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    corrected_steps: list[ExecutionStep] | None = None
    replanned: bool = False

    @property
    def ok(self) -> bool:
        return len(self.issues) == 0

    @property
    def blocking(self) -> bool:
        """True if there are blocking (critical) issues that prevent safe execution."""
        return not self.ok or self.replanned


def _clone_step(s: ExecutionStep) -> ExecutionStep:
    return ExecutionStep(
        step_id=s.step_id,
        action_type=s.action_type,
        description=s.description,
        tool_name=s.tool_name,
        tool_input=dict(s.tool_input),
        depends_on=list(s.depends_on),
        expected_output=s.expected_output,
        success_criteria=s.success_criteria,
        risk_level=s.risk_level,
        requires_confirmation=s.requires_confirmation,
        on_failure=s.on_failure,
        status=s.status,
        retry_count=s.retry_count,
        execution_mode=getattr(s, "execution_mode", "deterministic"),
        allowed_tools=list(getattr(s, "allowed_tools", [])),
        max_iterations=getattr(s, "max_iterations", 3),
        workflow_id=getattr(s, "workflow_id", ""),
        workflow_version=getattr(s, "workflow_version", ""),
        workflow_step_id=getattr(s, "workflow_step_id", ""),
        projection_kind=getattr(s, "projection_kind", "workflow_step"),
        task_id=getattr(s, "task_id", ""),
        task_intent=getattr(s, "task_intent", "unknown"),
        task_input=getattr(s, "task_input", ""),
    )


def _has_upstream_action_type(
    steps: list[ExecutionStep], step: ExecutionStep, action_type: str,
) -> bool:
    """Return whether a step transitively depends on an action type."""
    by_id = {candidate.step_id: candidate for candidate in steps}
    pending = list(step.depends_on)
    visited: set[str] = set()
    while pending:
        step_id = pending.pop()
        if step_id in visited:
            continue
        visited.add(step_id)
        candidate = by_id.get(step_id)
        if candidate is None:
            continue
        if candidate.action_type == action_type:
            return True
        pending.extend(candidate.depends_on)
    return False


def _has_upstream_tool(
    steps: list[ExecutionStep], step: ExecutionStep, tool_names: set[str],
) -> bool:
    """Return whether a step transitively depends on one of the given tools."""
    by_id = {candidate.step_id: candidate for candidate in steps}
    pending = list(step.depends_on)
    visited: set[str] = set()
    while pending:
        step_id = pending.pop()
        if step_id in visited:
            continue
        visited.add(step_id)
        candidate = by_id.get(step_id)
        if candidate is None:
            continue
        if candidate.action_type == "tool_call" and candidate.tool_name in tool_names:
            return True
        pending.extend(candidate.depends_on)
    return False


class StepProjectionValidator:
    """Pre-execution workflow step projection validation.

    Validates compiled workflow structure and governance. Router output is not
    accepted here: execution policy comes from WorkflowSpec and tools.
    """

    def __init__(self, tool_executor: "ToolExecutor | None" = None) -> None:
        self._tool_executor = tool_executor

    def _get_known_tools(self) -> set[str]:
        if self._tool_executor is not None:
            return {s.name for s in self._tool_executor.list_tools()}
        return set()

    def _get_tool_spec(self, name: str) -> "BaseTool | None":
        if self._tool_executor is not None:
            tool = self._tool_executor.get(name)
            if tool is not None:
                return tool
        return None

    def validate(
        self,
        steps: list[ExecutionStep],
        intent: EntryIntent,
    ) -> StepProjectionValidationResult:
        issues: list[str] = []
        warnings: list[str] = []
        bad_status_indices: list[int] = []
        known_tools = self._get_known_tools()

        # --- A. Structural checks ---
        seen_ids: set[str] = set()
        step_ids: set[str] = set()

        for i, s in enumerate(steps):
            prefix = f"步骤[{i}] {s.step_id!r}:"

            if not s.step_id or not s.step_id.strip():
                issues.append(f"{prefix} step_id 为空。")
            elif s.step_id in seen_ids:
                issues.append(f"{prefix} step_id 重复。")
            else:
                seen_ids.add(s.step_id)
            step_ids.add(s.step_id)

            if s.action_type not in VALID_ACTION_TYPES:
                issues.append(
                    f"{prefix} action_type={s.action_type!r} 无效，"
                    f"有效值：{sorted(VALID_ACTION_TYPES)}。"
                )

            if not s.description or not s.description.strip():
                warnings.append(f"{prefix} description 为空。")

            if s.action_type == "tool_call" and not s.tool_name:
                issues.append(f"{prefix} action_type=tool_call 但 tool_name 为空。")
            if s.action_type == "tool_call" and s.tool_name and s.tool_name not in known_tools:
                if known_tools:
                    issues.append(
                        f"{prefix} tool_name={s.tool_name!r} 未在 ToolExecutor 中注册。"
                        f"可用工具：{sorted(known_tools)}"
                    )
                else:
                    warnings.append(
                        f"{prefix} tool_name={s.tool_name!r} 无法校验（ToolExecutor 未注入）。"
                    )

            # Deep parameter validation against the LangChain tool schema.
            if s.action_type == "tool_call" and s.tool_name and s.tool_name in known_tools:
                tool_spec = self._get_tool_spec(s.tool_name)
                if tool_spec is not None and tool_spec.args_schema is not None:
                    try:
                        tool_spec.args_schema.model_validate(s.tool_input)
                        schema_errors: list[str] = []
                    except ValidationError as exc:
                        schema_errors = [
                            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
                            for err in exc.errors()
                        ]
                    for err in schema_errors:
                        deferred_capture_text = (
                            s.tool_name == "capture_text"
                            and "text" not in s.tool_input
                            and "text" in err
                            and (
                                (
                                    intent == "solidify_conversation"
                                    and _has_upstream_action_type(steps, s, "compose")
                                )
                                or intent == "capture_text"
                                or (
                                    intent in {"capture_link", "capture_file"}
                                    and _has_upstream_tool(
                                        steps,
                                        s,
                                        {"capture_url", "capture_upload"},
                                    )
                                )
                            )
                        )
                        deferred_capture_url = (
                            s.tool_name == "capture_url"
                            and "url" not in s.tool_input
                            and "url" in err
                            and intent == "capture_link"
                        )
                        deferred_capture_upload = (
                            s.tool_name == "capture_upload"
                            and (
                                ("file_path" not in s.tool_input and "file_path" in err)
                                or ("filename" not in s.tool_input and "filename" in err)
                            )
                            and intent == "capture_file"
                        )
                        deferred_delete_note_id = (
                            s.tool_name == "delete_note"
                            and "note_id" not in s.tool_input
                            and "note_id" in err
                            and _has_upstream_action_type(steps, s, "resolve")
                        )
                        deferred_consolidation_topic = (
                            s.tool_name == "consolidate_knowledge"
                            and "topic" not in s.tool_input
                            and "topic" in err
                            and intent == "consolidate_knowledge"
                        )
                        if (
                            deferred_capture_text
                            or deferred_capture_url
                            or deferred_capture_upload
                            or deferred_delete_note_id
                            or deferred_consolidation_topic
                        ):
                            continue
                        issues.append(f"{prefix} tool_input 参数校验失败: {err}")

                # --- Governance cross-checks ---
                if tool_spec is not None:
                    governance = tool_governance(tool_spec)
                    # Tool requires confirmation but step doesn't
                    if governance.requires_confirmation and not s.requires_confirmation:
                        warnings.append(
                            f"{prefix} 工具 {s.tool_name!r} 要求确认（requires_confirmation=True），"
                            f"但步骤未设置 requires_confirmation。"
                        )
                    # Tool writes longterm but step has no confirmation
                    explicit_solidify_write = (
                        intent in {
                            "solidify_conversation",
                            "capture_text",
                            "capture_link",
                            "capture_file",
                            "consolidate_knowledge",
                        }
                        and s.tool_name in {"capture_text", "consolidate_knowledge"}
                    )
                    if (
                        any(effect in governance.side_effects for effect in ("write_longterm", "delete_longterm"))
                        and not explicit_solidify_write
                        and not s.requires_confirmation
                        and s.risk_level != "high"
                    ):
                        warnings.append(
                            f"{prefix} 工具 {s.tool_name!r} 会修改长期知识（side_effects={governance.side_effects!r}），"
                            f"建议步骤增加确认或提升风险等级。"
                        )
                    # Tool accesses external network
                    if "external_network" in governance.side_effects:
                        warnings.append(
                            f"{prefix} 工具 {s.tool_name!r} 会访问外部网络（side_effects 包含 external_network），"
                            f"请注意外部副作用。"
                        )
                    # Tool risk is higher than step risk
                    risk_order = {"low": 0, "medium": 1, "high": 2}
                    tool_risk = governance.risk_level
                    if risk_order.get(tool_risk, 0) > risk_order.get(s.risk_level, 0):
                        warnings.append(
                            f"{prefix} 工具 {s.tool_name!r} 的固有风险等级为 "
                            f"{tool_risk!r}，高于步骤声明的 {s.risk_level!r}。"
                        )

            if s.risk_level not in VALID_RISK_LEVELS:
                issues.append(
                    f"{prefix} risk_level={s.risk_level!r} 无效，"
                    f"有效值：{sorted(VALID_RISK_LEVELS)}。"
                )

            if s.on_failure not in VALID_ON_FAILURE:
                issues.append(
                    f"{prefix} on_failure={s.on_failure!r} 无效，"
                    f"有效值：{sorted(VALID_ON_FAILURE)}。"
                )

            if s.status != "planned":
                warnings.append(
                    f"{prefix} 初始 status={s.status!r}，已自动修正为 'planned'。"
                )
                bad_status_indices.append(i)

            if s.requires_confirmation and s.risk_level == "low":
                warnings.append(
                    f"{prefix} requires_confirmation=True 但 risk_level='low'，"
                    f"建议将 risk_level 至少设为 'medium'。"
                )

            if intent == "delete_knowledge":
                if s.action_type == "verify":
                    issues.append(
                        f"{prefix} 删除确认由 delete_note 工具执行，"
                        "当前 verify 步骤无法执行目标确认，不应加入删除计划。"
                    )
                if s.action_type == "tool_call" and s.tool_name == "delete_note":
                    if not _has_upstream_action_type(steps, s, "resolve"):
                        issues.append(
                            f"{prefix} delete_note 必须依赖 resolve 动态解析目标 note_id。"
                        )
                    if "note_id" in s.tool_input:
                        issues.append(
                            f"{prefix} delete_note.note_id 必须由 resolve 执行结果动态注入，"
                            "不得在计划阶段提供。"
                        )
                    if s.risk_level != "high" or not s.requires_confirmation:
                        issues.append(
                            f"{prefix} delete_note 必须声明 risk_level='high' "
                            "且 requires_confirmation=True。"
                        )

            if intent == "solidify_conversation":
                if s.action_type in {"retrieve", "resolve", "verify"}:
                    issues.append(
                        f"{prefix} 固化计划只允许 compose 生成草稿后调用 capture_text；"
                        f"当前 {s.action_type!r} 步骤没有可兑现的独立执行语义。"
                    )
                if s.action_type == "tool_call" and s.tool_name == "capture_text":
                    if not _has_upstream_action_type(steps, s, "compose"):
                        issues.append(
                            f"{prefix} 固化写入必须依赖 compose 生成的真实知识草稿，"
                            "不得直接写入检索结果或步骤占位符。"
                        )
                    if "text" in s.tool_input:
                        issues.append(
                            f"{prefix} capture_text.text 必须由 compose 执行结果动态注入，"
                            "计划阶段不得提供正文或占位符。"
                        )
                    if s.risk_level != "low" or s.requires_confirmation:
                        issues.append(
                            f"{prefix} 用户已明确请求固化，capture_text 应声明 "
                            "risk_level='low' 且 requires_confirmation=False。"
                        )

            # ReAct execution mode checks
            exec_mode = getattr(s, "execution_mode", "deterministic")
            if exec_mode not in VALID_EXECUTION_MODES:
                issues.append(
                    f"{prefix} execution_mode={exec_mode!r} 无效，"
                    f"有效值：{sorted(VALID_EXECUTION_MODES)}。"
                )
            if exec_mode == "react":
                if s.risk_level == "high":
                    issues.append(
                        f"{prefix} execution_mode='react' 不允许 risk_level='high'。"
                    )
                if s.requires_confirmation:
                    issues.append(
                        f"{prefix} execution_mode='react' 不允许 requires_confirmation=True。"
                    )
                allowed = getattr(s, "allowed_tools", [])
                if isinstance(allowed, (list, tuple)):
                    for tool_name in allowed:
                        if tool_name not in known_tools and known_tools:
                            issues.append(
                                f"{prefix} allowed_tools 中的 {tool_name!r} 未在 ToolExecutor 中注册。"
                            )
                max_iter = getattr(s, "max_iterations", 3)
                if not isinstance(max_iter, int) or max_iter < 1:
                    issues.append(f"{prefix} max_iterations 必须为正整数。")
                elif max_iter > MAX_REACT_ITERATIONS:
                    warnings.append(
                        f"{prefix} max_iterations={max_iter} 超过上限 {MAX_REACT_ITERATIONS}，已自动限制。"
                    )

        # --- B. Dependency graph checks ---
        for i, s in enumerate(steps):
            prefix = f"步骤[{i}] {s.step_id!r}:"
            for dep_id in s.depends_on:
                if dep_id not in step_ids:
                    issues.append(
                        f"{prefix} depends_on={dep_id!r} 引用了不存在的 step_id。"
                    )

        # Topological sort to detect cycles
        if step_ids:
            has_bad_ref = any(
                "引用不存在的" in issue or "step_id 为空" in issue
                for issue in issues
            )
            if not has_bad_ref:
                indeg: dict[str, int] = {sid: 0 for sid in step_ids}
                adj: dict[str, list[str]] = {sid: [] for sid in step_ids}
                for s in steps:
                    if not s.step_id:
                        continue
                    for dep_id in s.depends_on:
                        if dep_id in adj:
                            indeg[s.step_id] += 1
                            adj[dep_id].append(s.step_id)
                queue: deque[str] = deque(sid for sid, d in indeg.items() if d == 0)
                sorted_count = 0
                while queue:
                    node = queue.popleft()
                    sorted_count += 1
                    for neighbor in adj[node]:
                        indeg[neighbor] -= 1
                        if indeg[neighbor] == 0:
                            queue.append(neighbor)
                if sorted_count != len(step_ids):
                    issues.append("计划中存在循环依赖。")

        for i, s in enumerate(steps):
            if s.action_type == "verify" and not s.depends_on:
                warnings.append(
                    f"步骤[{i}] {s.step_id!r}: action_type=verify 但 depends_on 为空，"
                    f"缺少校验目标。"
                )

        # --- C. Intent workflow invariants ---
        if (
            intent == "delete_knowledge"
            and not any(s.action_type == "tool_call" and s.tool_name == "delete_note" for s in steps)
        ):
            issues.append("delete_knowledge 计划必须包含 tool_call(delete_note) 步骤。")
        if (
            intent == "solidify_conversation"
            and not any(s.action_type == "tool_call" and s.tool_name == "capture_text" for s in steps)
        ):
            issues.append("solidify_conversation 计划必须包含 tool_call(capture_text) 步骤。")

        # --- D. Plan-level checks ---
        if len(steps) == 0:
            issues.append("计划为空，至少需要 1 个步骤。")
        else:
            if all(s.action_type == "verify" for s in steps):
                warnings.append("计划中所有步骤都是 verify，缺少实际执行步骤。")

            last_step = steps[-1]
            valid_terminal_action = last_step.action_type in ("compose", "verify") or (
                intent in {
                    "solidify_conversation",
                    "capture_text",
                    "capture_link",
                    "capture_file",
                }
                and last_step.action_type == "tool_call"
                and last_step.tool_name == "capture_text"
            )
            if not valid_terminal_action:
                warnings.append(
                    f"步骤投影最后一步是 {last_step.action_type!r}，"
                    f"建议以 compose 或 verify 结尾。"
                )

        # Build corrected steps if any status values were auto-fixed
        corrected: list[ExecutionStep] | None = None
        if bad_status_indices:
            corrected = [_clone_step(s) for s in steps]
            for i in bad_status_indices:
                corrected[i].status = "planned"

        valid = len(issues) == 0
        result = StepProjectionValidationResult(
            valid=valid,
            issues=issues,
            warnings=warnings,
            corrected_steps=corrected,
        )

        if issues:
            logger.warning("Step projection validation found %d issues: %s", len(issues), issues)
        if warnings:
            logger.info("Step projection validation found %d warnings: %s", len(warnings), warnings)
        if valid and not warnings:
            logger.info("Step projection validation passed cleanly.")

        return result

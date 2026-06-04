from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..tools import tool_governance
from .planner import PlanStep
from .router import RiskLevel, RouterDecision

if TYPE_CHECKING:
    from ..tools import ToolExecutor
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

VALID_ACTION_TYPES = {"retrieve", "tool_call", "compose", "verify", "resolve"}
VALID_RISK_LEVELS: set[RiskLevel | str] = {"low", "medium", "high"}
VALID_ON_FAILURE = {"skip", "retry", "abort"}
VALID_EXECUTION_MODES = {"deterministic", "react"}
MAX_REACT_ITERATIONS = 5


@dataclass(slots=True)
class PlanValidationResult:
    valid: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    corrected_steps: list[PlanStep] | None = None
    replanned: bool = False

    @property
    def ok(self) -> bool:
        return len(self.issues) == 0

    @property
    def blocking(self) -> bool:
        """True if there are blocking (critical) issues that prevent safe execution."""
        return not self.ok or self.replanned


def _clone_step(s: PlanStep) -> PlanStep:
    return PlanStep(
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
    )


def _has_upstream_action_type(
    steps: list[PlanStep], step: PlanStep, action_type: str,
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


class PlanValidator:
    """Pre-execution plan validation.

    Validates plan structure, dependency graph integrity, and cross-checks
    against the RouterDecision.  Dynamically resolves known tool names from
    ToolExecutor so the allowlist never drifts from registered tools.
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
        steps: list[PlanStep],
        decision: RouterDecision,
    ) -> PlanValidationResult:
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
                        deferred_draft_text = (
                            s.tool_name == "capture_text"
                            and "text" not in s.tool_input
                            and "text" in err
                            and _has_upstream_action_type(steps, s, "compose")
                        )
                        deferred_delete_note_id = (
                            s.tool_name == "delete_note"
                            and "note_id" not in s.tool_input
                            and "note_id" in err
                            and _has_upstream_action_type(steps, s, "resolve")
                        )
                        if deferred_draft_text or deferred_delete_note_id:
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
                        decision.route == "solidify_conversation"
                        and s.tool_name == "capture_text"
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

            if decision.route == "delete_knowledge":
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

            if decision.route == "solidify_conversation":
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

        # --- C. Cross-validation against RouterDecision ---
        action_types = {s.action_type for s in steps}
        step_risk_levels = {s.risk_level for s in steps}
        has_confirm_step = any(s.requires_confirmation for s in steps)

        if decision.requires_tools and "tool_call" not in action_types:
            warnings.append(
                "RouterDecision.requires_tools=True，"
                "但计划中没有 tool_call 步骤。"
            )
        if decision.requires_retrieval and "retrieve" not in action_types:
            warnings.append(
                "RouterDecision.requires_retrieval=True，"
                "但计划中没有 retrieve 步骤。"
            )
        if decision.requires_confirmation and not has_confirm_step:
            issues.append(
                "RouterDecision.requires_confirmation=True，"
                "但计划中没有 requires_confirmation=True 的步骤。"
            )
        if (
            decision.route == "delete_knowledge"
            and not any(s.action_type == "tool_call" and s.tool_name == "delete_note" for s in steps)
        ):
            issues.append("delete_knowledge 计划必须包含 tool_call(delete_note) 步骤。")
        if (
            decision.route == "solidify_conversation"
            and not any(s.action_type == "tool_call" and s.tool_name == "capture_text" for s in steps)
        ):
            issues.append("solidify_conversation 计划必须包含 tool_call(capture_text) 步骤。")

        # Risk escalation warning
        risk_order = {"low": 0, "medium": 1, "high": 2}
        max_step_risk_num = max((risk_order.get(r, 0) for r in step_risk_levels), default=0)
        decision_risk_num = risk_order.get(decision.risk_level, 0)
        if max_step_risk_num > decision_risk_num:
            max_risk_label = max(step_risk_levels, key=lambda r: risk_order.get(r, 0))
            warnings.append(
                f"计划中最高风险等级（{max_risk_label}）"
                f"高于路由决策的风险等级（{decision.risk_level}），建议确认。"
            )

        # --- D. Plan-level checks ---
        if len(steps) == 0:
            issues.append("计划为空，至少需要 1 个步骤。")
        else:
            if all(s.action_type == "verify" for s in steps):
                warnings.append("计划中所有步骤都是 verify，缺少实际执行步骤。")

            last_step = steps[-1]
            valid_terminal_action = last_step.action_type in ("compose", "verify") or (
                decision.route == "solidify_conversation"
                and last_step.action_type == "tool_call"
                and last_step.tool_name == "capture_text"
            )
            if not valid_terminal_action:
                warnings.append(
                    f"计划最后一步是 {last_step.action_type!r}，"
                    f"建议以 compose 或 verify 结尾。"
                )

        # Build corrected steps if any status values were auto-fixed
        corrected: list[PlanStep] | None = None
        if bad_status_indices:
            corrected = [_clone_step(s) for s in steps]
            for i in bad_status_indices:
                corrected[i].status = "planned"

        valid = len(issues) == 0
        result = PlanValidationResult(
            valid=valid,
            issues=issues,
            warnings=warnings,
            corrected_steps=corrected,
        )

        if issues:
            logger.warning("Plan validation found %d issues: %s", len(issues), issues)
        if warnings:
            logger.info("Plan validation found %d warnings: %s", len(warnings), warnings)
        if valid and not warnings:
            logger.info("Plan validation passed cleanly.")

        return result

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

from .planner import PlanStep
from .router import RiskLevel, RouterDecision

logger = logging.getLogger(__name__)

VALID_ACTION_TYPES = {"retrieve", "tool_call", "compose", "verify"}
VALID_RISK_LEVELS: set[RiskLevel | str] = {"low", "medium", "high"}
VALID_ON_FAILURE = {"skip", "retry", "abort"}
# Tools known to the system; Phase 3 uses a hardcoded allowlist.
# Phase 4 (PlanExecutor) will query ToolRegistry instead.
KNOWN_TOOLS = {
    "graph_search",
    "capture_url",
    "capture_text",
    "capture_upload",
    "delete_note",
}


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
    )


class PlanValidator:
    """Pre-execution plan validation.

    Validates plan structure, dependency graph integrity, and cross-checks
    against the RouterDecision.  Phase 3 is read-only: it logs findings but
    does not block execution.
    """

    def validate(
        self,
        steps: list[PlanStep],
        decision: RouterDecision,
    ) -> PlanValidationResult:
        issues: list[str] = []
        warnings: list[str] = []
        bad_status_indices: list[int] = []

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
            if s.action_type == "tool_call" and s.tool_name and s.tool_name not in KNOWN_TOOLS:
                warnings.append(f"{prefix} tool_name={s.tool_name!r} 不在已知工具列表中。")

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

            last_action = steps[-1].action_type
            if last_action not in ("compose", "verify"):
                warnings.append(
                    f"计划最后一步是 {last_action!r}，"
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

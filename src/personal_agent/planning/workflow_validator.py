"""Workflow spec validation: keep the declarative source of truth self-consistent.

``WorkflowSpecValidator`` validates a :class:`WorkflowSpec` *as a contract*,
which is distinct from :class:`~personal_agent.planning.step_projection_validator.StepProjectionValidator`
that validates a runtime ``ExecutionStep`` projection right before execution. The spec
validator answers a different question: is the declared workflow internally
coherent (unique step ids, resolvable dependencies and edges, enum-valid policy
fields, no dependency cycles, risk/HITL invariants honoured)?

:func:`validate_registry_against_capabilities` goes one step further and checks
that every registered workflow can actually be executed by the orchestration
graph and the tool layer — the consistency gate that prevents the documented
spec from drifting away from the real execution path.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from personal_agent.governance.policy.invariants import (
    delete_longterm_violations,
    high_risk_requires_confirmation,
)
from personal_agent.tools import tool_governance
from personal_agent.planning.workflow import (
    EDGE_SENTINELS,
    WorkflowRegistry,
    WorkflowSpec,
    WorkflowStepSpec,
)

if TYPE_CHECKING:
    from personal_agent.governance import ToolExecutor

logger = logging.getLogger(__name__)

# Action types the orchestration graph's ``_dispatch_step`` can execute.
EXECUTABLE_ACTION_TYPES = {"retrieve", "resolve", "tool_call", "compose", "verify", "repair"}
VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_ON_FAILURE = {"skip", "retry", "abort"}
VALID_EXECUTION_MODES = {"deterministic", "react"}
VALID_BRANCH_POLICIES = {"continue", "clarify", "abort", "human_select", "branch"}
VALID_PROJECTION_POLICIES = {"none", "step_projection"}
KNOWN_SIDE_EFFECTS = {
    "none",
    "read_longterm",
    "write_longterm",
    "delete_longterm",
    "external_network",
}


@dataclass(slots=True)
class WorkflowSpecValidationResult:
    """Outcome of validating one or more workflow specs."""

    valid: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.issues) == 0


def _has_cycle(steps: tuple[WorkflowStepSpec, ...]) -> bool:
    """Kahn topological sort over ``depends_on``; True if a cycle remains."""
    ids = {s.step_id for s in steps}
    indeg: dict[str, int] = {sid: 0 for sid in ids}
    adj: dict[str, list[str]] = {sid: [] for sid in ids}
    for s in steps:
        for dep in s.depends_on:
            if dep in adj:
                indeg[s.step_id] += 1
                adj[dep].append(s.step_id)
    queue: deque[str] = deque(sid for sid, d in indeg.items() if d == 0)
    seen = 0
    while queue:
        node = queue.popleft()
        seen += 1
        for nbr in adj[node]:
            indeg[nbr] -= 1
            if indeg[nbr] == 0:
                queue.append(nbr)
    return seen != len(ids)


class WorkflowSpecValidator:
    """Validate a :class:`WorkflowSpec` as a self-consistent contract."""

    def validate_spec(self, spec: WorkflowSpec) -> WorkflowSpecValidationResult:
        issues: list[str] = []
        warnings: list[str] = []
        wf = spec.workflow_id

        # --- Workflow-level policy enums ---
        if spec.projection_policy not in VALID_PROJECTION_POLICIES:
            issues.append(
                f"[{wf}] projection_policy={spec.projection_policy!r} 无效，"
                f"有效值：{sorted(VALID_PROJECTION_POLICIES)}。"
            )

        ids = [s.step_id for s in spec.steps]
        known = set(ids)

        # --- Duplicate step ids ---
        duplicates = sorted({sid for sid in ids if ids.count(sid) > 1})
        if duplicates:
            issues.append(f"[{wf}] 重复 step_id：{duplicates}。")

        # --- Per-step structural / policy / semantic checks ---
        for step in spec.steps:
            prefix = f"[{wf}] 步骤 {step.step_id!r}:"

            if not step.step_id or not step.step_id.strip():
                issues.append(f"[{wf}] 存在空 step_id。")

            if step.action_type not in EXECUTABLE_ACTION_TYPES:
                issues.append(
                    f"{prefix} action_type={step.action_type!r} 无法被执行器分发，"
                    f"有效值：{sorted(EXECUTABLE_ACTION_TYPES)}。"
                )

            if step.risk_level not in VALID_RISK_LEVELS:
                issues.append(f"{prefix} risk_level={step.risk_level!r} 无效。")
            if step.on_failure not in VALID_ON_FAILURE:
                issues.append(f"{prefix} on_failure={step.on_failure!r} 无效。")
            if step.execution_mode not in VALID_EXECUTION_MODES:
                issues.append(f"{prefix} execution_mode={step.execution_mode!r} 无效。")
            if step.branch_policy not in VALID_BRANCH_POLICIES:
                issues.append(
                    f"{prefix} branch_policy={step.branch_policy!r} 无效，"
                    f"有效值：{sorted(VALID_BRANCH_POLICIES)}。"
                )

            for effect in step.side_effects:
                if effect not in KNOWN_SIDE_EFFECTS:
                    warnings.append(
                        f"{prefix} 未知 side_effect={effect!r}（已知：{sorted(KNOWN_SIDE_EFFECTS)}）。"
                    )

            # Dependencies must resolve within the workflow.
            for dep in step.depends_on:
                if dep not in known:
                    issues.append(f"{prefix} depends_on={dep!r} 引用了不存在的 step_id。")

            # Conditional edge targets: a peer step id or a terminal sentinel.
            for edge in step.conditional_edges:
                if not edge.condition or not edge.condition.strip():
                    issues.append(f"{prefix} 条件边的 condition 为空。")
                if edge.target not in known and edge.target not in EDGE_SENTINELS:
                    issues.append(
                        f"{prefix} 条件边 target={edge.target!r} 既不是已知 step_id，"
                        f"也不是合法终止哨兵：{sorted(EDGE_SENTINELS)}。"
                    )

            if step.action_type == "tool_call" and not step.tool_name:
                issues.append(f"{prefix} action_type=tool_call 但 tool_name 为空。")

            if step.execution_mode == "react":
                if step.risk_level == "high":
                    issues.append(f"{prefix} react 步骤不允许 risk_level='high'。")
                if step.requires_confirmation:
                    issues.append(f"{prefix} react 步骤不允许 requires_confirmation=True。")
                if step.max_iterations < 1:
                    issues.append(f"{prefix} max_iterations 必须为正整数。")

            # --- Semantic invariants (shared definitions: policy/invariants.py) ---
            _delete_messages = {
                "risk": f"{prefix} 含 delete_longterm 副作用，必须声明 risk_level='high'。",
                "confirmation": f"{prefix} 含 delete_longterm 副作用，必须 requires_confirmation=True。",
                "hitl": f"{prefix} 含 delete_longterm 副作用，必须声明非 none 的 hitl_policy。",
            }
            for code in delete_longterm_violations(
                side_effects=step.side_effects,
                risk_level=step.risk_level,
                requires_confirmation=step.requires_confirmation,
                hitl_policy=step.hitl_policy,
            ):
                issues.append(_delete_messages[code])

            if high_risk_requires_confirmation(step.risk_level, step.requires_confirmation):
                issues.append(
                    f"{prefix} risk_level='high' 必须 requires_confirmation=True。"
                )

            # ``human_select`` is meaningful only where the workflow picks a
            # target from candidates — i.e. a resolve node.
            if step.branch_policy == "human_select" and step.action_type != "resolve":
                warnings.append(
                    f"{prefix} branch_policy='human_select' 通常只用于 resolve 步骤，"
                    f"当前 action_type={step.action_type!r}。"
                )

        # --- Dependency cycle detection (only if ids are sane) ---
        if known and not duplicates and all(s.step_id for s in spec.steps):
            unresolved = any(
                dep not in known for s in spec.steps for dep in s.depends_on
            )
            if not unresolved and _has_cycle(spec.steps):
                issues.append(f"[{wf}] 步骤依赖存在循环。")

        # --- Projection coherence ---
        if spec.requires_projection and not spec.project():
            issues.append(
                f"[{wf}] projection_policy='step_projection' 但投影结果为空，"
                "至少需要 1 个 project_to_plan=True 的步骤。"
            )

        valid = len(issues) == 0
        if issues:
            logger.warning("Workflow spec %s invalid: %s", wf, issues)
        return WorkflowSpecValidationResult(valid=valid, issues=issues, warnings=warnings)

    def validate_registry(self, registry: WorkflowRegistry) -> WorkflowSpecValidationResult:
        """Validate every spec registered in a :class:`WorkflowRegistry`."""
        all_issues: list[str] = []
        all_warnings: list[str] = []
        for spec in registry.all_specs():
            result = self.validate_spec(spec)
            all_issues.extend(result.issues)
            all_warnings.extend(result.warnings)
        return WorkflowSpecValidationResult(
            valid=len(all_issues) == 0,
            issues=all_issues,
            warnings=all_warnings,
        )


def validate_registry_against_capabilities(
    registry: WorkflowRegistry,
    tool_executor: "ToolExecutor | None" = None,
) -> WorkflowSpecValidationResult:
    """Check registered workflows match real execution + tool capabilities.

    This is the spec↔wiring consistency gate. It fails when a workflow declares
    something the orchestration graph or tool layer cannot actually honour, so a
    drift between the documented spec and the executable path is caught in tests
    rather than at runtime.
    """
    issues: list[str] = []
    warnings: list[str] = []

    known_tools: set[str] = set()
    if tool_executor is not None:
        known_tools = {t.name for t in tool_executor.list_tools()}

    for spec in registry.all_specs():
        wf = spec.workflow_id
        for step in spec.steps:
            prefix = f"[{wf}] 步骤 {step.step_id!r}:"

            # Every action type must be dispatchable by the graph executor.
            if step.action_type not in EXECUTABLE_ACTION_TYPES:
                issues.append(
                    f"{prefix} action_type={step.action_type!r} 不在执行器可分发集合内。"
                )

            # Referenced tools must be registered.
            referenced = set(step.allowed_tools)
            if step.tool_name:
                referenced.add(step.tool_name)
            for tool_name in referenced:
                if known_tools and tool_name not in known_tools:
                    issues.append(
                        f"{prefix} 引用的工具 {tool_name!r} 未在 ToolExecutor 中注册。"
                    )

            # Cross-check declared side effects against tool governance truth.
            if (
                tool_executor is not None
                and step.tool_name
                and step.tool_name in known_tools
            ):
                tool = tool_executor.get(step.tool_name)
                if tool is not None:
                    try:
                        governance = tool_governance(tool)
                    except ValueError:
                        warnings.append(
                            f"{prefix} 工具 {step.tool_name!r} 缺少治理元数据，无法交叉校验。"
                        )
                    else:
                        if (
                            governance.requires_confirmation
                            and not step.requires_confirmation
                        ):
                            issues.append(
                                f"{prefix} 工具 {step.tool_name!r} 要求确认，"
                                "但步骤未声明 requires_confirmation。"
                            )
                        missing = [
                            e
                            for e in governance.side_effects
                            if e != "none" and e not in step.side_effects
                        ]
                        if missing:
                            warnings.append(
                                f"{prefix} 工具 {step.tool_name!r} 的副作用 {missing} "
                                "未在步骤 side_effects 中声明。"
                            )

        # Projection policy must agree with whether the graph would plan it.
        if spec.requires_projection and not spec.project():
            issues.append(
                f"[{wf}] 声明 step_projection 但无法投影出可执行步骤。"
            )

    valid = len(issues) == 0
    if issues:
        logger.warning("Workflow registry capability check failed: %s", issues)
    return WorkflowSpecValidationResult(valid=valid, issues=issues, warnings=warnings)

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import ValidationError

from personal_agent.kernel.models import EntryIntent
from personal_agent.tools import tool_governance
from personal_agent.kernel.contracts.execution import ExecutionStep

if TYPE_CHECKING:
    from personal_agent.governance import ToolExecutor
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

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
    """Pre-execution gate for runtime tool executability.

    Workflow topology and step structure are gated by WorkflowSpecValidator in
    CI / deployment checks. This runtime gate only checks facts that depend on
    the currently wired ToolExecutor or dynamic execution-time parameter
    injection.
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
        known_tools = self._get_known_tools()

        # --- A. Tool executability checks ---
        for i, s in enumerate(steps):
            prefix = f"步骤[{i}] {s.step_id!r}:"

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

            # ReAct execution mode checks
            exec_mode = getattr(s, "execution_mode", "deterministic")
            if exec_mode == "react":
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

        valid = len(issues) == 0
        result = StepProjectionValidationResult(
            valid=valid,
            issues=issues,
            warnings=warnings,
        )

        if issues:
            logger.warning("Step projection validation found %d issues: %s", len(issues), issues)
        if warnings:
            logger.info("Step projection validation found %d warnings: %s", len(warnings), warnings)
        if valid and not warnings:
            logger.info("Step projection validation passed cleanly.")

        return result

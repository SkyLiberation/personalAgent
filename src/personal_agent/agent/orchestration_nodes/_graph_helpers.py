"""Pure helpers and constants shared by orchestration graph nodes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from collections import deque

from ...core.prompts import get_prompt
from ..orchestration_contexts import ReactContext

if TYPE_CHECKING:
    from ..execution_models import ExecutionStep

# ---------------------------------------------------------------------------
# Constants for checkpointed orchestration behavior
# ---------------------------------------------------------------------------

_RETRY_DELAY_SECONDS = 2.0

# ReAct constants used by checkpointed graph nodes.
_REACT_MAX_ITERATIONS_CAP = 5
_REACT_DEFAULT_ALLOWED_TOOLS = ("graph_search", "web_search")

_REACT_SYSTEM_PROMPT = get_prompt("react.system").template


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _topological_sort_steps(steps: list) -> list:
    """Sort execution steps so dependencies come before dependents."""
    if len(steps) <= 1:
        return list(steps)
    step_ids = {s.step_id for s in steps if s.step_id}
    indeg: dict[int, int] = {}
    adj: dict[int, list[int]] = {}
    for i, s in enumerate(steps):
        indeg[i] = 0
        adj[i] = []
        for dep_id in s.depends_on:
            if dep_id in step_ids:
                indeg[i] = indeg.get(i, 0) + 1
                for j, other in enumerate(steps):
                    if other.step_id == dep_id:
                        adj.setdefault(j, []).append(i)
                        break
    q: deque[int] = deque(i for i, d in indeg.items() if d == 0)
    result: list = []
    while q:
        i = q.popleft()
        result.append(steps[i])
        for ni in adj.get(i, []):
            indeg[ni] -= 1
            if indeg[ni] == 0:
                q.append(ni)
    return result


def _inject_note_id_into_steps(
    resolve_step_id: str, note_id: str, user_id: str, steps: list,
) -> None:
    by_id = {s.step_id: s for s in steps}

    def depends_on_resolve(step) -> bool:
        pending = list(step.depends_on)
        visited: set[str] = set()
        while pending:
            step_id = pending.pop()
            if step_id == resolve_step_id:
                return True
            if step_id in visited:
                continue
            visited.add(step_id)
            parent = by_id.get(step_id)
            if parent is not None:
                pending.extend(parent.depends_on)
        return False

    for s in steps:
        if s.status != "planned":
            continue
        if (depends_on_resolve(s)
                and s.action_type == "tool_call"
                and s.tool_name == "delete_note"):
            if not s.tool_input:
                s.tool_input = {}
            s.tool_input["note_id"] = note_id
            s.tool_input["user_id"] = user_id


def _inject_draft_text_into_steps(
    compose_step_id: str, text: str, user_id: str, steps: list,
) -> None:
    by_id = {s.step_id: s for s in steps}

    def depends_on_compose(step) -> bool:
        pending = list(step.depends_on)
        visited: set[str] = set()
        while pending:
            step_id = pending.pop()
            if step_id == compose_step_id:
                return True
            if step_id in visited:
                continue
            visited.add(step_id)
            parent = by_id.get(step_id)
            if parent is not None:
                pending.extend(parent.depends_on)
        return False

    for s in steps:
        if s.status != "planned":
            continue
        if (depends_on_compose(s)
                and s.action_type == "tool_call"
                and s.tool_name == "capture_text"):
            if not s.tool_input:
                s.tool_input = {}
            s.tool_input["text"] = text
            s.tool_input["user_id"] = user_id


def _skip_step_dependents(failed_step_id: str, steps: list) -> None:
    """Recursively mark dependents of a failed step as skipped."""
    for s in steps:
        if s.status != "planned":
            continue
        if failed_step_id in s.depends_on:
            s.status = "skipped"
            _skip_step_dependents(s.step_id, steps)


def _default_step_answer(steps: list) -> str:
    completed = sum(1 for s in steps if s.status == "completed")
    failed = sum(1 for s in steps if s.status == "failed")
    skipped = sum(1 for s in steps if s.status == "skipped")
    return f"步骤执行完成：{completed} 步成功" + (
        f"，{failed} 步失败" if failed else ""
    ) + (
        f"，{skipped} 步跳过" if skipped else ""
    ) + "。"


# ---------------------------------------------------------------------------
# ReAct helper functions used by the graph-native ReAct nodes.
# ---------------------------------------------------------------------------


def _resolve_allowed_tools_for_step(step: "ExecutionStep", deps: ReactContext) -> set[str]:
    allowed = set(step.allowed_tools) if step.allowed_tools else set(_REACT_DEFAULT_ALLOWED_TOOLS)
    registered = {
        t.name for t in deps.tool_executor.list_tools(
            exposures={"public_agent", "scoped_agent", "admin"}
        )
    }
    return allowed & registered


def _is_react_tool_blocked(tool_name: str, deps: ReactContext) -> bool:
    """Whether a tool may not run in ReAct autonomous mode, per the policy engine.

    The tool's governance snapshot is fed to the shared ``PolicyEngine`` so the
    block decision matches what the ToolGateway would enforce at execution time.
    """
    from ...policy import PolicyEngine, PolicyInput
    from ...tools import tool_governance

    spec = next((t for t in deps.tool_executor.list_tools() if t.name == tool_name), None)
    if spec is None:
        return True
    governance = tool_governance(spec)
    decision = deps.policy_engine.evaluate(
        PolicyInput(
            action="tool_call",
            execution_mode="react",
            tool_name=tool_name,
            risk_level=governance.risk_level,
            requires_confirmation=governance.requires_confirmation,
            side_effects=tuple(governance.side_effects),
            permission_scope=governance.permission_scope,
            # ReAct 预过滤只判断工具本身是否属于高风险/写操作，不在此校验
            # allow-list（调用点已先做 allow-list 检查），故放开允许集合。
            react_allowed_tools=frozenset({tool_name}),
        )
    )
    return not decision.allowed

"""Pure helpers and constants shared by orchestration graph nodes."""

from __future__ import annotations

from collections import deque

from personal_agent.kernel.prompts import get_prompt
from personal_agent.orchestration.orchestration_contexts import ReactContext

# ---------------------------------------------------------------------------
# Constants for checkpointed orchestration behavior
# ---------------------------------------------------------------------------

_RETRY_DELAY_SECONDS = 2.0

# ReAct constants used by checkpointed graph nodes.
_REACT_MAX_ITERATIONS_CAP = 5
_REACT_SYSTEM_PROMPT = get_prompt("react.system").template


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _topological_sort_steps(steps: list) -> list:
    """Sort execution steps so dependencies come before dependents."""
    if not steps:
        return list(steps)
    step_ids = [s.step_id for s in steps if s.step_id]
    if len(set(step_ids)) != len(step_ids):
        raise ValueError("Step DAG contains duplicate step_id values.")
    step_id_set = set(step_ids)
    id_to_index = {s.step_id: i for i, s in enumerate(steps) if s.step_id}
    indeg: dict[int, int] = {}
    adj: dict[int, list[int]] = {}
    for i, s in enumerate(steps):
        indeg[i] = 0
        adj[i] = []
        for dep_id in s.depends_on:
            if dep_id not in step_id_set:
                raise ValueError(
                    f"Step DAG dependency {s.step_id!r} -> {dep_id!r} "
                    "references an unknown step."
                )
            indeg[i] = indeg.get(i, 0) + 1
            adj.setdefault(id_to_index[dep_id], []).append(i)
    q: deque[int] = deque(i for i, d in indeg.items() if d == 0)
    result: list = []
    while q:
        i = q.popleft()
        result.append(steps[i])
        for ni in adj.get(i, []):
            indeg[ni] -= 1
            if indeg[ni] == 0:
                q.append(ni)
    if len(result) != len(steps):
        cyclic = [steps[i].step_id for i, d in indeg.items() if d > 0]
        raise ValueError(
            "Step DAG contains a dependency cycle involving "
            f"{', '.join(cyclic)}."
        )
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


# ---------------------------------------------------------------------------
# ReAct helper functions used by the graph-native ReAct nodes.
# ---------------------------------------------------------------------------


def _is_react_tool_blocked(tool_name: str, deps: ReactContext) -> bool:
    """Whether a tool may not run in ReAct autonomous mode, per the policy engine.

    The tool's governance snapshot is fed to the shared ``PolicyEngine`` so the
    block decision matches what the ToolGateway would enforce at execution time.
    """
    from personal_agent.governance.policy import PolicyInput
    from personal_agent.tools import tool_governance

    spec = next((t for t in deps.tool_executor.list_tools() if t.name == tool_name), None)
    if spec is None:
        return True
    governance = tool_governance(spec)
    if governance.requires_confirmation or any(
        effect != "none" and ("write" in effect or "delete" in effect)
        for effect in governance.side_effects
    ):
        return True
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

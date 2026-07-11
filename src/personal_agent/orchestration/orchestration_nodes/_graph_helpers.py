"""Pure helpers and constants shared by orchestration graph nodes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from collections import deque

from personal_agent.kernel.prompts import get_prompt
from personal_agent.kernel.contracts.capability import (
    CapabilityRequirement,
    CapabilityResolution,
    CapabilityResolutionRequest,
)
from personal_agent.orchestration.orchestration_contexts import ReactContext
from personal_agent.planning.capability_resolver import (
    CapabilityResolver,
    default_capability_policy_for_scope,
)
from personal_agent.tools.mcp_capability import build_capability_registry

if TYPE_CHECKING:
    from personal_agent.kernel.contracts.execution import ExecutionStep

# ---------------------------------------------------------------------------
# Constants for checkpointed orchestration behavior
# ---------------------------------------------------------------------------

_RETRY_DELAY_SECONDS = 2.0

# ReAct constants used by checkpointed graph nodes.
_REACT_MAX_ITERATIONS_CAP = 5
_REACT_DEFAULT_ALLOWED_TOOLS = (
    "graph_search",
    "web_search",
)

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
    resolution = _resolve_capability_resolution_for_step(step, deps)
    if resolution is not None:
        allowed = set(resolution.allowed_tools)
    else:
        allowed = set(step.allowed_tools) if step.allowed_tools else set(_REACT_DEFAULT_ALLOWED_TOOLS)
    registered = {
        t.name for t in deps.tool_executor.list_tools(
            exposures={"public_agent", "scoped_agent", "admin"}
        )
    }
    return allowed & registered


def _capability_resolution_payload(resolution: CapabilityResolution) -> dict[str, object]:
    """Stable trace shape shared by deterministic, ReAct, and agent steps."""
    return {
        "scope_id": resolution.request.scope_id,
        "resolution_id": resolution.resolution_id,
        "lifecycle_state": resolution.lifecycle_state,
        "workflow_id": resolution.request.workflow_id,
        "step_id": resolution.request.step_id,
        "step_action_type": resolution.request.step_action_type,
        "selected_capability_ids": [item.capability_id for item in resolution.selected_capabilities],
        "allowed_tools": list(resolution.allowed_tools),
        "selected_retrievers": list(resolution.selected_retrievers),
        "allowed_agents": list(resolution.allowed_agents),
        "workflow_actions": list(resolution.workflow_actions),
        "coverage": [item.model_dump(mode="json") for item in resolution.coverage],
        "denied_capability_ids": [item.capability_id for item in resolution.denied_capabilities],
        "denial_reasons": {item.capability_id: item.reason for item in resolution.denied_capabilities},
        "constraints": resolution.constraints,
        "escalation_hint": (
            resolution.escalation_hint.model_dump(mode="json")
            if resolution.escalation_hint is not None else None
        ),
        "rationale": resolution.rationale,
        "confidence": resolution.confidence,
    }


def _resolve_capability_resolution_for_step(
    step: "ExecutionStep",
    deps: ReactContext,
) -> CapabilityResolution | None:
    requirements = tuple(
        CapabilityRequirement.model_validate(raw)
        for raw in step.capability_requirements
        if isinstance(raw, dict)
    )
    if requirements:
        agent_requirement = all("delegate" in requirement.operations for requirement in requirements)
        allowed_kinds = ("agent",) if agent_requirement else ("local_tool", "mcp_tool")
        allowed_operations = tuple(dict.fromkeys(
            operation
            for requirement in requirements
            for operation in requirement.operations
        ))
        tools = deps.tool_executor.list_tools(exposures={"public_agent", "scoped_agent", "admin"})
        agent_gateway = getattr(deps, "agent_gateway", None)
        registry = build_capability_registry(
            tools=tools,
            agents=agent_gateway.definitions() if agent_gateway is not None else (),
        )
        resource_locator = next((
            requirement.resource_locator for requirement in requirements if requirement.resource_locator
        ), "")
        request = CapabilityResolutionRequest(
            task_text=step.task_input or step.description,
            workflow_id=step.workflow_id,
            step_action_type=step.meta_capability or getattr(step, "execution_mode", "") or step.action_type,
            allowed_kinds=allowed_kinds,
            allowed_operations=allowed_operations,
            requirements=requirements,
            step_id=step.step_id,
            policy=default_capability_policy_for_scope(step.workflow_id),
            runtime_context={
                "expected_local_names": [step.agent_id] if step.agent_id else [],
                "resource_locator": resource_locator,
            },
        )
        return CapabilityResolver(registry, policy_engine=deps.policy_engine).resolve(request)
    if step.workflow_id in {
        "external_codebase_qa",
        "external_workspace_qa",
        "external_project_ops",
    }:
        registry = build_capability_registry(deps.tool_executor.list_tools(
            exposures={"public_agent", "scoped_agent", "admin"}
        ))
        request = CapabilityResolutionRequest(
            task_text=step.task_input or step.description,
            workflow_id=step.workflow_id,
            step_action_type=getattr(step, "execution_mode", "") or step.action_type,
            allowed_kinds=("mcp_tool",),
            step_id=step.step_id,
            policy=default_capability_policy_for_scope(step.workflow_id),
        )
        return CapabilityResolver(registry, policy_engine=deps.policy_engine).resolve(request)
    if step.tool_name:
        registry = build_capability_registry(deps.tool_executor.list_tools(
            exposures={"public_agent", "scoped_agent", "admin"}
        ))
        capability = registry.get_by_name(step.tool_name)
        if capability is None:
            return None
        request = CapabilityResolutionRequest(
            task_text=step.task_input or step.description,
            workflow_id=step.workflow_id,
            step_action_type=step.action_type,
            allowed_kinds=(capability.kind,),
            allowed_operations=capability.operations,
            step_id=step.step_id,
            policy=default_capability_policy_for_scope(step.workflow_id),
            runtime_context={"expected_local_names": [step.tool_name]},
        )
        return CapabilityResolver(registry, policy_engine=deps.policy_engine).resolve(request)
    if step.workflow_id == "gpt_researcher_a2a" and step.agent_id:
        agent_gateway = getattr(deps, "agent_gateway", None)
        if agent_gateway is None:
            return None
        registry = build_capability_registry(
            agents=agent_gateway.definitions(),
        )
        request = CapabilityResolutionRequest(
            task_text=step.task_input or step.description,
            workflow_id=step.workflow_id,
            step_action_type=step.action_type,
            allowed_kinds=("agent",),
            allowed_operations=("delegate",),
            step_id=step.step_id,
            policy=default_capability_policy_for_scope(step.workflow_id),
            runtime_context={"expected_local_names": [step.agent_id]},
        )
        return CapabilityResolver(registry, policy_engine=deps.policy_engine).resolve(request)
    return None


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

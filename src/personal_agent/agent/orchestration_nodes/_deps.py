"""Orchestration graph dependencies and step execution utility helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from collections import deque
from dataclasses import dataclass
from typing import Callable

from ...core.prompts import get_prompt

if TYPE_CHECKING:
    from ...capture import CaptureService
    from ...core.config import Settings
    from ...core.models import EntryInput
    from ...graphiti.store import GraphitiStore
    from ...memory import MemoryFacade
    from ...policy import PolicyEngine
    from ...tools import ToolExecutor
    from ..ask import AskRunContextStore
    from ..runtime_ask import AskService
    from ..step_projection_validator import StepProjectionValidator
    from ..step_projector import ExecutionStep
    from ..replanner import Replanner
    from ..router import DefaultIntentRouter
    from ..runtime_results import AskResult, CaptureResult
    from ..verifier import AnswerVerifier

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class OrchestrationDeps:
    """Explicit dependencies used by the entry orchestration graph."""

    settings: "Settings"
    memory: "MemoryFacade"
    intent_router: "DefaultIntentRouter"
    step_projector: object
    step_projection_validator: "StepProjectionValidator"
    replanner: "Replanner | None"
    verifier: "AnswerVerifier | None"
    tool_executor: "ToolExecutor"
    graph_store: "GraphitiStore"
    execute_ask: Callable[..., "AskResult"]
    ask_service_factory: Callable[[], "AskService"]
    ask_run_context_store: "AskRunContextStore"
    policy_engine: "PolicyEngine | None" = None
    execute_capture: Callable[..., "CaptureResult"] | None = None
    capture_service: "CaptureService | None" = None
    summarize_chat: Callable[[str, str], str] | None = None
    compress_context: Callable[[str, str], str] | None = None
    load_thread_messages: Callable[["EntryInput", int], list[dict[str, str]]] | None = None

    @classmethod
    def from_runtime(cls, runtime) -> "OrchestrationDeps":
        from ..ask import AskRunContextStore

        return cls(
            settings=runtime.settings,
            memory=runtime.memory,
            intent_router=runtime.intent_router,
            step_projector=runtime.step_projector,
            step_projection_validator=runtime.step_projection_validator,
            replanner=getattr(runtime, "_replanner", None),
            verifier=getattr(runtime, "_verifier", None),
            tool_executor=runtime.tool_executor,
            graph_store=runtime.graph_store,
            execute_ask=runtime.execute_ask,
            ask_service_factory=runtime._ask_service,
            ask_run_context_store=AskRunContextStore(),
            policy_engine=getattr(runtime, "_policy_engine", None),
            execute_capture=runtime.execute_capture,
            capture_service=runtime.capture_service,
            summarize_chat=runtime.summarize_chat,
            compress_context=runtime.compress_context,
            load_thread_messages=runtime.load_thread_messages,
        )

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


def _resolve_allowed_tools_for_step(step: "ExecutionStep", deps: OrchestrationDeps) -> set[str]:
    allowed = set(step.allowed_tools) if step.allowed_tools else set(_REACT_DEFAULT_ALLOWED_TOOLS)
    registered = {t.name for t in deps.tool_executor.list_tools()}
    return allowed & registered


def _is_react_tool_blocked(tool_name: str, deps: OrchestrationDeps) -> bool:
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
    engine = deps.policy_engine or PolicyEngine()
    decision = engine.evaluate(
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

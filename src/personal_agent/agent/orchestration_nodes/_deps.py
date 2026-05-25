"""Orchestration graph dependencies and plan utility helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from collections import deque
from dataclasses import dataclass
from typing import Callable

if TYPE_CHECKING:
    from ...capture import CaptureService
    from ...core.config import Settings
    from ...core.models import EntryInput
    from ...graphiti.store import GraphitiStore
    from ...memory import MemoryFacade
    from ...storage.postgres_memory_store import PostgresMemoryStore
    from ...tools import ToolRegistry
    from ..plan_validator import PlanValidator
    from ..planner import PlanStep
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
    planner: object
    plan_validator: "PlanValidator"
    replanner: "Replanner | None"
    verifier: "AnswerVerifier | None"
    tool_registry: "ToolRegistry"
    graph_store: "GraphitiStore"
    store: "PostgresMemoryStore"
    execute_ask: Callable[..., "AskResult"]
    execute_capture: Callable[..., "CaptureResult"] | None = None
    capture_service: "CaptureService | None" = None
    summarize_thread: Callable[[str, str], str] | None = None
    load_thread_messages: Callable[["EntryInput", int], list[dict[str, str]]] | None = None

    @classmethod
    def from_runtime(cls, runtime) -> "OrchestrationDeps":
        return cls(
            settings=runtime.settings,
            memory=runtime.memory,
            intent_router=runtime.intent_router,
            planner=runtime.planner,
            plan_validator=runtime.plan_validator,
            replanner=getattr(runtime, "_replanner", None),
            verifier=getattr(runtime, "_verifier", None),
            tool_registry=runtime.tool_registry,
            graph_store=runtime.graph_store,
            store=runtime.store,
            execute_ask=runtime.execute_ask,
            execute_capture=runtime.execute_capture,
            capture_service=runtime.capture_service,
            summarize_thread=runtime._summarize_thread,
            load_thread_messages=runtime.load_thread_messages,
        )

# ---------------------------------------------------------------------------
# Constants (mirrored from plan_executor for replay-safe retry)
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 2.0

# ReAct constants (mirrored from react_runner.py)
_REACT_MAX_ITERATIONS_CAP = 5
_REACT_BLOCKED_TOOL_PREFIXES = ("delete_", "capture_")
_REACT_DEFAULT_ALLOWED_TOOLS = ("graph_search", "web_search")

_REACT_SYSTEM_PROMPT = (
    "你是一个在受控环境中执行任务步骤的推理助手。"
    "每一轮你需要输出 JSON：\n"
    '- 仍在推理：{"thought":"...","tool":"工具名","input":{...}}\n'
    '- 已完成：{"thought":"...","done":true,"result":{...}}\n\n'
    "tool 必须在可用工具列表中。result 应包含步骤产出的结构化数据。\n"
    "不要输出 JSON 以外的内容。"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _topological_sort_steps(steps: list) -> list:
    """Sort plan steps so dependencies come before dependents."""
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


def _inject_note_id_into_steps(resolve_step_id: str, note_id: str, plan_steps: list) -> None:
    for s in plan_steps:
        if s.status != "planned":
            continue
        if (resolve_step_id in s.depends_on
                and s.action_type == "tool_call"
                and s.tool_name == "delete_note"):
            if not s.tool_input:
                s.tool_input = {}
            s.tool_input["note_id"] = note_id


def _inject_draft_text_into_steps(
    compose_step_id: str, text: str, user_id: str, plan_steps: list,
) -> None:
    by_id = {s.step_id: s for s in plan_steps}

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

    for s in plan_steps:
        if s.status != "planned":
            continue
        if (depends_on_compose(s)
                and s.action_type == "tool_call"
                and s.tool_name == "capture_text"):
            if not s.tool_input:
                s.tool_input = {}
            s.tool_input["text"] = text
            s.tool_input["user_id"] = user_id


def _skip_step_dependents(failed_step_id: str, plan_steps: list) -> None:
    """Recursively mark dependents of a failed step as skipped."""
    for s in plan_steps:
        if s.status != "planned":
            continue
        if failed_step_id in s.depends_on:
            s.status = "skipped"
            _skip_step_dependents(s.step_id, plan_steps)


def _default_plan_answer(steps: list) -> str:
    completed = sum(1 for s in steps if s.status == "completed")
    failed = sum(1 for s in steps if s.status == "failed")
    skipped = sum(1 for s in steps if s.status == "skipped")
    return f"计划执行完成：{completed} 步成功" + (
        f"，{failed} 步失败" if failed else ""
    ) + (
        f"，{skipped} 步跳过" if skipped else ""
    ) + "。"


# ---------------------------------------------------------------------------
# ReAct helper functions (ported from ReActStepRunner for graph use)
# ---------------------------------------------------------------------------


def _resolve_allowed_tools_for_step(step: "PlanStep", deps: OrchestrationDeps) -> set[str]:
    allowed = set(step.allowed_tools) if step.allowed_tools else set(_REACT_DEFAULT_ALLOWED_TOOLS)
    registered = {t.name for t in deps.tool_registry.list_tools()}
    return allowed & registered


def _is_react_tool_blocked(tool_name: str, deps: OrchestrationDeps) -> bool:
    spec = None
    for t in deps.tool_registry.list_tools():
        if t.name == tool_name:
            spec = t
            break
    if spec is None:
        return True
    if spec.risk_level == "high" or spec.requires_confirmation or spec.writes_longterm:
        return True
    if any(tool_name.startswith(p) for p in _REACT_BLOCKED_TOOL_PREFIXES):
        return True
    return False

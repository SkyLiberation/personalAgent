"""Workflow / step planning: deterministic projection of fixed workflows.

The planner no longer asks an LLM to invent step topologies. Fixed flows are
declared once in :mod:`personal_agent.agent.workflow` and projected here into
``PlanStep`` objects. Genuine per-request semantic judgment (resolving a delete
target, drafting solidify text) happens at *execution* time inside the
orchestration graph's ``resolve`` / ``compose`` nodes, not during planning.

``PlanValidator`` still validates every projection before execution as the
pre-execution safety gate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from ..core.config import Settings
from ..core.models import EntryIntent
from ..tools import ToolExecutor

logger = logging.getLogger(__name__)
ConversationMessage = dict[str, str]


@dataclass(slots=True)
class PlanStep:
    """A single step in a task plan with execution metadata.

    action_type: "retrieve", "resolve", "tool_call", "compose", or "verify"
    status: "planned" (initial) -> "running" -> "completed" / "failed" / "skipped"
    """

    step_id: str = field(default_factory=lambda: uuid4().hex[:8])
    action_type: str = ""  # retrieve / resolve / tool_call / compose / verify
    description: str = ""  # user-visible label
    tool_name: str | None = None
    tool_input: dict[str, object] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    expected_output: str = ""
    success_criteria: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = False
    on_failure: str = "skip"  # skip / retry / abort
    status: str = "planned"  # planned / running / completed / failed / skipped
    retry_count: int = 0
    execution_mode: str = "deterministic"  # "deterministic" | "react"
    allowed_tools: list[str] = field(default_factory=list)  # empty = read-only defaults
    max_iterations: int = 3  # max ReAct iterations


class TaskPlanner(Protocol):
    def plan(
        self,
        intent: EntryIntent,
        context: str,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> list[PlanStep]:
        ...


class DefaultTaskPlanner:
    """Deterministic workflow projector.

    Selects the registered :class:`WorkflowSpec` for an intent and projects it
    into a fresh list of executable ``PlanStep`` objects. There is no LLM call in
    the planning path: the topology of every supported flow is fixed and
    declared in :mod:`personal_agent.agent.workflow`. Semantic decisions are
    deferred to execution-time graph nodes.

    The ``settings`` / ``tool_executor`` arguments are retained for construction
    compatibility with the runtime composition root; projection itself needs
    neither.
    """

    def __init__(self, settings: Settings, tool_executor: ToolExecutor | None = None) -> None:
        self._settings = settings
        self._tool_executor = tool_executor

    def plan(
        self,
        intent: EntryIntent,
        context: str = "",
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> list[PlanStep]:
        # ``context`` / ``conversation_messages`` no longer shape the topology;
        # they remain in the signature so callers (and the TaskPlanner protocol)
        # are unchanged. Per-request semantics are resolved at execution time.
        from .workflow import WORKFLOW_REGISTRY

        steps = WORKFLOW_REGISTRY.project(intent)
        logger.info("planner projected workflow intent=%s steps=%d", intent, len(steps))
        return steps

    def fallback_plan(self, intent: EntryIntent) -> list[PlanStep]:
        """Return the deterministic projection for ``intent``.

        Kept as a distinct method for validator fallback call sites; identical to
        ``plan`` now that projection is deterministic and cannot fail.
        """
        from .workflow import WORKFLOW_REGISTRY

        return WORKFLOW_REGISTRY.project(intent)

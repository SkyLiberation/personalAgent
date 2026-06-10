"""Workflow / step planning: deterministic selection and step projection.

The planner no longer asks an LLM to invent step topologies. Fixed workflows are
declared once in :mod:`personal_agent.agent.workflow`; ordinary branch workflows
are selected there and executed by their own graph branches, while high-value
checkpointable workflows are projected here into workflow step projections.
Genuine
per-request semantic judgment (resolving a delete target, drafting solidify
text) happens at *execution* time inside the orchestration graph's ``resolve`` /
``compose`` nodes, not during planning.

``PlanValidator`` validates step projections before execution as the
pre-execution safety gate. Intents that do not require projection return an
empty plan and should surface their progress through ``execution_trace``.
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
    """A workflow step projection with execution metadata.

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
    workflow_id: str = ""
    workflow_version: str = ""
    workflow_step_id: str = ""
    projection_kind: str = "workflow_step"


class TaskPlanner(Protocol):
    def plan(
        self,
        intent: EntryIntent,
        context: str,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> list[PlanStep]:
        ...


class DefaultTaskPlanner:
    """Deterministic workflow selector and step projector.

    Selects the registered :class:`WorkflowSpec` for an intent. Only specs marked
    ``requires_projection`` are projected into executable ``PlanStep`` objects.
    There is no LLM call in the planning path: supported workflow contracts are
    declared in :mod:`personal_agent.agent.workflow`, while semantic decisions
    are deferred to execution-time graph nodes.

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
        spec = WORKFLOW_REGISTRY.select(intent)
        logger.info(
            "planner selected workflow intent=%s workflow=%s requires_projection=%s steps=%d",
            intent, spec.workflow_id, spec.requires_projection, len(steps),
        )
        return steps

    def fallback_plan(self, intent: EntryIntent) -> list[PlanStep]:
        """Return the deterministic step projection for ``intent``.

        Kept as a distinct method for validator fallback call sites. Ordinary
        branch workflows return an empty list here by design.
        """
        from .workflow import WORKFLOW_REGISTRY

        return WORKFLOW_REGISTRY.project(intent)

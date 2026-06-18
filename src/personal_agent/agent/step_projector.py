"""Workflow step projection: deterministic workflow selection and step creation.

This module is not a planner. Fixed workflows are declared in
:mod:`personal_agent.agent.workflow`; ordinary branch workflows are selected
there and executed by their graph branches, while checkpointable workflows are
projected here into ``ExecutionStep`` objects. Per-request semantic judgment
(resolving a delete target, drafting solidify text) happens at execution time
inside the orchestration graph's ``resolve`` / ``compose`` nodes.
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
class ExecutionStep:
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


class StepProjector(Protocol):
    def project(
        self,
        intent: EntryIntent,
        context: str,
        conversation_messages: list[ConversationMessage] | None = None,
        routing_key: str = "",
    ) -> list[ExecutionStep]:
        ...


class WorkflowStepProjector:
    """Deterministic workflow selector and step projector.

    Selects the registered :class:`WorkflowSpec` for an intent. Only specs with
    step projection policy are projected into executable ``ExecutionStep``
    objects. There is no LLM call in this path.
    """

    def __init__(
        self,
        settings: Settings,
        tool_executor: ToolExecutor | None = None,
        workflow_definition_store: object | None = None,
    ) -> None:
        self._settings = settings
        self._tool_executor = tool_executor
        self._workflow_definition_store = workflow_definition_store

    def project(
        self,
        intent: EntryIntent,
        context: str = "",
        conversation_messages: list[ConversationMessage] | None = None,
        routing_key: str = "",
    ) -> list[ExecutionStep]:
        # ``context`` / ``conversation_messages`` no longer shape the topology;
        # they remain in the signature so callers can pass the same entry context
        # shape. Per-request semantics are resolved at execution time.
        from .workflow import WORKFLOW_REGISTRY

        spec = WORKFLOW_REGISTRY.select(intent)
        if self._workflow_definition_store is not None:
            selected = self._workflow_definition_store.select_active_spec(
                intent,
                registry=WORKFLOW_REGISTRY,
                routing_key=routing_key,
            )
            if selected is not None:
                spec = selected
            else:
                logger.warning("workflow deployment disabled intent=%s", intent)
                return []
        steps = spec.project()
        logger.info(
            "step_projector selected workflow intent=%s workflow=%s version=%s requires_projection=%s steps=%d",
            intent, spec.workflow_id, spec.version, spec.requires_projection, len(steps),
        )
        return steps

    def fallback_projection(
        self,
        intent: EntryIntent,
        *,
        routing_key: str = "",
    ) -> list[ExecutionStep]:
        """Return the deterministic step projection for ``intent``.

        Kept as a distinct method for validator fallback call sites. Ordinary
        branch workflows return an empty list here by design.
        """
        from .workflow import WORKFLOW_REGISTRY

        spec = WORKFLOW_REGISTRY.select(intent)
        if self._workflow_definition_store is not None:
            selected = self._workflow_definition_store.select_active_spec(
                intent,
                registry=WORKFLOW_REGISTRY,
                routing_key=routing_key,
            )
            if selected is not None:
                spec = selected
        return spec.project()

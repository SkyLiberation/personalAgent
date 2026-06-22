"""Narrow capability contexts injected into LangGraph node groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    from ..core.config import Settings
    from ..core.models import EntryInput
    from ..graphiti.store import GraphitiStore
    from ..memory import MemoryFacade
    from ..policy import PolicyEngine
    from ..tools import ToolExecutor
    from .ask import AskRunContextStore
    from .replanner import Replanner
    from .router import IntentRouter
    from .runtime_ask import AskService
    from .runtime_results import AskResult
    from .step_projection_validator import StepProjectionValidator
    from .verifier import AnswerVerifier
    from .workflow_planner import WorkflowPlanner


class ToolingContext(Protocol):
    tool_executor: "ToolExecutor"


@dataclass(frozen=True, slots=True)
class RoutingContext:
    settings: "Settings"
    memory: "MemoryFacade"
    intent_router: "IntentRouter"
    compress_context: Callable[[str, str], str]


@dataclass(frozen=True, slots=True)
class PlanningContext:
    workflow_planner: "WorkflowPlanner"
    step_projection_validator: "StepProjectionValidator"


@dataclass(frozen=True, slots=True)
class DirectAnswerContext:
    settings: "Settings"
    compress_context: Callable[[str, str], str]


@dataclass(frozen=True, slots=True)
class SummaryContext:
    summarize_chat: Callable[[str, str], str]
    load_thread_messages: Callable[["EntryInput", int], list[dict[str, str]]]


@dataclass(frozen=True, slots=True)
class StepExecutionContext:
    settings: "Settings"
    memory: "MemoryFacade"
    replanner: "Replanner | None"
    verifier: "AnswerVerifier | None"
    step_projection_validator: "StepProjectionValidator"
    tool_executor: "ToolExecutor"
    graph_store: "GraphitiStore"
    execute_ask: Callable[..., "AskResult"]
    ask_service_factory: Callable[[], "AskService"]
    ask_run_context_store: "AskRunContextStore"
    workflow_artifact_store: object
    summary: SummaryContext
    direct_answer: DirectAnswerContext


@dataclass(frozen=True, slots=True)
class ReactContext:
    settings: "Settings"
    tool_executor: "ToolExecutor"
    policy_engine: "PolicyEngine"


@dataclass(frozen=True, slots=True)
class GraphContexts:
    """Graph assembly input; nodes receive only one narrow child context."""

    routing: RoutingContext
    planning: PlanningContext
    direct_answer: DirectAnswerContext
    steps: StepExecutionContext
    react: ReactContext

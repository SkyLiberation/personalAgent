"""Narrow capability contexts injected into LangGraph node groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    from personal_agent.kernel.config import Settings
    from personal_agent.kernel.models import EntryInput
    from personal_agent.graphiti.store import GraphitiStore
    from personal_agent.memory import MemoryFacade
    from personal_agent.policy import PolicyEngine
    from personal_agent.tools import ToolExecutor
    from personal_agent.agent.ask import AskRunContextStore
    from personal_agent.agent.replanner import Replanner
    from personal_agent.agent.router import IntentRouter
    from personal_agent.agent.runtime_ask import AskService
    from personal_agent.agent.runtime_results import AskResult
    from personal_agent.agent.step_projection_validator import StepProjectionValidator
    from personal_agent.agent.verifier import AnswerVerifier
    from personal_agent.agent.workflow_planner import WorkflowPlanner


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

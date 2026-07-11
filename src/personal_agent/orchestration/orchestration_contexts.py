"""Narrow capability contexts injected into LangGraph node groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    from personal_agent.kernel.config import Settings
    from personal_agent.kernel.models import EntryInput
    from personal_agent.memory.graphiti.store import GraphitiStore
    from personal_agent.memory import MemoryFacade
    from personal_agent.governance.policy import PolicyEngine
    from personal_agent.governance import ToolExecutor
    from personal_agent.infra.structured_model import StructuredModelClient
    from personal_agent.orchestration.ask import AskRunContextStore
    from personal_agent.planning.router import IntentRouter
    from personal_agent.orchestration.runtime_ask import AskService
    from personal_agent.application.runtime_results import AskResult
    from personal_agent.planning.step_projection_validator import StepProjectionValidator
    from personal_agent.application.verifier import AnswerVerifier
    from personal_agent.planning.protocols import ProtocolRegistry
    from personal_agent.planning.goal_interpreter import GoalInterpreter
    from personal_agent.planning.executive import ExecutiveController
    from personal_agent.planning.decision_validator import DecisionValidator
    from personal_agent.planning.ledger import ExecutionLedgerProjector, LedgerPatchValidator
    from personal_agent.planning.verification import CompletionVerifier, GoalVerifier
    from personal_agent.application.workspace import WorkspaceService
    from personal_agent.agents.gateway import AgentGateway


class ToolingContext(Protocol):
    tool_executor: "ToolExecutor"


@dataclass(frozen=True, slots=True)
class RoutingContext:
    settings: "Settings"
    memory: "MemoryFacade"
    intent_router: "IntentRouter"
    compress_context: Callable[[str, str], str]


@dataclass(frozen=True, slots=True)
class ExecutiveContext:
    settings: "Settings"
    goal_interpreter: "GoalInterpreter"
    controller: "ExecutiveController"
    decision_validator: "DecisionValidator"
    ledger_projector: "ExecutionLedgerProjector"
    ledger_patch_validator: "LedgerPatchValidator"
    goal_verifier: "GoalVerifier"
    completion_verifier: "CompletionVerifier"
    protocol_registry: "ProtocolRegistry"
    step_projection_validator: "StepProjectionValidator"
    tool_executor: "ToolExecutor"
    policy_engine: "PolicyEngine"
    agent_gateway: "AgentGateway"


@dataclass(frozen=True, slots=True)
class DirectAnswerContext:
    settings: "Settings"
    compress_context: Callable[[str, str], str]
    model_client: "StructuredModelClient | None" = None


@dataclass(frozen=True, slots=True)
class SummaryContext:
    summarize_chat: Callable[[str, str], str]
    load_thread_messages: Callable[["EntryInput", int], list[dict[str, str]]]


@dataclass(frozen=True, slots=True)
class StepExecutionContext:
    settings: "Settings"
    memory: "MemoryFacade"
    verifier: "AnswerVerifier | None"
    step_projection_validator: "StepProjectionValidator"
    tool_executor: "ToolExecutor"
    policy_engine: "PolicyEngine"
    agent_gateway: "AgentGateway"
    graph_store: "GraphitiStore"
    execute_ask: Callable[..., "AskResult"]
    ask_service_factory: Callable[[], "AskService"]
    ask_run_context_store: "AskRunContextStore"
    workflow_artifact_store: object
    workspace_service: "WorkspaceService"
    summary: SummaryContext
    direct_answer: DirectAnswerContext
    model_client: "StructuredModelClient | None" = None
    structured_client: "StructuredModelClient | None" = None


@dataclass(frozen=True, slots=True)
class ReactContext:
    settings: "Settings"
    tool_executor: "ToolExecutor"
    policy_engine: "PolicyEngine"
    model_client: "StructuredModelClient | None" = None
    structured_client: "StructuredModelClient | None" = None


@dataclass(frozen=True, slots=True)
class GraphContexts:
    """Graph assembly input; nodes receive only one narrow child context."""

    routing: RoutingContext
    executive: ExecutiveContext
    direct_answer: DirectAnswerContext
    steps: StepExecutionContext
    react: ReactContext

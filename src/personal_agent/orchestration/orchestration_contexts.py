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
    from personal_agent.planning.task_analyzer import TaskAnalyzer
    from personal_agent.orchestration.runtime_ask import AskService
    from personal_agent.application.runtime_results import AskResult
    from personal_agent.planning.step_projection_validator import StepProjectionValidator
    from personal_agent.application.verifier import AnswerVerifier
    from personal_agent.planning.procedures import (
        ProcedureApplicabilityResolver,
        ProcedureRuntime,
    )
    from personal_agent.planning.goal_graph import GoalGraphCompiler
    from personal_agent.planning.executive import ExecutiveController
    from personal_agent.planning.decision_validator import DecisionValidator
    from personal_agent.planning.ledger import ExecutionLedgerProjector, GoalDecompositionValidator
    from personal_agent.planning.verification import CompletionVerifier, GoalVerifier
    from personal_agent.application.workspace import WorkspaceService
    from personal_agent.agents.gateway import AgentGateway
    from personal_agent.agents.runtime import SubagentRuntime
    from personal_agent.context import ContextManager, ModelContextGateway
    from personal_agent.planning.recovery import ObservationNormalizer, TechnicalRecoveryPolicy
    from personal_agent.planning.outcome_ranking import OutcomeAwareCapabilityRanker
    from personal_agent.planning.adaptive import (
        AdaptivePlanner,
        FrontierSelector,
        PlanLedgerProjector,
        PlanMonitor,
        PlanValidator,
        PlanningFactProjector,
        PlanningModePolicy,
    )
    from personal_agent.kernel.contracts.planning import PlannerExecutionProfile
    from personal_agent.runtime import ResolvedActionBuilder, ResourceAccessResolver, RunScheduler


class ToolingContext(Protocol):
    tool_executor: "ToolExecutor"


@dataclass(frozen=True, slots=True)
class RoutingContext:
    settings: "Settings"
    memory: "MemoryFacade"
    task_analyzer: "TaskAnalyzer"
    compress_context: Callable[[str, str], str]


@dataclass(frozen=True, slots=True)
class ExecutiveContext:
    settings: "Settings"
    goal_graph_compiler: "GoalGraphCompiler"
    controller: "ExecutiveController"
    decision_validator: "DecisionValidator"
    ledger_projector: "ExecutionLedgerProjector"
    goal_decomposition_validator: "GoalDecompositionValidator"
    goal_verifier: "GoalVerifier"
    completion_verifier: "CompletionVerifier"
    procedure_applicability_resolver: "ProcedureApplicabilityResolver"
    procedure_runtime: "ProcedureRuntime"
    step_projection_validator: "StepProjectionValidator"
    tool_executor: "ToolExecutor"
    policy_engine: "PolicyEngine"
    agent_gateway: "AgentGateway"
    context_manager: "ContextManager"
    context_gateway: "ModelContextGateway"
    observation_normalizer: "ObservationNormalizer"
    recovery_policy: "TechnicalRecoveryPolicy"
    resource_access_resolver: "ResourceAccessResolver"
    action_builder: "ResolvedActionBuilder"
    scheduler: "RunScheduler"
    subagent_runtime: "SubagentRuntime"
    capability_ranker: "OutcomeAwareCapabilityRanker"
    planning_fact_projector: "PlanningFactProjector"
    planning_mode_policy: "PlanningModePolicy"
    adaptive_planner: "AdaptivePlanner"
    plan_validator: "PlanValidator"
    plan_ledger_projector: "PlanLedgerProjector"
    frontier_selector: "FrontierSelector"
    plan_monitor: "PlanMonitor"
    planner_profile: "PlannerExecutionProfile"


@dataclass(frozen=True, slots=True)
class ConversationContext:
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
    verifier: "AnswerVerifier | None"
    step_projection_validator: "StepProjectionValidator"
    tool_executor: "ToolExecutor"
    policy_engine: "PolicyEngine"
    agent_gateway: "AgentGateway"
    graph_store: "GraphitiStore"
    execute_ask: Callable[..., "AskResult"]
    ask_service_factory: Callable[[], "AskService"]
    ask_run_context_store: "AskRunContextStore"
    execution_artifact_store: object
    workspace_service: "WorkspaceService"
    summary: SummaryContext
    conversation: ConversationContext
    model_client: "StructuredModelClient | None" = None
    structured_client: "StructuredModelClient | None" = None


@dataclass(frozen=True, slots=True)
class ReactContext:
    settings: "Settings"
    tool_executor: "ToolExecutor"
    policy_engine: "PolicyEngine"
    context_manager: "ContextManager"
    context_gateway: "ModelContextGateway"
    model_client: "StructuredModelClient | None" = None
    structured_client: "StructuredModelClient | None" = None


@dataclass(frozen=True, slots=True)
class GraphContexts:
    """Graph assembly input; nodes receive only one narrow child context."""

    routing: RoutingContext
    executive: ExecutiveContext
    steps: StepExecutionContext
    react: ReactContext

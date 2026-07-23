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
    from personal_agent.capabilities.contracts.model import StructuredModelClient
    from personal_agent.orchestration.ask import AskRunContextStore
    from personal_agent.planning.task_analyzer import TaskAnalyzer
    from personal_agent.orchestration.runtime_ask import AskService
    from personal_agent.application.runtime_results import AskResult
    from personal_agent.planning.step_projection_validator import StepProjectionValidator
    from personal_agent.application.verifier import AnswerVerifier
    from personal_agent.runtime.procedure_runtime import (
        ProcedureApplicabilityResolver,
        ProcedureRuntime,
    )
    from personal_agent.planning.task_compiler import GoalGraphCompiler
    from personal_agent.runtime.control_runtime import ExecutiveController
    from personal_agent.governance.decision_admission import (
        AcceptedIntentCompiler,
        DecisionValidator,
        ExecutionCommandResolver,
    )
    from personal_agent.governance.route_admission import ExecutionRoutePolicy
    from personal_agent.runtime.task_runtime import TaskRuntimeProjector, GoalDecompositionValidator
    from personal_agent.verification.runtime import CompletionVerifier, ExecutionFactVerifier, GoalVerifier
    from personal_agent.application.workspace import WorkspaceService
    from personal_agent.agents.gateway import AgentGateway
    from personal_agent.agents.runtime import SubagentRuntime
    from personal_agent.context import ContextManager, ModelContextGateway
    from personal_agent.runtime.recovery import ObservationNormalizer, TechnicalRecoveryPolicy
    from personal_agent.capabilities.outcomes import OutcomeAwareCapabilityRanker
    from personal_agent.runtime.capability_grants import CapabilityGrantIssuer
    from personal_agent.runtime.procedure_grants import ProcedureGrantIssuer
    from personal_agent.capabilities.acquisition import CapabilityAcquisitionManager
    from personal_agent.governance.evidence_admission import EvidenceAdmission
    from personal_agent.planning.adaptive import (
        AdaptivePlanner,
        FrontierSelector,
        PlanRuntimeProjector,
        PlanMonitor,
        PlanValidator,
        PlanningFactProjector,
        CoordinationModePolicy,
    )
    from personal_agent.runtime.contracts.planning import PlannerExecutionProfile
    from personal_agent.runtime import ResolvedActionBuilder, ResourceAccessResolver, RunScheduler
    from personal_agent.execution.invocation_journal import InvocationJournal
    from personal_agent.runtime.commits import ControlCommitter, TaskCompilationCommitter
    from personal_agent.infra.storage.postgres_control_plane_store import PostgresControlPlaneStore


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
    decision_admission: "DecisionValidator"
    accepted_intent_compiler: "AcceptedIntentCompiler"
    execution_command_resolver: "ExecutionCommandResolver"
    route_policy: "ExecutionRoutePolicy"
    task_runtime_projector: "TaskRuntimeProjector"
    goal_decomposition_validator: "GoalDecompositionValidator"
    goal_verifier: "GoalVerifier"
    execution_fact_verifier: "ExecutionFactVerifier"
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
    capability_grant_issuer: "CapabilityGrantIssuer"
    procedure_grant_issuer: "ProcedureGrantIssuer"
    capability_acquisition_manager: "CapabilityAcquisitionManager"
    evidence_admission: "EvidenceAdmission"
    planning_fact_projector: "PlanningFactProjector"
    coordination_policy: "CoordinationModePolicy"
    adaptive_planner: "AdaptivePlanner"
    plan_validator: "PlanValidator"
    plan_runtime_projector: "PlanRuntimeProjector"
    frontier_selector: "FrontierSelector"
    plan_monitor: "PlanMonitor"
    planner_profile: "PlannerExecutionProfile"
    task_compilation_committer: "TaskCompilationCommitter"
    control_committer: "ControlCommitter"
    control_plane_store: "PostgresControlPlaneStore"
    # Test/chaos-only hook at the durable node boundary immediately after the
    # atomic TaskContract + initial Runtime + TaskCompilationCommit checkpoint.
    # It cannot modify the compiled contracts and is never model-visible.
    post_task_compilation_commit_hook: Callable[[str], None] | None = None


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
    control_plane_store: "PostgresControlPlaneStore"
    invocation_journal: "InvocationJournal"
    procedure_grant_issuer: "ProcedureGrantIssuer"
    workspace_service: "WorkspaceService"
    summary: SummaryContext
    conversation: ConversationContext
    context_manager: "ContextManager"
    context_gateway: "ModelContextGateway"
    model_client: "StructuredModelClient | None" = None
    structured_client: "StructuredModelClient | None" = None
    # Test/chaos-only hook for the durable boundary after a real Gateway call
    # and before its result is consumed. It is never model-visible and cannot
    # change an invocation, grant, command, or journal entry.
    post_gateway_dispatch_hook: Callable[[str], None] | None = None


@dataclass(frozen=True, slots=True)
class ReactContext:
    settings: "Settings"
    tool_executor: "ToolExecutor"
    policy_engine: "PolicyEngine"
    context_manager: "ContextManager"
    context_gateway: "ModelContextGateway"
    invocation_journal: "InvocationJournal"
    model_client: "StructuredModelClient | None" = None
    structured_client: "StructuredModelClient | None" = None


@dataclass(frozen=True, slots=True)
class GraphContexts:
    """Graph assembly input; nodes receive only one narrow child context."""

    routing: RoutingContext
    executive: ExecutiveContext
    steps: StepExecutionContext
    react: ReactContext

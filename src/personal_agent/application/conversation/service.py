from __future__ import annotations

from personal_agent.capabilities.contracts.verification import ConversationAnswerSegment
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from collections.abc import Callable
import logging
from time import monotonic, sleep
from typing import Any

from pydantic import BaseModel, ValidationError

from personal_agent.application.capture.web_source import WEB_SOURCE_FORMAT, WebReadOutput, WebSearchOutput

from personal_agent.capabilities.contracts.grants import (
    DelegationGrant,
    GrantDependencySet,
)
from personal_agent.capabilities.contracts.model import (
    ModelInvocationUnavailable,
    ModelCapacityRefused,
    ModelRuntimeFeedback,
    ModelToolExchange,
    ModelUserHistoryMessage,
    StructuredOutputFailure,
    StructuredModelResponse,
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.capabilities.contracts.verification import GoalClarificationReview, GoalTaskReview, VerificationVerdict
from personal_agent.kernel.contracts.agent import AgentGatewayContext, AgentTask
from personal_agent.kernel.contracts.derivation import canonical_digest
from personal_agent.application.artifacts.models import (
    ArtifactWriteReceipt, resolve_artifact_file,
)
from personal_agent.application.retrieval_experiment.models import (
    ExperimentToolArgs, PublishedExperimentResult, RetrievalDeployment,
)
from personal_agent.application.bash_execution.models import (
    BashArgs, BashExecutionAuthorization, BashInputScope, BashToolResult,
)
from personal_agent.application.retrieval_experiment.delivery import DeliveryIncomplete
from .research_delivery import (
    ResearchExperimentCompletionUseCase, experiment_submission, pending_experiment_submission,
)
from .tool_requests import WriteArtifactArgs
from personal_agent.application.artifacts.text_coordinates import TextCoordinates
from .artifact_sources import input_resource_refs, trace_goal_draft_refs, trace_resource_refs
from .analysis_tasks import GoalTaskCandidate, select_goal_task, task_message_indices, task_switch_turn
from .history_compaction import (
    HistoryCompactor, checkpoint_refs, history_input_pressure, history_pressure_limit,
    recorded_checkpoint_refs,
)
from .model_history import (
    goal_pending_rejection, omit_replayed_delivered_answers, prior_analysis_turns, project_conversation_history,
    selected_analysis_turns, update_decisions,
)
from personal_agent.kernel.contracts.resource import OperationScope, ResourceRef, ResourceSelector
from personal_agent.kernel.contracts.scope import (
    ExecutionScope,
    AuthenticatedPrincipal,
)
from personal_agent.kernel.contracts.tool import ConversationToolProfile
from personal_agent.kernel.observability import PolicyDecisionRecorder
from personal_agent.kernel.contracts.policy import PolicyDecisionEvent
from personal_agent.kernel.logging_utils import log_event

from .observation_bounds import (
    MAX_TOOL_OBSERVATION_BYTES,
    fit_observation_preview,
    select_offload_text,
    serialized_length,
    serialized_utf8_size,
)
from .context_materialization import (
    select_visible_successful_observations,
    READ_FILE_CAPABILITY,
    GREP_FILE_CAPABILITY,
    FILE_READ_CAPABILITIES,
    materialize_interaction_inputs,
)
from .file_search import ArtifactSearchPort, GrepFileArguments, grep_file_text
from .file_reading import ReadFileArguments, read_file_text
from .interaction_projection import project_interaction_inputs, render_interaction_input
from .interaction_prompt import build_interaction_system_prompt
from .budget import ConversationBudget, deadline_elapsed
from .bash_authorization import require_bash_authorization
from .answer_results import DirectAnswerResult
from .tool_groups import conversation_tool_group
from .skills import LOAD_SKILL_CAPABILITY, InstalledSkill, LoadedSkill, PublishedSkillScripts, SkillCatalog, render_skill_summaries
from personal_agent.kernel.contracts.answer_result import AnswerProtocolVersion, AnswerResultConfig
from personal_agent.kernel.contracts.goal import ConversationGoalMode

from .goal_compliance import (
    ACTION_GOAL_PROMPT, PendingBashReview, action_goal_request, answer_goal_context, bind_action_goal_assessment,
)
from .verification_context import build_verification_context, current_question_inputs, verification_checkpoint, goal_submission_id
from .history_models import HistoryCompactionCheckpoint, HistoryItemKey, HistoryToolPruningBoundary
from .history_tool_pruning import active_tool_pruning, propose_tool_pruning
from personal_agent.capabilities.contracts.verification_prompt import (
    GOAL_COMPLIANCE_OPERATION, verification_input_size, task_verification_criteria,
)
from .model_actions import (
    PartiallyDecodedToolBatch,
    build_model_action_definitions,
    partially_decode_tool_batch,
    project_test_mode_tools,
    provider_action_feedback,
    decode_model_action_invocations,
    model_visible_capability_policy,
)
from .goal_models import (
    AddGoalItem, SUBMIT_GOAL_PATCH, GoalOperationRecord, GoalMaintenanceInvocation,
)
from .goal_maintenance import (
    current_analysis_goal,
    admit_goal_maintenance, goal_feedback, goal_input_digest,
)
from .goal_module import GoalModule
from .errors import (
    ConversationFailureStage,
    ConversationInputError,
    ConversationOperationConflict,
    ConversationOperationNotFound,
    ConversationFailure,
    ConversationTurnPending,
    ConversationTurnBlocked,
    ConversationSteeringPending,
    ConversationWriterBusy,
)
from .workspace_changes import (
    WORKSPACE_CHANGES, Decision as WorkspaceDecision, WorkspaceChangeArguments, WorkspaceChangeConfirmation,
    WorkspaceChangeOperation, WorkspaceChangeReceipt, WorkspaceChangeService,
)
from .journal import (
    InMemoryInteractionJournal,
)
from .knowledge_save import ConversationKnowledgeSaveUseCase
from .models import (
    TurnSteeringRequest,
    OFFLOADED_OUTPUT_REFETCH,
    ModelCallDisposition,
    ActionObservation,
    ArtifactSourceInput,
    AcceptedArtifactToolRequest,
    AcceptedExperimentToolRequest,
    AcceptedBashToolRequest,
    AgentDelegationProposal,
    ClarificationInvocation,
    CommittedUsage,
    ContinueTurnProposal,
    ConversationInteractionMode,
    ConversationKnowledgeSaveOperation,
    ConversationMessage,
    ConversationTurnView,
    ConversationWorkingPlan,
    DecisionFeedback,
    EffectiveAgentCapability,
    EffectiveCapabilities,
    EffectiveToolCapability,
    FinalMessage,
    AnswerResultInvocation,
    SubmittedFinal,
    InteractionTrace,
    InteractionInput,
    KnowledgeDeleteConfirmation,
    KnowledgeSaveArguments,
    ListPersonalKnowledgeArguments,
    LoopBudgetPolicy,
    MCPWriteDispatch,
    PrepareKnowledgeDeleteArguments,
    SessionId,
    SearchPersonalKnowledgeArguments,
    ToolCallProposal,
    TurnContextComposition,
)
from .ports import (
    ConversationKnowledgeLifecyclePort,
    ConversationKnowledgeWriter,
    ConversationKnowledgeReadPort,
    InteractionAgentPort,
    InteractionArtifactPort,
    InteractionToolPort,
)
from .verification_admission import observed_receipts, INTERACTION_VERIFICATION_CAPABILITY as _VERIFICATION_CAPABILITY
from .working_plan import (
    active_working_plan_step_id,
    admit_continue_turn_progress,
    admit_plan_review,
    admit_plan_wait_boundary,
    admit_working_plan,
    complete_working_plan,
    render_working_plan_recovery,
    required_plan_review_feedback,
    supersede_pending_working_plan,
)


_KNOWLEDGE_SAVE_CAPABILITY = "prepare_conversation_knowledge_save"

_LIST_PERSONAL_KNOWLEDGE_CAPABILITY = "list_personal_knowledge"
_SEARCH_PERSONAL_KNOWLEDGE_CAPABILITY = "search_personal_knowledge"
_PREPARE_KNOWLEDGE_DELETE_CAPABILITY = "prepare_knowledge_delete"
_LOGGER = logging.getLogger(__name__)
_RAW_NOTE_READ_CAPABILITIES = frozenset(
    {
        "find_similar_notes",
        "get_note",
        "list_recent_notes",
    }
)


@dataclass(frozen=True, slots=True)
class _ActionResult:
    action_id: str
    interaction_input: ActionObservation | DecisionFeedback


def submitted_turn_id(
    principal: AuthenticatedPrincipal, session_id: str, client_request_id: str,
) -> str:
    identity = json.dumps(
        [principal.tenant_id, principal.user_id, session_id, client_request_id], separators=(",", ":"),
    )
    return f"turn_{sha256(identity.encode('utf-8')).hexdigest()[:24]}"


class ConversationService:
    """Canonical non-durable ReAct loop for an ordinary user interaction."""

    def __init__(
        self,
        model_client: StructuredModelClient | None,
        *,
        tool_port: InteractionToolPort | None = None,
        agent_port: InteractionAgentPort | None = None,
        artifact_port: InteractionArtifactPort | None = None,
        artifact_search: ArtifactSearchPort | None = None,
        knowledge_writer: ConversationKnowledgeWriter | None = None,
        knowledge_reader: ConversationKnowledgeReadPort | None = None,
        knowledge_lifecycle: ConversationKnowledgeLifecyclePort | None = None,
        workspace_changes: WorkspaceChangeService | None = None,
        budget: ConversationBudget | None = None,
        journal: InMemoryInteractionJournal | None = None,
        action_diagnostics_reveal_field_names: bool = False,
        policy_decisions: PolicyDecisionRecorder | None = None,
        experiment_deployment: RetrievalDeployment | None = None,
        experiment_model_capacity_valid: bool = False,
        verification_input_budget: int | None = None,
        experiment_completion: ResearchExperimentCompletionUseCase | None = None,
        bash_authorization: BashExecutionAuthorization | None = None,
        answer_result: DirectAnswerResult | None = None,
        tool_profile: ConversationToolProfile = ConversationToolProfile(),
        skill_catalog: SkillCatalog | None = None,
        skill_scripts: Callable[[InstalledSkill, ExecutionScope], PublishedSkillScripts | None] | None = None,
        goal_module: GoalModule | None = GoalModule(),
        prompts: PromptCatalog = DEFAULT_PROMPTS,
    ) -> None:
        self._model_client = model_client
        self._prompts = prompts
        self._policy_decisions = policy_decisions or PolicyDecisionRecorder()
        self._tool_port = tool_port
        self._tool_profile = tool_profile
        self._skill_catalog = skill_catalog
        self._skill_scripts = skill_scripts
        self._agent_port = agent_port
        self._artifact_port = artifact_port
        self._artifact_search = artifact_search
        self._experiment_deployment = experiment_deployment
        self._verification_input_budget = verification_input_budget
        self._experiment_model_capacity_valid = experiment_model_capacity_valid
        self._experiment_completion = experiment_completion
        self._bash_authorization = bash_authorization
        self._answer_result = (
            replace(answer_result, prompts=prompts) if answer_result is not None
            else DirectAnswerResult(AnswerResultConfig(), prompts=prompts)
        )
        self._goals = goal_module
        self._goal_mode = ConversationGoalMode.ENABLED if goal_module is not None else ConversationGoalMode.DISABLED
        if goal_module is None and self._answer_result.verification_enabled:
            raise ValueError("Answer verification requires the Conversation Goal module")
        self._knowledge_writer = knowledge_writer
        self._knowledge_reader = knowledge_reader
        self._knowledge_lifecycle = knowledge_lifecycle
        self._workspace_changes = workspace_changes
        self._action_diagnostics_reveal_field_names = (
            action_diagnostics_reveal_field_names
        )
        if agent_port is not None and artifact_port is None:
            raise ValueError(
                "agent delegation requires the canonical Artifact read port"
            )
        self._journal = journal or InMemoryInteractionJournal()
        if budget is not None and (budget.journal is not self._journal
                                   or budget.bash_authorization != bash_authorization):
            raise ValueError("预算治理必须使用本对话的 Journal 和 Bash 授权")
        self._budget = budget or ConversationBudget(LoopBudgetPolicy(), self._journal, bash_authorization)
        self._history = HistoryCompactor(
            journal=self._journal, artifacts=self._artifact_port,
            generate=lambda request, run_ref: self._generate_model(request, run_ref=run_ref, usage=self._journal.get(run_ref).usage),
            record_usage=self._record_model_usage,
            goal_module=goal_module,
            prompts=prompts,
        ) if self._artifact_port is not None and self._model_client is not None else None
        self._knowledge_save = ConversationKnowledgeSaveUseCase(
            writer=self._knowledge_writer,
            journal=self._journal,
            prompts=self._prompts,
        )

    def respond(
        self,
        *,
        conversation_id: SessionId,
        principal: AuthenticatedPrincipal,
        source_platform: str = "web",
        message: ConversationMessage | None = None,
        interaction_run_ref: str | None = None,
        client_request_id: str | None = None,
        create_session: bool | None = False,
        interaction_mode: ConversationInteractionMode = "default",
        input_artifact_refs: tuple[ResourceRef, ...] = (),
        on_registered: Callable[[str], None] | None = None,
        on_turn_stopping: Callable[[], None] | None = None,
    ) -> ConversationTurnView:
        if not conversation_id:
            raise ConversationInputError("conversation_id must not be empty")
        if message is not None:
            if message.role != "user" or not client_request_id or interaction_run_ref is not None:
                raise ConversationInputError("提交新轮次需要一条用户消息和请求标识")
            if create_session is None and source_platform != "feishu":
                raise ConversationInputError("此入口需明确创建或续接会话")
            run_ref = submitted_turn_id(principal, conversation_id, client_request_id)
            prior = self._journal.get(run_ref)
            if prior is not None:
                return self._submitted_turn_view(
                    prior, conversation_id, message, principal, source_platform, input_artifact_refs,
                    create_session, on_registered,
                )
        elif interaction_run_ref is not None:
            run_ref = interaction_run_ref
        else:
            raise ConversationInputError("恢复需要原轮次标识")
        try:
            with (self._journal.exclusive_session(principal=principal, session_id=conversation_id),
                  self._journal.exclusive_run(run_ref)):
                prior = self._journal.get(run_ref)
                if message is None:
                    if prior is None:
                        raise ConversationOperationNotFound("interaction turn not found")
                    messages, input_artifact_refs = list(prior.messages), prior.input_artifact_refs
                elif prior is not None:
                    return self._submitted_turn_view(
                        prior, conversation_id, message, principal, source_platform, input_artifact_refs,
                        create_session, on_registered,
                    )
                else:
                    messages = self._next_turn_messages(conversation_id, principal, message, create_session)
                try:
                    turn = self._respond_locked(
                        conversation_id=conversation_id,
                        messages=messages,
                        principal=principal,
                        source_platform=source_platform,
                        interaction_run_ref=run_ref,
                        input_artifact_refs=input_artifact_refs,
                        on_registered=on_registered,
                        on_turn_stopping=on_turn_stopping,
                    )
                except ConversationFailure as error:
                    trace = self._journal.get(run_ref)
                    research_bound = trace is not None and trace.bash_profile_digest is not None
                    if error.failure_stage in {"model_capacity", "application_budget"} or research_bound:
                        if trace is not None and trace.principal == principal:
                            usage = trace.usage
                            for response in error.prior_responses:
                                usage = self._record_model_usage(usage, response)
                            if error.response is not None:
                                usage = self._record_model_usage(
                                    usage,
                                    error.response,
                                    model_turn=error.operation == "agent_interaction_turn", run_ref=run_ref,
                                )
                            if (research_bound and error.failure_stage == "provider_request"
                                    and not error.provider_response_complete):
                                usage = usage.model_copy(update={
                                    "provider_usage_complete": False, "model_calls": None,
                                    "input_tokens": None, "output_tokens": None,
                                })
                            if usage != trace.usage:
                                self._journal.update(
                                    ExecutionScope(
                                        principal=principal,
                                        execution_id=run_ref,
                                        thread_id=conversation_id,
                                    ),
                                    lambda latest: latest.model_copy(
                                        update={
                                            "revision": latest.revision + 1,
                                            "usage": usage,
                                        }
                                    ),
                                )
                            if error.failure_stage == "application_budget":
                                return self._fail_closed_limitation(
                                    conversation_id, run_ref, principal, messages, list(trace.inputs), usage,
                                    list(trace.execution_order), list(trace.concurrent_batches), list(trace.context_composition),
                                    working_plan=trace.working_plan,
                                    message=str(error),
                                )
                    raise
                return turn
        except ConversationWriterBusy as exc:
            if message is None:
                raise
            prior = self._journal.get(run_ref)
            if prior is None:
                tail = self._journal.last_turn(principal=principal, session_id=conversation_id)
                if tail is not None:
                    raise ConversationTurnBlocked(tail.interaction_run_ref) from exc
                raise
            return self._submitted_turn_view(
                prior, conversation_id, message, principal, source_platform, input_artifact_refs,
                create_session, on_registered,
            )

    def steer_turn(self, run_ref: str, *, principal: AuthenticatedPrincipal,
                   request: TurnSteeringRequest) -> InteractionTrace:
        trace = self.trace(run_ref, principal=principal)
        if trace is None:
            raise ConversationOperationNotFound("interaction turn not found")
        try:
            with self._journal.exclusive_run(run_ref):
                active = False
        except ConversationWriterBusy:
            active = True
        self._journal.submit_steering(ExecutionScope(
            principal=principal, execution_id=run_ref, thread_id=trace.conversation_id,
        ), request, active=active)
        return trace

    def _next_turn_messages(
        self, conversation_id: SessionId, principal: AuthenticatedPrincipal,
        message: ConversationMessage, create_session: bool | None,
    ) -> list[ConversationMessage]:
        tail = self._journal.last_turn(principal=principal, session_id=conversation_id)
        if tail is None:
            if create_session is False:
                raise ConversationOperationNotFound("会话不存在")
            return [message]
        if create_session:
            raise ConversationOperationConflict("会话已存在")
        view = self._recorded_turn_view(tail, self._turn_working_plan(tail))
        unresolved_workspace = any(
            item.receipt is None or item.receipt.status == "unknown" for item in tail.workspace_changes
        )
        unresolved_bash = any(
            isinstance(item, AcceptedBashToolRequest) and item.command is not None
            and (item.receipt is None or item.receipt.status == "unknown")
            for item in tail.accepted_tool_requests
        )
        unresolved_experiment = any(
            item.command is not None and (item.receipt is None or item.receipt.status == "unknown")
            for item in tail.experiment_records
        )
        if (view is None or view.disposition == "confirmation_required" or view.pending_confirmation is not None
                or unresolved_workspace or unresolved_bash or unresolved_experiment):
            raise ConversationTurnBlocked(tail.interaction_run_ref)
        return [*tail.messages, view.message, message]

    def _submitted_turn_view(
        self,
        prior: InteractionTrace,
        conversation_id: SessionId,
        message: ConversationMessage,
        principal: AuthenticatedPrincipal,
        source_platform: str,
        input_artifact_refs: tuple[ResourceRef, ...],
        create_session: bool | None,
        on_registered: Callable[[str], None] | None,
    ) -> ConversationTurnView:
        self._validate_turn_input(
            prior, conversation_id, list(prior.messages), principal, source_platform, input_artifact_refs,
        )
        if (prior.messages[-1] != message
                or (create_session is not None and create_session != (len(prior.messages) == 1))):
            raise ConversationOperationConflict("请求标识已绑定不同的用户输入")
        if on_registered is not None:
            on_registered(prior.interaction_run_ref)
        view = self._recorded_turn_view(prior, self._turn_working_plan(prior))
        if view is None:
            raise ConversationTurnPending()
        return view

    def _require_goal_mode(self, trace: InteractionTrace) -> None:
        if trace.goal_mode != self._goal_mode:
            raise ConversationOperationConflict("Goal mode changed. Restore using the original configuration.")

    def _validate_turn_input(
        self,
        prior: InteractionTrace,
        conversation_id: SessionId,
        messages: list[ConversationMessage],
        principal: AuthenticatedPrincipal,
        source_platform: str,
        input_artifact_refs: tuple[ResourceRef, ...],
    ) -> None:
        self._require_trace_scope(prior, principal, action="conversation_run_resume")
        if prior.conversation_id != conversation_id:
            raise ConversationOperationConflict("turn_id is bound to a different session")
        self._require_goal_mode(prior)
        if prior.messages != tuple(messages) or prior.input_artifact_refs != input_artifact_refs:
            raise ConversationOperationConflict("turn_id is bound to different turn input")
        if prior.deployment_digest is not None and (
            self._experiment_deployment is None or self._experiment_deployment.deployment_digest != prior.deployment_digest):
            raise PermissionError("original experiment deployment is no longer available")
        if prior.bash_authorization_digest is not None:
            require_bash_authorization(prior, self._bash_authorization)
        if (prior.answer_protocol_version != AnswerProtocolVersion.MARKDOWN_STATUS
                or prior.answer_result_binding != self._answer_result.config):
            raise ConversationOperationConflict("原运行的回答模块绑定缺失或与本次装配不同，请使用新对话进行独立运行。")
        if prior.feature_flags_binding != self._answer_result.feature_flags:
            raise ConversationOperationConflict("原运行的 feature flags 与本次装配不同，请使用新对话。")
        if prior.tool_profile_binding != self._tool_profile:
            raise ConversationOperationConflict("原轮次的 Conversation 工具组与当前配置不同，请使用原配置恢复。")
        self._require_skill_scope(prior, self._skill_scope_digest(principal, conversation_id, source_platform))
        if prior.workspace_changes and source_platform != "web":
            raise PermissionError("工作区对话只能通过 Web 恢复")

    def _skill_scope_digest(
        self, principal: AuthenticatedPrincipal, conversation_id: SessionId, source_platform: str,
    ) -> str | None:
        if self._skill_catalog is None:
            return None
        return self._skill_catalog.scope_digest(principal, conversation_id, source_platform=source_platform)

    def _require_skill_scope(self, trace: InteractionTrace, current_digest: str | None) -> None:
        if trace.skill_scope_digest != current_digest:
            raise ConversationOperationConflict(self._prompts.render("skills.scope_changed"))

    def _turn_working_plan(self, prior: InteractionTrace) -> ConversationWorkingPlan | None:
        working_plan = prior.working_plan
        if working_plan is None and not task_switch_turn(prior):
            predecessors = selected_analysis_turns(prior, self._journal.task_traces(prior))
            working_plan = next((
                source.working_plan for source in reversed(predecessors) if source.working_plan is not None
            ), None)
        return working_plan

    def _recorded_turn_view(
        self, prior: InteractionTrace, working_plan: ConversationWorkingPlan | None,
    ) -> ConversationTurnView | None:
        conversation_id, run_ref, principal = prior.conversation_id, prior.interaction_run_ref, prior.principal
        pending_workspace = next((item for item in prior.workspace_changes if item.receipt is None), None)
        if pending_workspace is not None:
            if self._workspace_changes is None:
                raise ConversationOperationConflict("当前部署未装配工作区授权")
            return self._workspace_confirmation(pending_workspace, working_plan)
        if prior.workspace_changes:
            receipt = prior.workspace_changes[-1].receipt
            if receipt is not None and receipt.status != "applied":
                message = {
                    "rejected": "你已拒绝这份工作区变更清单，未执行其中的操作。",
                    "unknown": "工作区变更有操作结果未知，已停止后续派发。请先核对实际文件状态。",
                    "blocked": "工作区变更被当前策略阻止，后续操作未执行。请查看已记录的执行结果。",
                }[receipt.status]
                return ConversationTurnView(
                    conversation_id=conversation_id, interaction_run_ref=run_ref, disposition="limitation",
                    message=ConversationMessage(role="assistant", content=message), working_plan=working_plan,
                )
        if prior.knowledge_save_operation is not None:
            return self._knowledge_save.turn_view(
                conversation_id,
                run_ref,
                prior.knowledge_save_operation,
            )
        if prior.knowledge_delete_command_ref is not None:
            operation = (
                self._knowledge_lifecycle.get_delete(
                    prior.knowledge_delete_command_ref,
                    user_id=principal.user_id,
                )
                if self._knowledge_lifecycle is not None
                else None
            )
            if operation is None:
                raise ConversationOperationNotFound(
                    "knowledge delete operation not found"
                )
            return self._knowledge_delete_turn_view(conversation_id, run_ref, operation)
        if prior.final_message is not None:
            resources = ()
            if prior.deployment_digest is not None and prior.final_message.disposition == "answer":
                if self._experiment_completion is None:
                    raise ConversationFailure(self._prompts.render('conversation.service.experiment_restore_validation_unavailable'))
                self._experiment_completion.validate(prior)
            return ConversationTurnView(
                resources=resources,
                interaction_run_ref=run_ref,
                conversation_id=conversation_id,
                disposition=prior.final_message.disposition,
                message=ConversationMessage(
                    role="assistant", content=prior.final_message.message
                ),
                working_plan=working_plan,
            )
        last_decision = next(iter(reversed(prior.responded_steps)), None)
        if last_decision is not None:
            waiting = next((item for item in last_decision.dispositions if item.plan_waiting), None)
            if waiting is not None:
                return self._plan_review_view(
                    run_ref, conversation_id, waiting.working_plan_snapshot, waiting.plan_review_message or "",
                )
        return None

    def _respond_locked(self, **arguments) -> ConversationTurnView:
        while True:
            try:
                return self._run_locked(**arguments)
            except ConversationSteeringPending:
                # The candidate was journaled without publishing its answer.
                continue

    def _run_locked(
        self,
        *,
        conversation_id: SessionId,
        messages: list[ConversationMessage],
        principal: AuthenticatedPrincipal,
        source_platform: str = "web",
        interaction_run_ref: str,
        input_artifact_refs: tuple[ResourceRef, ...] = (),
        on_registered: Callable[[str], None] | None = None,
        on_turn_stopping: Callable[[], None] | None = None,
    ) -> ConversationTurnView:
        if not messages or messages[-1].role != "user":
            raise ConversationInputError("conversation must end with a user message")
        if self._model_client is None:
            raise ConversationFailure(
                "conversation model is not configured",
                reason_code="model_not_configured",
                failure_stage="application_configuration",
            )
        owner = principal
        run_ref = interaction_run_ref
        prior = self._journal.get(run_ref)
        if prior is None:
            tail = self._journal.last_turn(principal=principal, session_id=conversation_id)
            skill_scope_digest = self._skill_scope_digest(principal, conversation_id, source_platform)
            if tail is not None:
                self._require_skill_scope(tail, skill_scope_digest)
            if tail is not None and tail.goal_mode != self._goal_mode:
                raise ConversationOperationConflict("Goal mode is fixed for this session. Start a new session.")
            if tail is not None and (
                tail.answer_protocol_version != AnswerProtocolVersion.MARKDOWN_STATUS
                or tail.answer_result_binding != self._answer_result.config
                or tail.feature_flags_binding != self._answer_result.feature_flags
            ):
                raise ConversationOperationConflict("同一对话不能更换答复测试模式或核验配置，请使用独立对话。")
            if len(set(input_artifact_refs)) != len(input_artifact_refs):
                raise ConversationInputError("input_artifact_refs contains duplicate references")
            sources = []
            for ref in input_artifact_refs:
                if ref.resource_type != "artifact" or ref.owner != principal or self._artifact_port is None:
                    raise PermissionError("initial Artifact reference is not authorized")
                sources.append(ArtifactSourceInput(resource=self._artifact_port.resource_item(
                    ref, principal=principal, owner=principal)))
            deployment = self._experiment_deployment
            bound = deployment is not None and deployment.authorized_principal == principal and all(
                item.resource_ref in input_artifact_refs for item in deployment.materials if item.role != "test_qrels")
            authorization = self._bash_authorization
            analysis_bound = (authorization is not None and authorization.authorized_principal == principal
                              and authorization.conversation_id == conversation_id)
            if analysis_bound and any(
                item.bash_authorization_digest is not None
                and item.bash_authorization_digest != authorization.authorization_digest
                for item in self._journal.session_runs(principal=principal, session_id=conversation_id)
            ):
                raise PermissionError("同一分析对话不能更换授权身份并重置额度")
            now = datetime.now(UTC)
            prior = InteractionTrace(
                answer_protocol_version=AnswerProtocolVersion.MARKDOWN_STATUS,
                answer_result_binding=self._answer_result.config,
                feature_flags_binding=self._answer_result.feature_flags,
                tool_profile_binding=self._tool_profile,
                skill_scope_digest=skill_scope_digest,
                goal_mode=self._goal_mode,
                mcp_write_dispatches=(),
                interaction_run_ref=run_ref, conversation_id=conversation_id, principal=principal,
                messages=tuple(messages), input_artifact_refs=tuple(input_artifact_refs), inputs=tuple(sources),
                usage=CommittedUsage(provider_usage_complete=True, model_calls=0, input_tokens=0, output_tokens=0),
                deployment_digest=deployment.deployment_digest if bound else None,
                bash_authorization_digest=authorization.authorization_digest if analysis_bound else None,
                run_deadline_at=(now + timedelta(seconds=authorization.turn_timeout_seconds)
                                 if analysis_bound else now + timedelta(seconds=deployment.limits.run_timeout_seconds)
                                 if bound else None),
                max_execution_seconds=(authorization.max_execution_seconds if analysis_bound
                                       else deployment.limits.max_execution_seconds if bound else None),
            )
            self._journal.put(prior)
            if on_registered is not None:
                on_registered(run_ref)
        self._validate_turn_input(prior, conversation_id, messages, principal, source_platform, input_artifact_refs)
        working_plan = self._turn_working_plan(prior)
        existing_view = self._recorded_turn_view(prior, working_plan)
        if existing_view is not None:
            return existing_view
        inputs: list[InteractionInput] = list(prior.inputs)
        # The review owner checks its exact original input and current version.
        # Restarting this invocation does not change those persisted facts.
        execution_order = list(prior.execution_order if prior else ())
        concurrent_batches = list(prior.concurrent_batches if prior else ())
        context_composition = list(prior.context_composition if prior else ())
        usage = prior.usage if prior else CommittedUsage(
            provider_usage_complete=True,
            model_calls=0,
            input_tokens=0,
            output_tokens=0,
        )
        plan_review_required = self._goal_requires_plan_review(prior)
        inputs, usage, execution_order = self._recover_accepted_requests(
            run_ref=run_ref, principal=principal, owner=owner, conversation_id=conversation_id,
            source_platform=source_platform, inputs=inputs, usage=usage, execution_order=execution_order,
        )
        if (
            prior.deployment_digest is not None and pending_experiment_submission(inputs) is not None
            and prior.first_goal_operation is not None
            and not plan_review_required
        ):
            if self._experiment_completion is None:
                raise ConversationFailure(self._prompts.render('conversation.service.experiment_delivery_restore_unavailable'))
            try:
                self._experiment_completion.validate(self._journal.get(run_ref))
            except DeliveryIncomplete as error:
                inputs.append(self._experiment_completion_feedback(error))
                self._commit(
                    run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
                    context_composition, working_plan=working_plan,
                )
            else:
                return self._complete_experiment_answer(
                    run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
                    context_composition, working_plan=working_plan,
                )
        while True:
            trace = self._journal.get(run_ref)
            plan_review_required = self._goal_requires_plan_review(trace)
            usage = trace.usage
            first_goal = trace.first_goal_operation
            delivery = first_goal.patch.delivery if first_goal is not None and first_goal.patch is not None else None
            if delivery is not None and delivery.mode == "background":
                return self._fail_closed_limitation(conversation_id, run_ref, principal, messages,
                    inputs, usage, execution_order, concurrent_batches, context_composition,
                    working_plan=working_plan, message=self._prompts.render("conversation.service.background_unavailable"))
            scope = ExecutionScope(principal=principal, execution_id=run_ref, thread_id=conversation_id)
            trace = self._model_journal_call("agent_interaction_turn", self._journal.recover_model_response_originals, scope)
            if not any(record.step_no is not None and not record.consumed for record in trace.model_decisions):
                trace = self._journal.claim_steering(scope)
            usage = trace.usage
            decision = self._pending_final_candidate(inputs, trace)
            model_response = None
            protocol_feedback = None
            decision_trace = self._journal.get(run_ref)
            paid_main = any(not record.consumed and record.response_refs
                and record.operation == "agent_interaction_turn" for record in decision_trace.model_decisions)
            if decision is None and not paid_main:
                if deadline_elapsed(trace.run_deadline_at):
                    return self._fail_closed_limitation(
                        conversation_id, run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition,
                        working_plan=working_plan, message=self._prompts.render('conversation.service.run_deadline_limitation'),
                    )
                if self._budget.new_decision_exhausted(decision_trace, usage):
                    return self._budget_exhausted(
                        conversation_id,
                        run_ref,
                        principal,
                        messages,
                        inputs,
                        usage,
                        execution_order,
                        concurrent_batches,
                        context_composition,
                                    working_plan,
                    )
            capabilities = self._effective_capabilities(run_ref=run_ref, source_platform=source_platform)
            if decision is None:
                decision, model_response, composition, protocol_feedback = self._decide(
                    run_ref=run_ref, messages=messages, source_platform=source_platform,
                    capabilities=self._model_visible_capabilities_for_turn(capabilities, inputs, run_ref=run_ref),
                    inputs=inputs, usage=usage, turn_index=usage.model_turns, working_plan=working_plan)
                usage = self._record_model_usage(self._journal.get(run_ref).usage, model_response, model_turn=True, run_ref=run_ref)
                if not any(item.turn_index == composition.turn_index for item in context_composition):
                    context_composition.append(composition)
                self._commit(run_ref, principal, messages, inputs, usage, execution_order,
                    concurrent_batches, context_composition,
                    working_plan=working_plan, model_response=model_response)
            if protocol_feedback is not None:
                inputs.append(protocol_feedback)
                self._commit(
                    run_ref,
                    principal,
                    messages,
                    inputs,
                    usage,
                    execution_order,
                    concurrent_batches,
                    context_composition,
                    working_plan=working_plan,
                )
                continue
            assert decision is not None
            partially_decoded = decision if isinstance(decision, PartiallyDecodedToolBatch) else None
            if partially_decoded is not None:
                decision = partially_decoded.proposal
            if isinstance(decision, ClarificationInvocation):
                question = FinalMessage(disposition="clarification_required", segments=(
                    ConversationAnswerSegment(text=decision.question),))
                self._commit(run_ref, principal, messages, inputs, usage, execution_order,
                    concurrent_batches, context_composition,
                    working_plan=working_plan, final_message=question,
                    call_dispositions=(ModelCallDisposition(call_id=decision.call_id,
                        operation="request_clarification", status="accepted"),))
                return ConversationTurnView(interaction_run_ref=run_ref, conversation_id=conversation_id,
                    disposition=question.disposition, message=ConversationMessage(role="assistant", content=question.message),
                    working_plan=working_plan)
            goal_trace = self._journal.get(run_ref)
            step_no = goal_trace.current_step_no
            committed_call_ids = self._committed_call_ids(goal_trace)
            # Retain every actual answer proposal, including revisions rejected
            # by the goal prerequisite. Recording does not admit or publish it.
            if (isinstance(decision, FinalMessage)
                    and self._pending_final_candidate(inputs, goal_trace) != decision):
                inputs.append(self._answer_submission(decision, run_ref=run_ref,
                    principal=principal, turn=step_no))
                self._commit(run_ref, principal, messages, inputs, usage, execution_order,
                    concurrent_batches, context_composition,
                    working_plan=working_plan)
                goal_trace = self._journal.get(run_ref)
            outcome = None
            if self._goals is not None:
                predecessors = selected_analysis_turns(goal_trace, self._journal.task_traces(goal_trace))
                read_only_tools = frozenset(tool.name for tool in capabilities.tools if tool.read_only)
                outcome = self._goals.admit(decision, trace=goal_trace, previous=predecessors,
                    prompts=self._prompts, read_only_tools=read_only_tools)
                if (isinstance(outcome, (GoalMaintenanceInvocation, GoalOperationRecord))
                        and outcome.call_id in committed_call_ids):
                    operation = "read_current_goal" if isinstance(outcome, GoalOperationRecord) else SUBMIT_GOAL_PATCH
                    outcome = self._duplicate_call_feedback(outcome.call_id, action_name=operation)
                if isinstance(outcome, GoalOperationRecord):
                    assert isinstance(decision, ContinueTurnProposal)
                    # A resumed mixed step can already have the Goal read but still owe tool results.
                    if outcome not in goal_trace.goal_operations:
                        usage = usage.model_copy(update={"tool_calls": usage.tool_calls + 1})
                        self._commit(run_ref, principal, messages, inputs, usage, execution_order,
                            concurrent_batches, context_composition, working_plan=working_plan,
                            goal_operation=outcome, call_dispositions=(ModelCallDisposition(
                                call_id=outcome.call_id, operation="read_current_goal", status="accepted"),))
                    if not decision.actions and decision.working_plan is None:
                        continue
                    outcome = self._goals.admit(decision.model_copy(update={"goal_read": None}),
                        trace=goal_trace, previous=predecessors, prompts=self._prompts, read_only_tools=read_only_tools)
            if outcome is not None:
                if isinstance(outcome, GoalMaintenanceInvocation):
                    outcome, result, usage, task = self._verify_goal_maintenance(outcome, run_ref=run_ref,
                        owner=owner, source_platform=source_platform)
                    if result is not None and result.interaction_input not in inputs:
                        inputs.append(result.interaction_input)
                    if result is not None and result.action_id not in execution_order:
                        execution_order.append(result.action_id)
                    usage = usage.model_copy(update={"tool_calls": usage.tool_calls + 1})
                accepted_goal = outcome if isinstance(outcome, GoalOperationRecord) else None
                if accepted_goal is None:
                    inputs.append(outcome)
                elif accepted_goal.patch is not None and accepted_goal.patch.task is not None and task.action != "continue":
                    working_plan = next((source.working_plan for source in reversed(task.previous)
                                         if source.working_plan is not None), None)
                if accepted_goal is not None and accepted_goal.patch is not None and working_plan is not None:
                    active_ids = {item.item_id for item in accepted_goal.goal.active_items(run_ref)}
                    changed_ids = {change.item_id for change in accepted_goal.patch.changes
                                   if not isinstance(change, AddGoalItem)}
                    delivery = accepted_goal.patch.delivery
                    if delivery is not None and delivery.mode == "deliver_final_result":
                        working_plan = supersede_pending_working_plan(working_plan)
                    else:
                        working_plan = supersede_pending_working_plan(working_plan,
                            affected=lambda step: not step.goal_item_ids or bool(set(step.goal_item_ids) - (active_ids - changed_ids)))
                self._commit(run_ref, principal, messages, inputs, usage, execution_order,
                    concurrent_batches, context_composition,
                    working_plan=working_plan, goal_operation=accepted_goal,
                    call_dispositions=((ModelCallDisposition(call_id=accepted_goal.call_id,
                        operation="maintain_goal",
                        status="accepted"),) if accepted_goal is not None else ()))
                continue
            if isinstance(decision, FinalMessage):
                if plan_review_required:
                    inputs.append(required_plan_review_feedback())
                    self._commit(
                        run_ref,
                        principal,
                        messages,
                        inputs,
                        usage,
                        execution_order,
                        concurrent_batches,
                        context_composition,
                        working_plan=working_plan,
                    )
                    continue
                if (
                    decision.disposition != "answer"
                    and self._has_failed_or_unknown_action_observation(inputs)
                ):
                    self._commit(
                        run_ref,
                        principal,
                        messages,
                        inputs,
                        usage,
                        execution_order,
                        concurrent_batches,
                        context_composition,
                        final_message=decision,
                        working_plan=working_plan,
                    )
                    return ConversationTurnView(
                        interaction_run_ref=run_ref,
                        conversation_id=conversation_id,
                        disposition=decision.disposition,
                        message=ConversationMessage(
                            role="assistant", content=decision.message
                        ),
                        working_plan=working_plan,
                    )
                if prior.deployment_digest is not None and decision.disposition == "answer":
                    inputs.append(self._answer_submission(decision, run_ref=run_ref,
                        principal=principal, turn=step_no))
                    # Save the real report and billed response before checking or publishing files.
                    self._commit(
                        run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition,
                        working_plan=working_plan,
                    )
                    if self._experiment_completion is None:
                        raise ConversationFailure(self._prompts.render('conversation.service.experiment_delivery_check_unavailable'))
                    try:
                        self._experiment_completion.validate(self._journal.get(run_ref))
                    except DeliveryIncomplete as error:
                        inputs.append(self._experiment_completion_feedback(error))
                    else:
                        return self._complete_experiment_answer(
                            run_ref, principal, messages, inputs, usage, execution_order,
                            concurrent_batches, context_composition,
                            working_plan=working_plan,
                        )
                    self._commit(
                        run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition,
                        working_plan=working_plan,
                    )
                    continue
                if decision.disposition == "answer" and self._pending_final_candidate(inputs, goal_trace) != decision:
                    inputs.append(self._answer_submission(decision, run_ref=run_ref,
                        principal=principal, turn=step_no))
                    self._commit(
                        run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition,
                        working_plan=working_plan,
                    )
                delivery_inputs = self._task_inputs(self._task_turns(run_ref), inputs)
                if self._answer_result.verification_enabled:
                    verified, result, usage = (
                        self._verify_before_send(
                            decision,
                            verification_inputs=tuple(delivery_inputs),
                            run_ref=run_ref,
                            owner=owner,
                            source_platform=source_platform,
                            usage=usage,
                            attempt=len(execution_order),
                        )
                    )
                    if result.interaction_input not in inputs:
                        inputs.append(result.interaction_input)
                    if result.action_id not in execution_order:
                        execution_order.append(result.action_id)
                    if verified is None:
                        # Verifier owns acceptance, not the next action.
                        # Check the hard budget before the model chooses again.
                        self._commit(
                            run_ref,
                            principal,
                            messages,
                            inputs,
                            usage,
                            execution_order,
                            concurrent_batches,
                            context_composition,
                            working_plan=working_plan,
                        )
                        continue
                    decision = verified
                if (
                    decision.disposition == "answer"
                    and on_turn_stopping is not None
                    and not self._journal.pending_steering(run_ref)
                ):
                    on_turn_stopping()
                if decision.disposition == "answer" and working_plan is not None:
                    working_plan = complete_working_plan(
                        working_plan,
                        inputs=tuple(inputs),
                    )
                self._commit(
                    run_ref,
                    principal,
                    messages,
                    inputs,
                    usage,
                    execution_order,
                    concurrent_batches,
                    context_composition,
                    final_message=decision,
                    working_plan=working_plan,
                )
                return ConversationTurnView(
                    interaction_run_ref=run_ref,
                    conversation_id=conversation_id,
                    disposition=decision.disposition,
                    message=ConversationMessage(
                        role="assistant", content=decision.message
                    ),
                    working_plan=working_plan,
                )

            wait_feedback = admit_plan_wait_boundary(decision)
            if (wait_feedback is None and plan_review_required and decision.actions
                    and not self._actions_are_planning_safe(decision.actions, capabilities)):
                wait_feedback = required_plan_review_feedback()
            if wait_feedback is not None:
                inputs.append(wait_feedback)
                self._commit(
                    run_ref,
                    principal,
                    messages,
                    inputs,
                    usage,
                    execution_order,
                    concurrent_batches,
                    context_composition,
                    working_plan=working_plan,
                )
                continue

            previous_plan = working_plan
            plan_call_committed = decision.working_plan_call_id is not None and any(
                item.call_id == decision.working_plan_call_id and item.status == "accepted"
                for record in self._journal.get(run_ref).model_decisions
                if record.step_no == step_no
                for item in record.dispositions
                if item.operation in {"working_plan", "read_working_plan"}
            )
            if decision.working_plan is not None and not plan_call_committed:
                result_delivered = (
                    working_plan is not None
                    and self._journal.plan_result_delivered(
                        working_plan, principal=principal, session_id=conversation_id,
                    )
                )
                review_feedback = admit_plan_review(
                    decision,
                    current=working_plan,
                    result_delivered=result_delivered,
                    review_required=plan_review_required,
                    unsafe_execution_started=(
                        self._unsafe_execution_started_before_plan(
                            execution_order,
                            inputs,
                            capabilities,
                        )
                    ),
                )
                if review_feedback is not None:
                    inputs.append(review_feedback)
                    self._commit(
                        run_ref,
                        principal,
                        messages,
                        inputs,
                        usage,
                        execution_order,
                        concurrent_batches,
                        context_composition,
                        working_plan=working_plan,
                    )
                    continue
                feedback, admitted_plan = admit_working_plan(
                    decision.working_plan,
                    current=working_plan,
                    inputs=tuple(inputs),
                    wait_for_user=decision.wait_for_user,
                    result_delivered=result_delivered,
                    prompts=self._prompts,
                    active_goal_item_ids=self._plan_goal_item_ids(run_ref),
                )
                if feedback is not None:
                    inputs.append(feedback)
                    self._commit(
                        run_ref,
                        principal,
                        messages,
                        inputs,
                        usage,
                        execution_order,
                        concurrent_batches,
                        context_composition,
                        working_plan=working_plan,
                    )
                    continue
                working_plan = admitted_plan
                if decision.working_plan_call_id is not None:
                    reading_plan = decision.working_plan.steps is None
                    review_message = (self._plan_review_view(run_ref, conversation_id, working_plan,
                        decision.message).message.content if decision.wait_for_user else None)
                    self._commit(run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition,
                        working_plan=working_plan, call_dispositions=(ModelCallDisposition(
                            call_id=decision.working_plan_call_id,
                            operation="read_working_plan" if reading_plan else "working_plan", status="accepted",
                            plan_id=working_plan.plan_id if working_plan else None,
                            plan_revision=working_plan.revision if working_plan else None,
                            working_plan_snapshot=working_plan, plan_waiting=decision.wait_for_user,
                            plan_review_message=review_message),))
            progress_feedback = admit_continue_turn_progress(
                decision,
                previous_plan=previous_plan,
                admitted_plan=working_plan,
            )
            if progress_feedback is not None:
                inputs.append(progress_feedback)
                self._commit(
                    run_ref,
                    principal,
                    messages,
                    inputs,
                    usage,
                    execution_order,
                    concurrent_batches,
                    context_composition,
                    working_plan=working_plan,
                )
                continue
            if decision.wait_for_user:
                self._commit(
                    run_ref,
                    principal,
                    messages,
                    inputs,
                    usage,
                    execution_order,
                    concurrent_batches,
                    context_composition,
                    working_plan=working_plan,

                )
                return self._plan_review_view(run_ref, conversation_id, working_plan, decision.message)

            save_actions = [
                action
                for action in decision.actions
                if (
                    isinstance(action, ToolCallProposal)
                    and action.tool_name == _KNOWLEDGE_SAVE_CAPABILITY
                )
            ]
            if save_actions:
                action = save_actions[0]
                feedback, arguments = self._knowledge_save.admit(
                    action,
                    all_actions=decision.actions,
                    messages=messages,
                )
                if feedback is not None:
                    inputs.append(self._name_action_feedback(
                        feedback,
                        decision.actions,
                    ))
                    self._commit(
                        run_ref,
                        principal,
                        messages,
                        inputs,
                        usage,
                        execution_order,
                        concurrent_batches,
                        context_composition,
                        working_plan=working_plan,
                    )
                    continue
                operation = self._knowledge_save.prepare(
                    action,
                    arguments=arguments,
                    run_ref=run_ref,
                    messages=messages,
                    principal=principal,
                    owner=owner,
                )
                self._commit(
                    run_ref,
                    principal,
                    messages,
                    inputs,
                    usage,
                    execution_order,
                    concurrent_batches,
                    context_composition,
                    knowledge_save_operation=operation,
                    working_plan=working_plan,
                    call_dispositions=(ModelCallDisposition(call_id=action.action_id,
                        operation="knowledge_save", status="prepared", operation_ref=operation.command.command_id),
                        ),
                )
                return self._knowledge_save.turn_view(
                    conversation_id,
                    run_ref,
                    operation,
                )

            delete_actions = [
                action
                for action in decision.actions
                if isinstance(action, ToolCallProposal)
                and action.tool_name == _PREPARE_KNOWLEDGE_DELETE_CAPABILITY
            ]
            if delete_actions:
                action = delete_actions[0]
                feedback, arguments = self._admit_knowledge_delete(
                    action,
                    all_actions=decision.actions,
                    principal=principal,
                    owner=owner,
                )
                if feedback is not None:
                    inputs.append(self._name_action_feedback(
                        feedback,
                        decision.actions,
                    ))
                    self._commit(
                        run_ref,
                        principal,
                        messages,
                        inputs,
                        usage,
                        execution_order,
                        concurrent_batches,
                        context_composition,
                        working_plan=working_plan,
                    )
                    continue
                try:
                    operation = self._knowledge_lifecycle.prepare_delete(
                        owner_id=owner.principal_id,
                        user_id=principal.user_id,
                        target_note_id=arguments.target_knowledge_item_id,
                        reason=arguments.reason,
                        idempotency_key=sha256(
                            f"{run_ref}:{action.action_id}".encode("utf-8")
                        ).hexdigest(),
                    )
                except (KeyError, PermissionError, ValueError) as error:
                    inputs.append(self._name_action_feedback(
                        self._application_operation_feedback(action, error),
                        decision.actions,
                    ))
                    self._commit(
                        run_ref,
                        principal,
                        messages,
                        inputs,
                        usage,
                        execution_order,
                        concurrent_batches,
                        context_composition,

                    )
                    continue
                execution_order.append(action.action_id)
                self._commit(
                    run_ref,
                    principal,
                    messages,
                    inputs,
                    usage,
                    execution_order,
                    concurrent_batches,
                    context_composition,
                    knowledge_delete_command_ref=operation.command.command_id,
                    working_plan=working_plan,
                    call_dispositions=(ModelCallDisposition(call_id=action.action_id,
                        operation="knowledge_delete", status="prepared", operation_ref=operation.command.command_id),
                        ),
                )
                return self._knowledge_delete_turn_view(
                    conversation_id,
                    run_ref,
                    operation,
                )

            # Persist billed usage and admitted work state before durable acceptance.
            self._commit(
                run_ref,
                principal,
                messages,
                inputs,
                usage,
                execution_order,
                concurrent_batches,
                context_composition,
                working_plan=working_plan,
            )
            latest = self._journal.get(run_ref)
            if latest.bash_authorization_digest is not None and (
                partially_decoded is None or not self._budget.action_dispatch_exhausted(latest)
            ):
                self._admit_research_model_call(run_ref, usage)
                latest = self._journal.get(run_ref)
            if decision.actions and self._budget.action_dispatch_exhausted(latest):
                return self._budget_exhausted(conversation_id, run_ref, principal, messages, inputs,
                    latest.usage, execution_order, concurrent_batches, context_composition, working_plan,
                    partially_decoded=partially_decoded)
            workspace_action = next((action for action in decision.actions if isinstance(action, ToolCallProposal)
                                     and action.tool_name == WORKSPACE_CHANGES), None)
            if workspace_action is not None:
                try:
                    if self._workspace_changes is None or len(decision.actions) != 1:
                        raise ValueError("请单独提交完整的工作区变更清单")
                    if workspace_action.action_id in committed_call_ids:
                        raise ValueError("工作区调用标识已经使用")
                    if self._budget.tool_calls_exhausted(latest.usage):
                        raise ValueError("工作区变更已达本轮工具调用额度")
                    operation = self._workspace_changes.prepare(
                        latest, source_platform=source_platform, action_id=workspace_action.action_id,
                        arguments=WorkspaceChangeArguments.model_validate(workspace_action.arguments),
                        plan_step_id=active_working_plan_step_id(working_plan),
                    )
                except (ValueError, PermissionError, ConversationOperationConflict) as error:
                    inputs.append(self._name_action_feedback(
                        self._application_operation_feedback(workspace_action, error), decision.actions,
                    ))
                    self._commit(run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
                                 context_composition, working_plan=working_plan)
                    continue
                self._workspace_changes.store(operation)
                return self._workspace_confirmation(operation, working_plan)
            results, usage, concurrent = self._execute_actions(
                decision,
                conversation_id=conversation_id,
                run_ref=run_ref,
                principal=principal,
                owner=owner,
                source_platform=source_platform,
                usage=usage,
                committed_action_ids=committed_call_ids,
                committed_inputs=self._task_inputs(self._task_turns(run_ref), inputs),
                plan_step_id=active_working_plan_step_id(working_plan),
                partially_decoded=partially_decoded,
                replaying_model_response=paid_main,
            )
            inputs.extend(item.interaction_input for item in results)
            executed_results = [
                item
                for item in results
                if isinstance(item.interaction_input, ActionObservation)
            ]
            execution_order.extend(item.action_id for item in executed_results)
            if concurrent:
                concurrent_batches.append(
                    tuple(item.action_id for item in executed_results)
                )
            self._commit(
                run_ref,
                principal,
                messages,
                inputs,
                usage,
                execution_order,
                concurrent_batches,
                context_composition,
                working_plan=working_plan,
            )

        return self._budget_exhausted(
            conversation_id,
            run_ref,
            principal,
            messages,
            inputs,
            usage,
            execution_order,
            concurrent_batches,
            context_composition,
            working_plan,
        )

    def _experiment_completion_feedback(self, error: DeliveryIncomplete) -> DecisionFeedback:
        return DecisionFeedback(
            action_id="experiment-delivery", reason_code="experiment_delivery_incomplete",
            message=json.dumps([gap.model_dump(mode="json") for gap in error.gaps], ensure_ascii=False),
            required_repair=self._prompts.render('conversation.service.experiment_completion_repair'),
        )

    def _complete_experiment_answer(
        self, run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
        context_composition, *, working_plan,
    ):
        if self._experiment_completion is None:
            raise ConversationFailure(self._prompts.render('conversation.service.experiment_validation_unavailable'))
        trace = self._journal.get(run_ref)
        submission = experiment_submission(trace, prompts=self._prompts)
        # Persist the exact submission and its usage before completion checks.
        self._commit(
            run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
            context_composition, working_plan=working_plan,
        )
        try:
            self._experiment_completion.validate(self._journal.get(run_ref))
        except DeliveryIncomplete as error:
            # This boundary has no new model call. A missing physical result cannot be
            # converted into an answer by a previously successful semantic review.
            return self._fail_closed_limitation(
                trace.conversation_id, run_ref, principal, messages, inputs, usage,
                execution_order, concurrent_batches, context_composition,
                working_plan=working_plan,
                message=self._prompts.render('conversation.service.experiment_incomplete_prefix') + str(error),
            )
        final = submission.final
        if working_plan is not None:
            working_plan = complete_working_plan(working_plan, inputs=tuple(inputs))
        self._commit(
            run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
            context_composition, working_plan=working_plan, final_message=final,
        )
        return ConversationTurnView(
            interaction_run_ref=run_ref, conversation_id=trace.conversation_id,
            disposition="answer", message=ConversationMessage(role="assistant", content=final.message),
            working_plan=working_plan,
        )

    def _append_artifact_sources(self, run_ref, inputs):
        if self._artifact_port is None:
            return
        trace = self._journal.get(run_ref)
        existing = set(input_resource_refs(inputs))
        refs = list(trace_resource_refs(trace))
        control_refs = set(recorded_checkpoint_refs((trace,)))
        # Only the experiment's named publication contract supplies child files.
        for record in trace.experiment_records:
            if record.receipt is None:
                continue
            for result_ref in record.receipt.result_refs:
                snapshot = self._artifact_port.read_snapshot(
                    result_ref, principal=trace.principal, owner=trace.principal
                )
                published = PublishedExperimentResult.model_validate_json(
                    snapshot.content
                )
                refs.extend(
                    (
                        published.raw_result_ref,
                        published.rankings_ref,
                        published.coverage_ref,
                        published.metrics_ref,
                        published.per_query_ref,
                          published.corpus.resource_ref,
                          published.queries.resource_ref,
                    )
                )
        control_refs.update(trace_goal_draft_refs(trace))
        for ref in dict.fromkeys(refs):
            if ref in control_refs:
                continue
            if ref not in existing:
                try:
                    resource = self._artifact_port.resource_item(ref, principal=trace.principal, owner=trace.principal)
                except FileNotFoundError:
                    action_id = f"artifact-unavailable:{ref.resource_id}:{ref.revision}"
                    if not any(isinstance(item, DecisionFeedback) and item.action_id == action_id for item in inputs):
                        inputs.append(DecisionFeedback(action_id=action_id, reason_code="artifact_unavailable",
                            message=self._prompts.render('conversation.service.artifact_unavailable', resource=ref.model_dump_json()),
                            required_repair=self._prompts.render('conversation.service.artifact_unavailable_repair')))
                    continue
                inputs.append(ArtifactSourceInput(resource=resource))
                existing.add(ref)

    def _recover_accepted_requests(
        self,
        *,
        run_ref,
        principal,
        owner,
        conversation_id,
        source_platform,
        inputs,
        usage,
        execution_order,
    ):
        trace = self._journal.get(run_ref)
        observed = {
            item.action_id for item in inputs if isinstance(item, ActionObservation)
        }
        for accepted in trace.accepted_tool_requests:
            pending_bash = (
                isinstance(accepted, AcceptedBashToolRequest)
                and accepted.command is not None
                and (accepted.receipt is None or accepted.receipt.status == "unknown")
            )
            pending_experiment = (
                isinstance(accepted, AcceptedExperimentToolRequest)
                and any(
                    record.action_id == accepted.action_id
                    and record.command is not None
                    and (record.receipt is None or record.receipt.status == "unknown")
                    for record in trace.experiment_records
                )
            )
            was_observed = accepted.action_id in observed
            if was_observed and not (pending_bash or pending_experiment):
                continue
            if (
                isinstance(accepted, AcceptedArtifactToolRequest)
                and accepted.receipt is None and accepted.failure is None
                and self._artifact_port is not None
            ):
                recovered = self._artifact_port.recover_draft(
                    execution_scope=accepted.execution_scope, tool_call_id=accepted.action_id,
                    request=accepted.arguments.request, allowed_resource_refs=self._journal.readable_resource_refs(trace),
                )
                if recovered is not None:
                    self._journal.record_artifact_result(
                        execution_scope=accepted.execution_scope, action_id=accepted.action_id, receipt=recovered,
                    )
                    accepted = accepted.model_copy(update={"receipt": recovered})
            action = ToolCallProposal(
                action_id=accepted.action_id,
                tool_name=accepted.tool_name,
                arguments=accepted.arguments.model_dump(mode="json"),
            )
            if (
                isinstance(accepted, AcceptedArtifactToolRequest)
                and accepted.failure is not None
            ):
                observation = accepted.failure
            elif (
                isinstance(accepted, AcceptedArtifactToolRequest)
                and accepted.receipt is not None
            ):
                observation = ActionObservation(
                    kind="tool_result",
                    action_id=accepted.action_id,
                    capability_id=accepted.tool_name,
                    status="succeeded",
                    plan_step_id=accepted.plan_step_id,
                    execution_request_digest=canonical_digest(
                        {"tool_name": action.tool_name, "arguments": action.arguments}
                    ),
                    payload={
                        "ok": True,
                        "data": accepted.receipt.model_dump(mode="json"),
                        "evidence": [],
                    },
                )
            else:
                result = self._execute_one(
                    action,
                    (conversation_id, run_ref, principal, owner, source_platform),
                )
                observation = result.interaction_input.model_copy(
                    update={"plan_step_id": accepted.plan_step_id}
                )
            if was_observed:
                # The prior snapshot retains the unknown observation. The current
                # projection replaces it with this same action's reconciled fact.
                index = next(index for index, item in enumerate(inputs)
                             if isinstance(item, ActionObservation)
                             and item.action_id == accepted.action_id)
                inputs[index] = observation
            else:
                inputs.append(observation)
            observed.add(accepted.action_id)
            if accepted.action_id not in execution_order:
                execution_order.append(accepted.action_id)
            if not was_observed:
                usage = usage.model_copy(update={"tool_calls": usage.tool_calls + 1})
            self._append_artifact_sources(run_ref, inputs)
            self._journal.update(
                accepted.execution_scope,
                lambda latest: latest.model_copy(
                    update={
                        "revision": latest.revision + 1,
                        "inputs": tuple(inputs),
                        "usage": usage,
                        "execution_order": tuple(execution_order),
                    }
                ),
            )
        self._append_artifact_sources(run_ref, inputs)
        return inputs, usage, execution_order

    def trace(
        self,
        interaction_run_ref: str,
        *,
        principal: AuthenticatedPrincipal,
    ) -> InteractionTrace | None:
        trace = self._journal.get(interaction_run_ref)
        if trace is not None:
            self._require_trace_scope(
                trace,
                principal,
                action="conversation_trace_read",
            )
        return trace

    def _require_trace_scope(
        self,
        trace: InteractionTrace,
        principal: AuthenticatedPrincipal,
        *,
        action: str,
    ) -> None:
        if trace.principal == principal:
            return
        self._policy_decisions.record(
            PolicyDecisionEvent(
                action=action,
                effect="deny",
                rule="conversation_run_scope_mismatch",
                reason="authenticated principal does not own the interaction run",
                permission_scope="conversation_run:read",
                resource=trace.interaction_run_ref,
                user_id=principal.principal_id,
                run_id=trace.interaction_run_ref,
            )
        )
        raise PermissionError("interaction run scope mismatch")

    def _plan_review_view(self, run_ref, conversation_id, working_plan, message="") -> ConversationTurnView:
        return ConversationTurnView(
            interaction_run_ref=run_ref,
            conversation_id=conversation_id,
            disposition="plan_ready",
            message=ConversationMessage(
                role="assistant", content=message.strip() or self._prompts.render("conversation.service.plan_review_ready"),
            ),
            working_plan=working_plan,
        )

    @staticmethod
    def _workspace_confirmation(operation: WorkspaceChangeOperation, working_plan) -> ConversationTurnView:
        command = operation.command
        return ConversationTurnView(
            conversation_id=command.scope.thread_id,
            interaction_run_ref=command.scope.execution_id,
            disposition="confirmation_required",
            message=ConversationMessage(role="assistant", content="请审核清单中的工作区变更并确认是否执行。"),
            pending_confirmation=WorkspaceChangeConfirmation(
                command_digest=command.digest, changes=command.arguments.changes,
            ),
            working_plan=working_plan,
        )

    def decide_workspace_changes(
        self, *, conversation_id: SessionId, interaction_run_ref: str,
        principal: AuthenticatedPrincipal, command_digest: str, decision: WorkspaceDecision,
    ) -> WorkspaceChangeReceipt:
        if not conversation_id:
            raise ConversationInputError("conversation_id must not be empty")
        with (self._journal.exclusive_session(principal=principal, session_id=conversation_id),
              self._journal.exclusive_run(interaction_run_ref)):
            trace = self._journal.get(interaction_run_ref)
            if self._workspace_changes is None or trace is None or trace.conversation_id != conversation_id:
                raise ConversationOperationNotFound("工作区命令不存在")
            self._require_trace_scope(trace, principal, action="workspace_changes_decision")
            self._require_goal_mode(trace)
            return self._workspace_changes.decide(trace, digest=command_digest, decision=decision)

    def decide_knowledge_save(
        self,
        *,
        interaction_run_ref: str,
        principal: AuthenticatedPrincipal,
        decision: str,
        confirmation_ref: str,
    ) -> ConversationKnowledgeSaveOperation:
        return self._knowledge_save.decide(
            interaction_run_ref=interaction_run_ref,
            principal=principal,
            decision=decision,
            confirmation_ref=confirmation_ref,
        )

    def _admit_knowledge_delete(
        self,
        action,
        *,
        all_actions,
        principal,
        owner,
    ):
        if len(all_actions) != 1:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="knowledge_delete_requires_independent_confirmation",
                message=self._prompts.render("conversation.knowledge.exclusive", count=len(all_actions)),
                repairable_fields=("actions",),
                immutable_fields=("action_id",),
                required_repair=self._prompts.get("conversation.knowledge.exclusive_repair").template,
            ), None
        if self._knowledge_reader is None or self._knowledge_lifecycle is None:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="capability_missing",
                message=self._prompts.get("conversation.knowledge.delete_unavailable").template,
                immutable_fields=("action_id",),
                required_repair=self._prompts.get("conversation.knowledge.delete_unavailable_repair").template,
                disposition="fail_closed",
            ), None
        try:
            arguments = PrepareKnowledgeDeleteArguments.model_validate(action.arguments)
        except ValidationError as error:
            return self._invalid_special_arguments(action, error), None
        candidates = self._knowledge_reader.list_personal_knowledge(
            owner_id=owner.principal_id,
            user_id=principal.user_id,
            limit=50,
        )
        if arguments.target_knowledge_item_id not in {
            item.knowledge_item_id for item in candidates
        }:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="target_not_observed_in_scope",
                message=self._prompts.render("conversation.knowledge.delete_target_missing",
                    target_id=arguments.target_knowledge_item_id),
                repairable_fields=("target_knowledge_item_id",),
                immutable_fields=("action_id", "reason"),
                required_repair=self._prompts.get("conversation.knowledge.delete_target_stop").template,
            ), None
        return None, arguments

    def _project_action_feedback(self, feedback, actions, *, knowledge_inventory_observed=False):
        if feedback.reason_code == "target_not_observed_in_scope":
            declared = {action.target_name: action.name for action in actions if action.kind == "tool"}
            inventory = declared.get(_LIST_PERSONAL_KNOWLEDGE_CAPABILITY)
            delete = declared.get(_PREPARE_KNOWLEDGE_DELETE_CAPABILITY)
            if delete is not None and knowledge_inventory_observed:
                return feedback.model_copy(update={"required_repair": self._prompts.render(
                    "conversation.knowledge.delete_target_reuse", delete_tool=delete)})
            if inventory is not None and delete is not None:
                return feedback.model_copy(update={"required_repair": self._prompts.render(
                    "conversation.knowledge.delete_target_retry", inventory_tool=inventory, delete_tool=delete)})
        return feedback

    def _invalid_special_arguments(self, action, error):
        return DecisionFeedback(
            action_id=action.action_id,
            reason_code="invalid_arguments",
            message=str(error),
            repairable_fields=("arguments",),
            immutable_fields=("action_id", "tool_name"),
            required_repair=self._prompts.get("conversation.knowledge.arguments_repair").template,
        )

    def _application_operation_feedback(self, action, error):
        return DecisionFeedback(
            action_id=action.action_id,
            reason_code="application_operation_rejected",
            message=str(error),
            immutable_fields=("action_id", "tool_name"),
            required_repair=self._prompts.get("conversation.knowledge.operation_repair").template,
            disposition="fail_closed",
        )

    def _knowledge_delete_turn_view(self, conversation_id, run_ref, operation):
        messages = {
            "awaiting_confirmation": self._prompts.render('conversation.service.knowledge_delete_confirmation'),
            "rejected": self._prompts.render('conversation.service.knowledge_delete_rejected'),
            "executed": self._prompts.render('conversation.service.knowledge_deleted'),
        }
        return ConversationTurnView(
            interaction_run_ref=run_ref,
            conversation_id=conversation_id,
            disposition=(
                "confirmation_required"
                if operation.status == "awaiting_confirmation"
                else "answer"
            ),
            message=ConversationMessage(
                role="assistant", content=messages[operation.status]
            ),
            pending_confirmation=(
                KnowledgeDeleteConfirmation(operation=operation)
                if operation.status == "awaiting_confirmation"
                else None
            ),
        )

    @staticmethod
    def _goal_requires_plan_review(trace: InteractionTrace) -> bool:
        first = trace.first_goal_operation
        delivery = first.patch.delivery if first is not None and first.patch is not None else None
        return delivery is not None and delivery.mode == "review_plan"

    def _plan_goal_item_ids(self, run_ref: str) -> frozenset[str]:
        trace = self._journal.get(run_ref)
        goal = current_analysis_goal(trace, self._task_turns(run_ref))
        return frozenset(item.item_id for item in goal.goal.active_items(run_ref)) if goal else frozenset()

    def _record_model_usage(self, usage, response, *, model_turn=False, run_ref=None):
        if response.response_records:
            if not model_turn:
                return usage
            if run_ref is None:
                raise ConversationOperationConflict("主模型决策计数缺少运行绑定")
            invocation_id = response.response_records[-1].invocation_id
            for count, record in enumerate(self._journal.get(run_ref).responded_steps, start=1):
                if record.invocation_id == invocation_id:
                    return usage.model_copy(update={"model_turns": max(usage.model_turns, count)})
            raise ConversationOperationConflict("主模型决策计数缺少已存响应")
        total_tokens = response.total_tokens
        if total_tokens is None:
            total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
        complete = (
            usage.provider_usage_complete
            and usage.model_calls is not None
            and usage.input_tokens is not None
            and usage.output_tokens is not None
            and response.input_tokens is not None
            and response.output_tokens is not None
        )
        return usage.model_copy(update={
            "provider_usage_complete": complete,
            "model_calls": usage.model_calls + 1 if complete else None,
            "model_turns": usage.model_turns + int(model_turn),
            "input_tokens": (
                usage.input_tokens + response.input_tokens
                if complete
                else None
            ),
            "output_tokens": (
                usage.output_tokens + response.output_tokens
                if complete
                else None
            ),
            "total_tokens": usage.total_tokens + total_tokens,
        })

    @staticmethod
    def _has_failed_or_unknown_action_observation(inputs) -> bool:
        return any(
            isinstance(item, ActionObservation)
            and item.kind == "tool_result"
            and (item.status in {"failed", "unknown"} or item.payload.get("ok") is False)
            for item in inputs
        )

    @staticmethod
    def _offloaded_resources(
        inputs,
    ) -> dict[str, tuple[str, str | None, dict[str, Any]]]:
        """Map saved artifacts to their producing requests for duplicate-fetch admission."""

        offloaded: dict[
            str,
            tuple[str, str | None, dict[str, Any]],
        ] = {}
        for item in inputs:
            if not isinstance(item, ActionObservation):
                continue
            if item.capability_id in FILE_READ_CAPABILITIES:
                continue
            if item.status != "succeeded":
                continue
            reference = item.payload.get("retrieval", {})
            if isinstance(reference, dict) and "resource_ref" in reference:
                resource_ref = reference["resource_ref"]
                if not isinstance(resource_ref, dict):
                    continue
                resource_id = str(resource_ref.get("resource_id", ""))
                if resource_id:
                    offloaded[resource_id] = (
                        item.capability_id,
                        item.execution_request_digest,
                        resource_ref,
                    )
        return offloaded

    def _goal_verification_context(self, run_ref, *, draft, goal_call_id, task: GoalTaskCandidate, task_id,
                                   clarification_resolution: GoalClarificationReview | None,
                                   task_review: GoalTaskReview | None):
        trace = self._journal.get(run_ref)
        context = build_verification_context(trace=trace, history=task.previous, draft=draft,
            kind="goal", goal_call_id=goal_call_id, clarification_resolution=clarification_resolution,
            task_review=task_review)
        if self._history is None:
            return context
        summary_prompt = self._prompts.get("conversation.goal_verification_history_compaction")
        checkpoint = verification_checkpoint(trace, task.previous, kind="goal",
            prompt_version=summary_prompt.version, task_id=task_id, context=context)
        criteria = task_verification_criteria("goal", prompts=self._prompts)
        while True:
            projected = self._history.project_verification(run_ref, context, checkpoint, previous_turns=task.previous)
            size = verification_input_size(projected, criteria, prompts=self._prompts)
            if self._verification_input_budget is None or size <= self._verification_input_budget:
                return projected
            try:
                checkpoint = self._history.compact_verification(run_ref, context, checkpoint,
                    previous_turns=task.previous, task_id=task_id)
            except (ValueError, OSError, ConversationOperationConflict) as error:
                raise ConversationFailure(self._prompts.render('conversation.service.history_summary_inactive', failure=error),
                    reason_code="context_capacity_exceeded", failure_stage="model_capacity") from error

    def _verify_goal_maintenance(self, invocation, *, run_ref, owner, source_platform):
        trace = self._journal.get(run_ref)
        branch = prior_analysis_turns(trace, self._journal.task_traces(trace))
        if self._goals is None:
            raise ConversationOperationConflict("Goal maintenance requires the installed Goal module")
        prepared = self._goals.prepare_maintenance(invocation, trace=trace, previous=branch, prompts=self._prompts)
        if isinstance(prepared, DecisionFeedback):
            return prepared, None, trace.usage, None
        task, proposal = prepared
        if not trace.feature_flags_binding.goal_verification:
            operation = admit_goal_maintenance(invocation, trace=trace, current=task.current,
                verification_ref=None, candidate=proposal)
            return operation, None, trace.usage, task
        draft = proposal.goal.verification_text(run_ref, proposal.execution_control, invocation.arguments.delivery)
        current_turns = task.history.by_task.get(task.history.current_id, ())
        task_review = (GoalTaskReview(action=task.action,
            evidence=invocation.arguments.task.evidence if invocation.arguments.task is not None else None,
            current_task_request=current_turns[0].messages[-1].content if current_turns else None)
            if trace.first_goal_operation is None else None)
        context = self._goal_verification_context(run_ref, draft=draft, goal_call_id=invocation.call_id,
            task=task, task_id=proposal.goal.goal_id, task_review=task_review,
            clarification_resolution=proposal.clarification_resolution)
        arguments = {"draft": draft,
            "success_criteria": [item.criterion for item in task_verification_criteria("goal", prompts=self._prompts)],
            "task_context": context.model_dump(mode="json")}
        action_id = goal_submission_id(trace, invocation.call_id, trace.current_step_no)
        result, usage = self._invoke_verifier(arguments, action_id=action_id, run_ref=run_ref,
            owner=owner, source_platform=source_platform, verification_inputs=current_question_inputs(trace))
        receipts = observed_receipts((result.interaction_input,), capability_names=frozenset({_VERIFICATION_CAPABILITY}))
        if len(receipts) != 1 or receipts[0].checked_kind != "goal" or receipts[0].verified_draft != draft:
            raise ConversationFailure(self._prompts.render('conversation.service.goal_verification_unavailable'),
                reason_code="dependency_unavailable", failure_stage="application_dependency")
        receipt = receipts[0]
        latest = self._journal.get(run_ref)
        latest_branch = prior_analysis_turns(latest, self._journal.task_traces(latest))
        latest_task = select_goal_task(invocation.arguments, latest, latest_branch)
        if (latest_task.current != task.current or latest_task.previous != task.previous
                or goal_input_digest(latest) != goal_input_digest(trace)):
            raise ConversationOperationConflict("goal source changed during verification")
        if receipt.verdict != "passed":
            feedback = goal_feedback(invocation.call_id, "goal_verification_failed", {
                "verdict": receipt.verdict, "criterion_results": [item.model_dump(mode="json") for item in receipt.criterion_results],
                "revision_feedback": receipt.revision_feedback}, action_name=SUBMIT_GOAL_PATCH, prompts=self._prompts)
            return feedback, result, usage, task
        operation = admit_goal_maintenance(invocation, trace=latest, current=task.current,
            verification_ref=HistoryItemKey(kind="tool_result", action_id=action_id),
            candidate=proposal)
        return operation, result, usage, task

    def _verify_before_send(
        self,
        decision,
        *,
        verification_inputs,
        run_ref,
        owner,
        source_platform,
        usage,
        attempt,
    ):
        """Verify a review answer before it can be sent, and carry back the receipt.

        The runtime invokes the verifier itself, so "verification happened" is a
        property of this code path rather than of the model's cooperation. On a
        passed verdict the sent text is taken from the receipt, which keeps the
        emitted bytes identical to the judged bytes without asking a model to
        copy them.

        Returns ``(final_message | None, action_result, usage)``. A failed
        verification remains visible to the next agent turn as the typed receipt,
        but it does not choose that turn's action availability.
        """
        action_id = f"runtime-verify-{attempt}"
        trace = self._journal.get(run_ref)
        history = self._task_turns(run_ref)
        goal = current_analysis_goal(trace, history)
        try:
            workspace_facts = tuple(fact for item in verification_inputs
                if isinstance(item, ActionObservation) and item.capability_id == WORKSPACE_CHANGES
                for fact in item.payload.get("execution_facts", ()))
            source_observations = select_visible_successful_observations(
                verification_inputs, excluded_capability_ids=frozenset({
                    "bash", _VERIFICATION_CAPABILITY, WORKSPACE_CHANGES,
                }))
            task_context, through = answer_goal_context(goal, decision.message, (*history, trace),
                source_observations=tuple(
                    render_interaction_input(item, prompts=self._prompts)
                    for item in project_interaction_inputs(source_observations)),
                workspace_execution_facts=workspace_facts,
                prompts=self._prompts, measure_capacity=self._model_client.measure_capacity)
        except ModelCapacityRefused as error:
            raise self._capacity_failure(error) from error
        scope = ExecutionScope(principal=trace.principal, execution_id=run_ref, thread_id=trace.conversation_id)
        self._advance_goal_compliance_history(scope, trace, through)
        arguments = {
            "draft": decision.message,
            "success_criteria": [item.criterion for item in task_verification_criteria("answer", prompts=self._prompts)],
            "task_context": task_context.model_dump(mode="json", exclude_none=True),
        }
        result, usage = self._invoke_verifier(arguments, action_id=action_id, run_ref=run_ref,
            owner=owner, source_platform=source_platform,
            verification_inputs=current_question_inputs(self._journal.get(run_ref)))
        receipts = observed_receipts(
            (result.interaction_input,),
            capability_names=frozenset({_VERIFICATION_CAPABILITY}),
        )
        receipt = receipts[-1] if receipts else None
        verdict: VerificationVerdict | None = (
            receipt.verdict if receipt is not None else None
        )
        passed = receipt if verdict == "passed" and receipt.checked_kind == "answer" else None
        if passed is None:
            if result.interaction_input in verification_inputs:
                _, result = self._reuse_verification(result.interaction_input, decision=decision, action_id=action_id)
            return None, result, usage
        if decision.message != passed.verified_draft:
            raise ValueError("verified receipt must bind the submitted answer")
        return (decision, result, usage)

    def _invoke_verifier(self, arguments, *, action_id, run_ref, owner, source_platform, verification_inputs):
        expected = canonical_digest({"tool_name": _VERIFICATION_CAPABILITY, "arguments": arguments})
        previous = next((item for item in reversed(verification_inputs) if isinstance(item, ActionObservation)
            and item.capability_id == _VERIFICATION_CAPABILITY and item.execution_request_digest == expected), None)
        trace = self._journal.get(run_ref)
        if previous is not None:
            return _ActionResult(previous.action_id, previous), trace.usage
        if self._budget.counted_tool_quota_exhausted(trace.usage):
            raise ConversationFailure(self._prompts.render('conversation.service.verification_budget_exhausted'),
                reason_code="dependency_unavailable", failure_stage="application_budget")
        scope = ExecutionScope(principal=trace.principal, execution_id=run_ref,
            thread_id=trace.conversation_id, task_id=action_id)
        result = self._tool_port.invoke_workflow(_VERIFICATION_CAPABILITY, arguments,
            execution_scope=scope, tool_call_id=action_id, source_platform=source_platform)
        # Canonical verification receipts stay complete; context projection owns display budgeting.
        payload = result
        if not result.get("ok") and arguments.get("task_context") is None:
            payload = self._fit_observation_payload(
                result, capability_id=_VERIFICATION_CAPABILITY, execution_scope=scope,
            )
        observation = ActionObservation(kind="tool_result", action_id=action_id,
            capability_id=_VERIFICATION_CAPABILITY, status="succeeded" if result.get("ok") else "failed",
            execution_request_digest=expected, payload=payload)
        usage = self._journal.get(run_ref).usage
        return _ActionResult(action_id, observation), usage.model_copy(update={"tool_calls": usage.tool_calls + 1})

    def generate_verification(
        self, scope: ExecutionScope, request: StructuredModelRequest,
    ) -> StructuredModelResponse:
        """Bind each verifier call to the canonical run admission and usage owner."""
        trace = self._journal.get(scope.execution_id)
        if trace is None or scope.thread_id != trace.conversation_id:
            raise PermissionError("核验缺少当前对话运行绑定")
        self._require_trace_scope(trace, scope.principal, action="conversation_verification")
        try:
            response = self._generate_model(
                request, run_ref=scope.execution_id, usage=trace.usage,
            )
        except ConversationFailure as error:
            def record_failure(latest, failure=error):
                usage = latest.usage
                for observed in (*failure.prior_responses,
                                 *((failure.response,) if failure.response is not None else ())):
                    usage = self._record_model_usage(usage, observed)
                if failure.failure_stage == "provider_request" and not failure.provider_response_complete:
                    usage = usage.model_copy(update={
                        "provider_usage_complete": False, "model_calls": None,
                        "input_tokens": None, "output_tokens": None,
                    })
                return latest.model_copy(update={"revision": latest.revision + 1, "usage": usage})
            self._journal.update(scope, record_failure)
            # This owner has committed the failure. Do not charge it again if propagated.
            error.response, error.prior_responses = None, ()
            raise
        self._journal.update(scope, lambda latest: latest.model_copy(update={
            "revision": latest.revision + 1,
            "usage": self._record_model_usage(latest.usage, response),
        }))
        return response

    @staticmethod
    def _reuse_verification(
        previous: ActionObservation, *, decision: FinalMessage, action_id: str,
    ) -> tuple[FinalMessage | None, _ActionResult]:
        receipts = observed_receipts((previous,), capability_names=frozenset({_VERIFICATION_CAPABILITY}))
        receipt = receipts[-1] if receipts else None
        if receipt is None:
            return None, _ActionResult(previous.action_id, previous)
        if receipt.checked_kind != "answer" or decision.message != receipt.verified_draft:
            raise ValueError("verified receipt must bind the submitted answer")
        if receipt.verdict == "passed":
            return decision, _ActionResult(previous.action_id, previous)
        # A cache hit is a new rejection of this proposal, not a new verdict.
        # Keep it after the current submission so recovery returns to the model.
        feedback = DecisionFeedback(action_id=action_id, action_name="final_message",
            reason_code="cached_verification_failed",
            message=receipt.model_dump_json(include={"receipt_id", "verdict", "criterion_results"}),
            required_repair=receipt.revision_feedback)
        return None, _ActionResult(action_id, feedback)

    @staticmethod
    def _answer_submission(
        decision: FinalMessage, *, run_ref: str, principal: AuthenticatedPrincipal, turn: int,
    ) -> SubmittedFinal:
        return SubmittedFinal(
            action_id=f"final-{turn}",
            resource_ref=ResourceRef(resource_id=f"{run_ref}:final", resource_type="conversation_final",
                                     owner=principal, revision=turn),
            final=decision,
        )

    @staticmethod
    def _pending_final_candidate(inputs, trace):
        index = next((i for i in range(len(inputs) - 1, -1, -1) if isinstance(inputs[i], SubmittedFinal)), None)
        if index is None:
            return None
        if trace.steering and trace.steering[-1].after_step >= inputs[index].resource_ref.revision:
            return None
        later = inputs[index + 1:]
        if any(isinstance(item, DecisionFeedback) for item in later):
            return None
        if any(isinstance(item, ActionObservation) and item.capability_id != _VERIFICATION_CAPABILITY for item in later):
            return None
        for item in later:
            if isinstance(item, ActionObservation) and item.capability_id == _VERIFICATION_CAPABILITY:
                receipts = observed_receipts((item,), capability_names=frozenset({_VERIFICATION_CAPABILITY}))
                if not receipts or receipts[-1].checked_kind != "answer" or receipts[-1].verdict != "passed":
                    return None
        return inputs[index].final

    def _decide(self, **arguments):
        run_ref = arguments["run_ref"]
        for attempt in range(3):
            request, composition, sources = self._build_decision_request(**arguments)
            if any(not record.consumed and record.operation == request.operation
                   and record.request.consumer_key == request.consumer_key for record in sources[-1].model_decisions):
                return self._decide_once(request, composition, run_ref=run_ref, usage=arguments["usage"],
                                         capabilities=arguments["capabilities"])
            capacity, refusal = self._measure_decision_capacity(request)
            pressure = capacity is not None and (
                history_input_pressure(capacity, sources) >= history_pressure_limit(capacity))
            if pressure and attempt == 0 and self._history is not None and capacity is not None:
                boundaries = propose_tool_pruning(sources)
                if boundaries is not None:
                    pruned, pruned_composition, pruned_sources = self._build_decision_request(
                        **arguments, tool_pruning_candidate=boundaries,
                    )
                    if pruned.model_history != request.model_history:
                        reduced, reduced_refusal = self._measure_decision_capacity(pruned)
                        if reduced is not None and reduced.estimated_input_tokens < capacity.estimated_input_tokens:
                            self._history.activate_tool_pruning(sources[-1], boundaries)
                            request, composition, sources = pruned, pruned_composition, pruned_sources
                            capacity, refusal = reduced, reduced_refusal
                            pressure = history_input_pressure(capacity, sources) >= history_pressure_limit(capacity)
            if (pressure and attempt < 2 and self._history is not None
                    and self._history.has_safe_prefix(run_ref)):
                trigger = refusal or ModelCapacityRefused(request.operation, "context_capacity_exceeded", check=capacity)
                self._compact_after_capacity(self._capacity_failure(trigger), run_ref,
                    verify_reduction=lambda candidate: self._require_history_reduction(
                        candidate, arguments, capacity.estimated_input_tokens))
                arguments["usage"] = self._journal.get(run_ref).usage
                arguments["capabilities"] = self._model_visible_capabilities_for_turn(
                    self._effective_capabilities(
                        run_ref=run_ref, source_platform=arguments["source_platform"]
                    ), arguments["inputs"], run_ref=run_ref)
                continue
            if refusal is not None:
                raise self._capacity_failure(refusal)
            composition = composition.model_copy(update={"capacity": capacity})
            return self._decide_once(request, composition, run_ref=run_ref, usage=arguments["usage"],
                                     capabilities=arguments["capabilities"])
        raise ConversationOperationConflict("history compaction exhausted without a final request")

    def _measure_decision_capacity(self, request):
        try:
            return self._model_client.measure_capacity(request), None
        except ModelCapacityRefused as error:
            if error.reason_code != "context_capacity_exceeded" or error.check is None:
                raise self._capacity_failure(error) from error
            return error.check, error

    def _require_history_reduction(self, candidate: HistoryCompactionCheckpoint, arguments, original_input_tokens: int):
        revised = {**arguments, "usage": self._journal.get(arguments["run_ref"]).usage}
        revised["capabilities"] = self._model_visible_capabilities_for_turn(
            self._effective_capabilities(
                run_ref=arguments["run_ref"], source_platform=arguments["source_platform"]
            ), arguments["inputs"],
            run_ref=arguments["run_ref"])
        request, _, _ = self._build_decision_request(**revised, candidate=candidate)
        try:
            capacity = self._model_client.measure_capacity(request)
        except ModelCapacityRefused as error:
            if error.reason_code != "context_capacity_exceeded" or error.check is None:
                raise
            capacity = error.check
        if capacity is None or capacity.estimated_input_tokens >= original_input_tokens:
            raise ValueError(self._prompts.render("conversation.history.summary_incomplete"))

    def _build_decision_request(
        self,
        *,
        run_ref,
        messages,
        source_platform,
        capabilities,
        inputs,
        usage,
        turn_index,
        working_plan,
        candidate: HistoryCompactionCheckpoint | None = None,
        tool_pruning_candidate: tuple[HistoryToolPruningBoundary, ...] | None = None,
    ):
        """Build the same pure projection for candidate checks and actual model calls."""
        decision_trace = self._journal.get(run_ref)
        prior_turns = prior_analysis_turns(decision_trace, self._journal.task_traces(decision_trace))
        goal_step = self._goals.step(decision_trace, prior_turns) if self._goals is not None else None
        previous_turns = goal_step.previous if goal_step is not None else prior_turns
        current_goal = goal_step.current if goal_step is not None else None
        goal_required = goal_step is not None and goal_step.required
        message_indices = task_message_indices(decision_trace, previous_turns)
        switch_turn = task_switch_turn(decision_trace)
        first_after_switch = next((record.input_start for record in decision_trace.responded_steps
            if record.step_no > switch_turn), len(inputs))
        inputs = self._task_inputs(previous_turns, tuple(
            item for index, item in enumerate(inputs)
            if not (switch_turn and index < first_after_switch and isinstance(item, SubmittedFinal))
        ))
        control = current_goal.execution_control if current_goal is not None else None
        if control is not None and control.mode != "running":
            capabilities = EffectiveCapabilities(tools=tuple(
                tool for tool in capabilities.tools if control.mode == "read_only" and tool.read_only))
        if self._budget.tool_calls_exhausted(usage):
            capabilities = capabilities.model_copy(update={"tools": ()})
        action_definitions = build_model_action_definitions(capabilities,
            experiment_run=decision_trace.deployment_digest is not None,
            task_workspace=self._uses_task_bash_workspace(decision_trace),
            bind_goal_items=goal_step is not None,
            answer_actions=self._answer_result.action_definitions(), prompts=self._prompts)
        goal_tools_available = goal_step is not None and not self._budget.counted_tool_quota_exhausted(usage)
        if goal_step is not None:
            action_definitions = goal_step.actions(action_definitions, available=goal_tools_available, prompts=self._prompts)
        test_mode = self._answer_result.config.test_mode
        action_definitions = project_test_mode_tools(action_definitions, enabled=test_mode)
        visible_capabilities = capabilities
        if goal_required:
            draft_tools = {item.target_name for item in action_definitions if item.kind == "tool"}
            visible_capabilities = EffectiveCapabilities(tools=tuple(
                tool for tool in capabilities.tools if tool.name in draft_tools))
        capability_projection = model_visible_capability_policy(visible_capabilities,
            definitions=action_definitions, prompts=self._prompts)
        prompt_name = "conversation.action"
        prompt_version = self._prompts.get(prompt_name).version
        system_content = build_interaction_system_prompt(
            capabilities,
            capability_projection=capability_projection,
            explicit_research_entry=decision_trace.deployment_digest is not None,
            answer_result=self._answer_result,
            prompts=self._prompts,
        )
        task_prompt = self._prompts.get("conversation.analysis.task" if goal_step is not None
                                       else "conversation.analysis.direct_task")
        system_content += task_prompt.template
        prompt_version += "+" + task_prompt.version
        if goal_tools_available:
            prompt_version += "+" + self._prompts.get("conversation.goal.description").version
        if test_mode:
            note = self._prompts.get("conversation.test_mode")
            system_content += "\n\n" + note.template
            prompt_version += "+" + note.version
        visible_messages = [{"role": "system", "content": system_content}]
        visible_messages.extend(messages[index].model_dump(mode="json") for index in message_indices)
        if self._history is not None:
            visible_messages = self._history.project_messages(decision_trace, visible_messages, candidate)
        latest_submission_index = next((index for index in range(len(inputs) - 1, -1, -1)
                                        if isinstance(inputs[index], SubmittedFinal)), None)
        knowledge_inventory_observed = self._has_knowledge_inventory(inputs)
        decision_inputs = tuple(
            self._project_action_feedback(item, action_definitions,
                knowledge_inventory_observed=knowledge_inventory_observed)
            if isinstance(item, DecisionFeedback) else item
            for index, item in enumerate(inputs)
            if not isinstance(item, SubmittedFinal) or index == latest_submission_index
        )
        visible_inputs = project_interaction_inputs(materialize_interaction_inputs(
            decision_inputs, actions=action_definitions, prompts=self._prompts))
        history_recovery = ""
        if self._history is not None:
            projection = self._history.project(decision_trace, visible_inputs,
                candidate=candidate, actions=action_definitions)
            visible_inputs, history_recovery = projection.inputs, projection.recovery
        sources = (*previous_turns, decision_trace)
        tool_pruning = (active_tool_pruning(sources) if tool_pruning_candidate is None else
                        {boundary.run_ref: boundary.through_step for boundary in tool_pruning_candidate})
        model_history, unpaired, current_plan_visible = project_conversation_history(
            decision_trace, previous_turns, visible_inputs,
            prompts=self._prompts, candidate=candidate, working_plan=working_plan,
            tool_pruning=tool_pruning)
        visible_messages, model_history = omit_replayed_delivered_answers(
            decision_trace, previous_turns, visible_messages, model_history)
        conversation_content = visible_messages[1:]
        if history_recovery:
            prompt_version += "+" + self._prompts.get("conversation.history.result_locations").version
            visible_messages.append({"role": "system", "content": history_recovery})
        model_history = (*model_history, *(ModelRuntimeFeedback(feedback=render_interaction_input(item, prompts=self._prompts))
            for item in unpaired if not isinstance(item.observation, ArtifactSourceInput)))
        last_main = next(iter(reversed(decision_trace.responded_steps)), None)
        if (last_main is not None and last_main.blocked_by is not None and last_main.response_refs
                and last_main.step_no > task_switch_turn(decision_trace)
                and goal_pending_rejection(decision_trace, last_main) is None
                and not any(isinstance(exchange, ModelToolExchange)
                            and exchange.assistant == last_main.assistant for exchange in model_history)):
            visible_messages.append({"role": "system", "content": self._prompts.get("conversation.rejected_output_preface").template
                + self._journal.model_response_records(run_ref, last_main)[-1].payload_json})
        if goal_step is not None:
            for version, content in goal_step.context(model_history, tools_available=goal_tools_available,
                                                      prompts=self._prompts):
                visible_messages.append({"role": "user", "content": content})
                prompt_version += "+" + version
        step_sections: list[str] = []
        if working_plan is not None and not goal_required and not current_plan_visible:
            step_sections.append(render_working_plan_recovery(working_plan, prompts=self._prompts))
            prompt_version += "+" + self._prompts.get("conversation.plan.recovery").version
        if self._skill_catalog is not None and any(
            action.kind == "tool" and action.target_name == LOAD_SKILL_CAPABILITY
            for action in action_definitions
        ):
            prompt = self._prompts.get("skills.catalog")
            summaries = render_skill_summaries(
                self._skill_catalog.visible(decision_trace.principal, decision_trace.conversation_id,
                                            source_platform=source_platform)
            )
            step_sections.append(prompt.render(catalog=summaries))
            prompt_version += "+" + prompt.version
        if self._skill_catalog is not None:
            prompt_version += "+" + self._prompts.get("skills.repeat_notice").version
        if self._skill_scripts is not None:
            prompt_version += "+" + self._prompts.get("skills.resource_base").version
        step_context = "\n\n".join(step_sections)
        if step_context:
            # End-position exchanges still precede the new step message.
            step_position = len(visible_messages)
            model_history = tuple(
                exchange.model_copy(update={"before_message_index": step_position})
                if exchange.before_message_index is None else exchange
                for exchange in model_history
            )
            visible_messages.append({"role": "user", "content": step_context})
        request = StructuredModelRequest(
        operation="agent_interaction_turn",
        consumer_key="conversation:decision",
        version=prompt_version,
        messages=visible_messages,
        model_history=model_history,
        output_type=BaseModel,
        context_projection_ref=sealed_context_projection_ref(
            purpose="agent_interaction_turn",
            messages=visible_messages,
            model_history=model_history,
        ),
        temperature=0,
        max_tokens=32_768,
        kind="tool_calling",
        action_definitions=action_definitions,
        max_output_repairs=0,
        metadata={"component": "conversation_interaction_loop", "prompt_name": prompt_name},
        )
        action_definition_chars = len(
            json.dumps(
                [item.model_dump(mode="json") for item in action_definitions],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        composition = TurnContextComposition(
            turn_index=turn_index,
            capability_projection_chars=len(capability_projection),
            model_action_definition_chars=action_definition_chars,
            # By subtraction, so the two segments are disjoint by construction and
            # always sum to the prompt that was sent.
            system_prompt_other_chars=len(system_content) - len(capability_projection),
            conversation_messages_chars=sum(
                len(item["content"]) for item in conversation_content
            ),
            typed_inputs_chars=len(history_recovery) + len(step_context),
            native_history_chars=sum(
                sum(map(len, exchange.context_before)) +
                (len(exchange.feedback) if isinstance(exchange, ModelRuntimeFeedback) else
                 len(exchange.user_text) if isinstance(exchange, ModelUserHistoryMessage) else
                 len(json.dumps(exchange.assistant.payload, ensure_ascii=False))
                 + sum(len(result.content) for result in exchange.results)
                 + sum(map(len, exchange.runtime_feedback)))
                for exchange in model_history),
            prompt_version=self._prompts.get(prompt_name).version,
            input_tokens=None,
        )
        return request, composition, sources

    def _decide_once(self, request, composition, *, run_ref, usage, capabilities: EffectiveCapabilities):
        provider_protocol_error = None
        try:
            response = self._generate_model(request, run_ref=run_ref, usage=usage)
        except StructuredOutputFailure as error:
            if error.response is None:
                raise
            response = error.response
            provider_protocol_error = error
        response_invocation_id = response.response_records[-1].invocation_id if response.response_records else None
        responded_steps = self._journal.get(run_ref).responded_steps
        response_record = next((record for record in reversed(responded_steps)
            if record.invocation_id == response_invocation_id), None)
        composition = composition.model_copy(update={
            "turn_index": responded_steps.index(response_record) if response_record is not None else composition.turn_index,
            "input_tokens": response.input_tokens})
        bound_request = self._journal.model_request(run_ref, response_record) if response_record is not None else request
        try:
            if provider_protocol_error is not None:
                raise provider_protocol_error
            assistant = response.assistant_message
            has_calls = bool(response.action_invocations or (assistant is not None and assistant.call_ids))
            if has_calls:
                decision = decode_model_action_invocations(response.action_invocations, bound_request.action_definitions,
                    prompts=self._prompts,
                    reveal_invalid_action_field_names=self._action_diagnostics_reveal_field_names)
            else:
                try:
                    decision = self._answer_result.decode_assistant_message(assistant)
                except ValueError as error:
                    return None, response, composition, DecisionFeedback(
                        action_id="assistant_message", reason_code="answer_result_payload_invalid",
                        message=str(error), repairable_fields=("content",),
                        required_repair=self._prompts.render('conversation.service.answer_result_repair'))
            if isinstance(decision, AnswerResultInvocation):
                try:
                    decision = self._answer_result.decode_operation(decision)
                except ValueError as error:
                    return None, response, composition, DecisionFeedback(
                        action_id=response.action_invocations[0].call_id, reason_code="answer_result_payload_invalid",
                        message=str(error), repairable_fields=("arguments",),
                        required_repair=self._prompts.render('conversation.service.final_operation_repair'))
        except StructuredOutputFailure as exc:
            log_event(
                _LOGGER,
                logging.WARNING,
                "conversation.model_action_repair",
                component="conversation_interaction_loop",
                failure_stage="application_action_decode",
                operation=exc.operation,
                reason_code=exc.reason_code,
                action_name=exc.action_name,
                action_kind=exc.action_kind,
                action_field_paths=exc.field_paths or None,
                action_error_types=exc.error_types or None,
            )
            if provider_protocol_error is None:
                partially_decoded = partially_decode_tool_batch(
                    exc, response.action_invocations, bound_request.action_definitions, capabilities,
                    prompts=self._prompts,
                    reveal_invalid_action_field_names=self._action_diagnostics_reveal_field_names,
                )
                if partially_decoded is not None:
                    return partially_decoded, response, composition, None
            return None, response, composition, provider_action_feedback(
                exc, response.action_invocations, prompts=self._prompts,
                available_actions=tuple(action.name for action in bound_request.action_definitions))
        return decision, response, composition, None

    def _admit_research_model_call(self, run_ref, usage):
        trace = self._journal.get(run_ref)
        rejection = self._budget.model_send_rejection(trace, usage)
        if rejection is not None:
            message = ('conversation.service.model_deadline_exceeded' if rejection == "run_deadline_exceeded"
                       else 'conversation.service.model_budget_exhausted')
            raise ConversationFailure(
                self._prompts.render(message), reason_code=rejection, failure_stage="application_budget",
            )

        if trace.bash_profile_digest is None:
            return
        if trace.bash_authorization_digest is not None:
            require_bash_authorization(trace, self._bash_authorization)
            if self._journal.execution_budget(trace).unsettled_action_ids:
                raise ConversationFailure(self._prompts.render('conversation.service.unsettled_execution'),
                    reason_code="dependency_unavailable", failure_stage="application_budget")
        if not self._experiment_model_capacity_valid:
            raise ConversationFailure(
                self._prompts.render('conversation.service.model_capacity_missing'),
                reason_code="capacity_profile_mismatch", failure_stage="model_capacity",
            )

    def _history_snapshot_refs(self, trace):
        return checkpoint_refs(trace, self._journal.task_traces(trace))

    def _recorded_history_snapshot_refs(self, trace):
        return recorded_checkpoint_refs(self._journal.task_traces(trace))

    def _compact_after_capacity(self, error, run_ref, *, verify_reduction=None):
        if (error.reason_code != "context_capacity_exceeded" or self._history is None):
            raise error
        for response in (*error.prior_responses, *((error.response,) if error.response else ())):
            self._history.record_response(run_ref, response)
        error.response, error.prior_responses = None, ()
        try:
            self._history.compact(run_ref, verify_reduction=verify_reduction)
        except ConversationFailure:
            raise
        except ModelCapacityRefused as failure:
            raise self._capacity_failure(failure) from failure
        except (ModelInvocationUnavailable, StructuredOutputFailure) as failure:
            raise self._model_failure(failure, message=self._prompts.render('conversation.service.history_summary_incomplete'),
                failure_stage=("provider_request" if isinstance(failure, ModelInvocationUnavailable)
                               else "provider_structured_decode"), component="conversation_history") from failure
        except (ValueError, OSError, ConversationOperationConflict) as failure:
            raise ConversationFailure(self._prompts.render('conversation.service.history_summary_inactive', failure=failure),
                reason_code="context_capacity_exceeded", failure_stage="model_capacity") from failure

    def _model_journal_call(self, operation, callback, *args, **kwargs):
        """Classify IO only at the explicit model-original Journal boundary."""
        try:
            return callback(*args, **kwargs)
        except (OSError, ConversationOperationConflict) as error:
            raise ConversationFailure(self._prompts.render('conversation.service.model_journal_incomplete'),
                reason_code="runtime_failure", failure_stage="application_persistence",
                operation=operation) from error

    def _generate_model(self, request, *, run_ref, usage):
        if request.consumer_key is None:
            request = replace(request, consumer_key=request.context_projection_ref)
        try:
            trace = self._journal.get(run_ref)
            scope = ExecutionScope(principal=trace.principal, execution_id=run_ref, thread_id=trace.conversation_id)
            request, continuation = self._model_journal_call(request.operation, self._journal.begin_model_invocation, scope, request)
            try:
                response = self._model_client.generate(request,
                    response_sink=lambda record: self._model_journal_call(request.operation, self._journal.record_model_response, scope, record),
                    continuation=continuation,
                    before_send=lambda: self._admit_research_model_call(run_ref, self._journal.get(run_ref).usage))
            except (ModelCapacityRefused, ModelInvocationUnavailable, StructuredOutputFailure) as failure:
                self._model_journal_call(request.operation, self._journal.finish_model_invocation, scope, continuation.invocation_id,
                    response=getattr(failure, "response", None), failure=failure)
                raise
            self._model_journal_call(request.operation, self._journal.finish_model_invocation, scope, continuation.invocation_id, response=response)
            return response
        except ModelCapacityRefused as error:
            raise self._capacity_failure(error) from error
        except ModelInvocationUnavailable as exc:
            if not exc.provider_response_complete:
                trace = self._journal.get(run_ref)
                self._journal.update(ExecutionScope(principal=trace.principal, execution_id=run_ref,
                    thread_id=trace.conversation_id), lambda latest: latest.model_copy(update={
                        "revision": latest.revision + 1, "usage": latest.usage.model_copy(update={
                            "provider_usage_complete": False, "model_calls": None,
                            "input_tokens": None, "output_tokens": None})}))
            raise self._model_failure(
                exc,
                message=self._prompts.render('conversation.service.model_request_failed'),
                failure_stage="provider_request",
                component=str(request.metadata.get("component", "conversation")),
            ) from exc
        except StructuredOutputFailure as exc:
            if request.kind == "tool_calling" and exc.response is not None:
                raise
            raise self._model_failure(
                exc,
                message=self._prompts.render('conversation.service.model_output_invalid'),
                failure_stage=(
                    "provider_action_decode"
                    if request.kind == "tool_calling"
                    else "provider_structured_decode"
                ),
                component=str(request.metadata.get("component", "conversation")),
            ) from exc
        except Exception as error:
            if getattr(error, "model_response_recording_failed", False):
                raise ConversationFailure(self._prompts.render('conversation.service.model_response_record_incomplete'),
                    reason_code="runtime_failure", failure_stage="application_persistence",
                    operation=request.operation) from error
            raise

    def _capacity_failure(self, error: ModelCapacityRefused) -> ConversationFailure:
        return ConversationFailure(
            self._prompts.render('conversation.service.model_capacity_refused'),
            reason_code=error.reason_code, failure_stage="model_capacity", operation=error.operation,
            retryable=False, response=error.response, prior_responses=error.prior_responses,
        )

    @staticmethod
    def _model_failure(
        error: ModelInvocationUnavailable | StructuredOutputFailure,
        *,
        message: str,
        failure_stage: ConversationFailureStage,
        component: str,
    ) -> ConversationFailure:
        if isinstance(error, ModelInvocationUnavailable):
            if error.provider_response_complete and error.response is None:
                raise ValueError("完整模型拒绝缺少实际响应，不能据此确认消费")
            unavailable = ConversationFailure(
                message,
                reason_code=error.category,
                failure_stage=failure_stage,
                operation=error.operation,
                provider_host=error.provider_host,
                provider_status_code=error.status_code,
                provider_diagnostics=error.diagnostics,
                provider_response_complete=error.provider_response_complete,
                retryable=error.retryable,
                response=error.response,
                prior_responses=error.prior_responses,
            )
        else:
            unavailable = ConversationFailure(
                message,
                reason_code=error.reason_code,
                failure_stage=failure_stage,
                operation=error.operation,
                action_name=error.action_name,
                action_kind=error.action_kind,
                field_paths=error.field_paths,
                error_types=error.error_types,
                provider_response_complete=bool(error.response is not None or error.prior_responses),
                response=error.response,
                prior_responses=error.prior_responses,
            )
        ConversationService._log_model_failure(
            unavailable,
            component=component,
        )
        return unavailable

    @staticmethod
    def _log_model_failure(
        error: ConversationFailure,
        *,
        component: str,
    ) -> None:
        log_event(
            _LOGGER,
            logging.WARNING,
            "conversation.model_failure",
            component=component,
            failure_stage=error.failure_stage,
            operation=error.operation,
            reason_code=error.reason_code,
            provider_host=error.provider_host,
            provider_status_code=error.provider_status_code,
            provider_response_complete=error.provider_response_complete or None,
            provider_diagnostics=(error.provider_diagnostics.model_dump(exclude_none=True)
                                  if error.provider_diagnostics else None),
            retryable=error.retryable,
            action_name=error.action_name,
            action_kind=error.action_kind,
            action_field_paths=error.field_paths or None,
            action_error_types=error.error_types or None,
        )

    def _effective_capabilities(self, *, run_ref: str, source_platform: str) -> EffectiveCapabilities:
        trace = self._journal.get(run_ref)
        principal = trace.principal
        tools: list[EffectiveToolCapability] = []
        if self._workspace_changes is not None and self._workspace_changes.visible(trace, source_platform):
            tools.append(EffectiveToolCapability(
                name=WORKSPACE_CHANGES,
                description=("提交一份有序的工作区变更清单供用户一次确认。"
                             "使用完整绝对路径，先列出必要的建目录，再列出移动。"
                             "确认后按序执行，回执会交回本次对话。请单独调用此动作。"),
                input_schema=WorkspaceChangeArguments.model_json_schema(),
                strict=False, read_only=False, planning_safe=False, safely_retryable=False,
            ))
        if self._knowledge_writer is not None:
            tools.append(
                EffectiveToolCapability(
                    name=_KNOWLEDGE_SAVE_CAPABILITY,
                    description=self._prompts.get("conversation.knowledge.save_description").template,
                    input_schema=KnowledgeSaveArguments.model_json_schema(),
                    read_only=False,
                    planning_safe=False,
                    safely_retryable=False,
                )
            )
        if self._artifact_port is not None:
            tools.append(
                EffectiveToolCapability(
                    name=READ_FILE_CAPABILITY,
                    description=self._prompts.get("conversation.read_file.description").template,
                    input_schema=ReadFileArguments.model_json_schema(),
                    read_only=True,
                    planning_safe=True,
                    safely_retryable=True,
                )
            )
        if self._artifact_port is not None and self._artifact_search is not None:
            tools.append(EffectiveToolCapability(
                name=GREP_FILE_CAPABILITY,
                description=self._prompts.get("conversation.grep_file.description").template,
                input_schema=GrepFileArguments.model_json_schema(),
                read_only=True, planning_safe=True, safely_retryable=True,
            ))
        if self._knowledge_reader is not None:
            tools.append(
                EffectiveToolCapability(
                    name=_SEARCH_PERSONAL_KNOWLEDGE_CAPABILITY,
                    description=self._prompts.get("conversation.knowledge.search_description").template,
                    input_schema=SearchPersonalKnowledgeArguments.model_json_schema(),
                    read_only=True,
                    planning_safe=True,
                    safely_retryable=True,
                )
            )
            tools.append(
                EffectiveToolCapability(
                    name=_LIST_PERSONAL_KNOWLEDGE_CAPABILITY,
                    description=self._prompts.get("conversation.knowledge.list_description").template,
                    input_schema=ListPersonalKnowledgeArguments.model_json_schema(),
                    read_only=True,
                    planning_safe=True,
                    safely_retryable=True,
                )
            )
        if self._knowledge_reader is not None and self._knowledge_lifecycle is not None:
            tools.append(
                EffectiveToolCapability(
                    name=_PREPARE_KNOWLEDGE_DELETE_CAPABILITY,
                    description=self._prompts.get("conversation.knowledge.delete_description").template,
                    input_schema=PrepareKnowledgeDeleteArguments.model_json_schema(),
                    read_only=False,
                    planning_safe=False,
                    safely_retryable=False,
                )
            )
        tools = [
            tool for tool in tools
            if self._tool_profile.enables(conversation_tool_group(tool.name))
        ]
        if self._tool_port is not None:
            for candidate in self._tool_port.list_interaction_tools(
                principal=principal, source_platform=source_platform,
            ):
                if not self._tool_profile.enables(conversation_tool_group(candidate.name)):
                    continue
                if candidate.name == LOAD_SKILL_CAPABILITY and (
                    self._skill_catalog is None or not self._skill_catalog.visible(
                        principal, trace.conversation_id, source_platform=source_platform,
                    )
                ):
                    continue
                if candidate.name == "retrieval_experiment" and (
                    run_ref is None or self._journal.get(run_ref).deployment_digest is None):
                    continue
                if candidate.name == "bash":
                    trace = self._journal.get(run_ref) if run_ref is not None else None
                    if trace is None or trace.bash_profile_digest is None:
                        continue
                    deployment = self._experiment_deployment
                    budget = self._journal.execution_budget(trace)
                    if trace.bash_authorization_digest is not None:
                        require_bash_authorization(trace, self._bash_authorization)
                    elif (deployment is None or trace.principal != deployment.authorized_principal
                          or trace.deployment_digest != deployment.deployment_digest):
                        continue
                    if not self._budget.execution_available(trace, budget):
                        continue
                if (
                    self._knowledge_reader is not None
                    and candidate.name in _RAW_NOTE_READ_CAPABILITIES
                ):
                    continue
                tools.append(
                    EffectiveToolCapability(
                        name=candidate.name,
                        description=candidate.description,
                        input_schema=candidate.input_schema,
                        strict=candidate.strict,
                        model_integer_string_fields=candidate.model_integer_string_fields,
                        read_only=candidate.read_only,
                        planning_safe=candidate.planning_safe,
                        safely_retryable=candidate.safely_retryable,
                        emits_verified_artifact=candidate.emits_verified_artifact,
                    )
                )
        agents = tuple(
            EffectiveAgentCapability(
                agent_id=profile.agent_id,
                description=profile.description,
                task_types=profile.task_types,
                allowed_operations=profile.allowed_operations,
            )
            for profile in (
                self._agent_port.interaction_profiles(principal=principal, source_platform=source_platform)
                if self._agent_port and self._tool_profile.enables("delegation") else ()
            )
        )
        return EffectiveCapabilities(
            tools=tuple(tools),
            agents=agents,
        )

    def _model_visible_capabilities_for_turn(
        self,
        capabilities: EffectiveCapabilities,
        inputs,
        *, run_ref: str | None = None,
    ) -> EffectiveCapabilities:
        """Remove actions whose interaction-scoped success contract is exhausted."""
        if run_ref is not None:
            trace = self._journal.get(run_ref)
            previous = selected_analysis_turns(trace, self._journal.task_traces(trace))
            inputs = self._task_inputs(previous, inputs)
        personal_search_succeeded = any(
            isinstance(item, ActionObservation)
            and item.capability_id == _SEARCH_PERSONAL_KNOWLEDGE_CAPABILITY
            and item.status == "succeeded"
            for item in inputs
        )
        return capabilities.model_copy(update={
            "tools": tuple(
                tool for tool in capabilities.tools
                if not (personal_search_succeeded and tool.name == _SEARCH_PERSONAL_KNOWLEDGE_CAPABILITY)
            ),
        })

    def _task_inputs(self, previous, inputs):
        inherited = [*self._journal.task_observations(previous)]
        known_refs = set(input_resource_refs(inputs))
        for source in previous:
            for item in source.inputs:
                if isinstance(item, ArtifactSourceInput) and item.resource.resource_ref not in known_refs:
                    inherited.append(item)
                    known_refs.add(item.resource.resource_ref)
        current_ids = {item.action_id for item in inputs if isinstance(item, ActionObservation)}
        return (*(item for item in inherited
                  if not isinstance(item, ActionObservation) or item.action_id not in current_ids), *inputs)

    def _task_turns(self, run_ref: str) -> tuple[InteractionTrace, ...]:
        trace = self._journal.get(run_ref)
        return selected_analysis_turns(trace, self._journal.task_traces(trace))

    @staticmethod
    def _unsafe_execution_started_before_plan(
        execution_order,
        inputs,
        capabilities: EffectiveCapabilities,
    ) -> bool:
        """Fail closed unless every executed action was planning-safe exploration."""
        if not execution_order:
            return False
        planning_safe_capabilities = {
            tool.name for tool in capabilities.tools if tool.planning_safe
        }
        planning_safe_capabilities.add(_VERIFICATION_CAPABILITY)
        observed_capability_by_action = {
            item.action_id: item.capability_id
            for item in inputs
            if isinstance(item, ActionObservation)
        }
        return any(
            observed_capability_by_action.get(action_id)
            not in planning_safe_capabilities
            for action_id in execution_order
        )

    @staticmethod
    def _actions_are_planning_safe(actions, capabilities) -> bool:
        planning_safe = {
            tool.name for tool in capabilities.tools if tool.planning_safe
        }
        return bool(actions) and all(
            isinstance(action, ToolCallProposal)
            and action.tool_name in planning_safe
            for action in actions
        )

    @staticmethod
    def _action_name(action: ToolCallProposal | AgentDelegationProposal) -> str:
        return (
            action.tool_name
            if isinstance(action, ToolCallProposal)
            else action.agent_id
        )

    @classmethod
    def _name_action_feedback(cls, feedback, actions):
        if feedback.action_name:
            return feedback
        action = next(
            (
                candidate
                for candidate in actions
                if candidate.action_id == feedback.action_id
            ),
            None,
        )
        if action is None:
            return feedback
        return feedback.model_copy(update={"action_name": cls._action_name(action)})

    def _uses_task_bash_workspace(self, trace: InteractionTrace) -> bool:
        return self._bash_input_scope(trace) == "task"

    def _bash_input_scope(self, trace: InteractionTrace) -> BashInputScope:
        authorization = self._bash_authorization
        if authorization is not None and trace.bash_authorization_digest == authorization.authorization_digest:
            if authorization.workspace is not None:
                return "attachments"
            if authorization.retain_task_workspace:
                return "task"
        return "history"

    def _review_bash_actions(self, actions, *, run_ref):
        trace = self._journal.get(run_ref)
        if (not trace.feature_flags_binding.answer_verification
                or not any(isinstance(action, ToolCallProposal) and action.tool_name == "bash" for action in actions)):
            return {}, {}, trace.usage
        history = selected_analysis_turns(trace, self._journal.task_traces(trace))
        goal = current_analysis_goal(trace, history)
        if goal is None:
            return {}, {}, trace.usage
        files = self._journal.bash_workspace_files(trace, input_scope=self._bash_input_scope(trace))
        batch = []
        denied = {}
        for action in actions:
            if not isinstance(action, ToolCallProposal) or action.tool_name != "bash":
                continue
            arguments = BashArgs.model_validate(action.arguments, context=self._prompts)
            scope = ExecutionScope(principal=trace.principal, execution_id=run_ref,
                                   thread_id=trace.conversation_id, task_id=action.action_id)
            batch.append(PendingBashReview.create(scope, arguments, files, goal, prompts=self._prompts))
        reviews = {item.binding.action_id: item for item in trace.action_goal_reviews}
        for item in batch:
            previous = reviews.get(item.binding.action_id)
            if previous is not None and previous.binding != item.binding:
                raise ConversationOperationConflict("cannot reuse an action goal judgment with a different binding")
        pending = tuple(item for item in batch if item.binding.action_id not in reviews)
        if pending:
            try:
                prepared = action_goal_request(goal, pending, (*history, trace), prompts=self._prompts,
                    artifacts=self._artifact_port, measure_capacity=self._model_client.measure_capacity)
            except ModelCapacityRefused as error:
                raise self._capacity_failure(error) from error
            scope = ExecutionScope(principal=trace.principal, execution_id=run_ref, thread_id=trace.conversation_id)
            self._advance_goal_compliance_history(scope, trace, prepared.compacted_through)
            response = self.generate_verification(scope, prepared.request)
            results = bind_action_goal_assessment(pending, response.value)
            self._journal.record_action_goal_reviews(scope, results)
            reviews.update((item.binding.action_id, item) for item in results)
        for item in batch:
            action_id = item.binding.action_id
            judgment = reviews[action_id].judgment
            if judgment.verdict == "conflict":
                denied[action_id] = DecisionFeedback(
                    action_id=action_id, action_name="bash", reason_code="action_goal_conflict",
                    message=self._prompts.render(f"{ACTION_GOAL_PROMPT}.rejection", tool_name="bash"),
                    repairable_fields=("arguments",), immutable_fields=("action_id", "tool_name"),
                    required_repair=judgment.feedback,
                )
        return {item.binding.action_id: item for item in batch}, denied, self._journal.get(run_ref).usage

    def _advance_goal_compliance_history(self, scope, trace, through):
        if through > trace.goal_compliance_history_compacted_through:
            self._journal.update(scope, lambda latest: latest.model_copy(update={
                "revision": latest.revision + 1,
                "goal_compliance_history_compacted_through": max(through, latest.goal_compliance_history_compacted_through),
            }))

    def _execute_actions(
        self,
        proposal,
        *,
        conversation_id,
        run_ref,
        principal,
        owner,
        source_platform,
        usage,
        committed_action_ids,
        committed_inputs,
        plan_step_id,
        partially_decoded: PartiallyDecodedToolBatch | None = None,
        replaying_model_response: bool = False,
    ):
        admitted = [
            self._admit(
                action,
                run_ref=run_ref,
                committed_action_ids=committed_action_ids,
                committed_inputs=committed_inputs,
            )
            for action in proposal.actions
        ]
        first_safe_request: dict[str, str] = {}
        for index, (action, feedback) in enumerate(
            zip(proposal.actions, admitted, strict=True)
        ):
            if (
                feedback is not None
                or not isinstance(action, ToolCallProposal)
                or action.tool_name == LOAD_SKILL_CAPABILITY
                or not (
                    action.tool_name in FILE_READ_CAPABILITIES
                    or self._safe_for_concurrency(action)
                )
            ):
                continue
            request_digest = canonical_digest({
                "tool_name": action.tool_name,
                "arguments": action.arguments,
            })
            first_action_id = first_safe_request.setdefault(
                request_digest,
                action.action_id,
            )
            if first_action_id == action.action_id:
                continue
            admitted[index] = DecisionFeedback(
                action_id=action.action_id,
                action_name=f"{action.tool_name}:{request_digest[:12]}",
                reason_code="duplicate_action_request",
                message=(
                    f"Action {first_action_id!r} already contains this exact safe "
                    "request in the same proposal. Both calls would run without an "
                    "intermediate observation."
                ),
                repairable_fields=("tool_name", "arguments"),
                immutable_fields=("action_id",),
                required_repair=(
                    "Keep one exact request, observe its result, and only propose a "
                    "different follow-up if that observation makes it necessary."
                ),
            )
        accepted = [
            action
            for action, feedback in zip(proposal.actions, admitted, strict=True)
            if feedback is None
        ]
        denied = [
            _ActionResult(
                action.action_id,
                self._name_action_feedback(feedback, proposal.actions),
            )
            for action, feedback in zip(proposal.actions, admitted, strict=True)
            if feedback is not None
        ]
        runnable, budget_feedback = self._budget.allocate_actions(accepted, usage)
        denied.extend(_ActionResult(feedback.action_id, self._name_action_feedback(feedback, proposal.actions))
                      for feedback in budget_feedback)
        reviewed, action_feedback, usage = self._review_bash_actions(runnable, run_ref=run_ref)
        if action_feedback:
            denied.extend(_ActionResult(action_id, feedback) for action_id, feedback in action_feedback.items())
            runnable = [item for item in runnable if item.action_id not in action_feedback]
        if reviewed and runnable:
            self._admit_research_model_call(run_ref, usage)
        concurrent = len(runnable) > 1 and all(
            self._safe_for_concurrency(item) for item in runnable
        )
        context = (
            conversation_id,
            run_ref,
            principal,
            owner,
            source_platform,
        )
        trace = self._journal.get(run_ref)
        history = selected_analysis_turns(trace, self._journal.task_traces(trace))
        goal = current_analysis_goal(trace, history)
        bash_input_scope = self._bash_input_scope(trace)
        for action in runnable:
            if not isinstance(action, ToolCallProposal) or action.tool_name not in {"write_artifact", "retrieval_experiment", "bash"}:
                continue
            argument_type = {"write_artifact": WriteArtifactArgs,
                             "retrieval_experiment": ExperimentToolArgs,
                             "bash": BashArgs}[action.tool_name]
            self._journal.accept_tool_request(
                execution_scope=ExecutionScope(principal=principal, execution_id=run_ref,
                                                thread_id=conversation_id, task_id=action.action_id),
                action_id=action.action_id,
                arguments=(reviewed[action.action_id].arguments if action.action_id in reviewed else
                           argument_type.model_validate(action.arguments, context=self._prompts)),
                plan_step_id=plan_step_id,
                action_goal_binding=reviewed[action.action_id].binding if action.action_id in reviewed else None,
                goal_ref=goal.reference if goal is not None else None,
                bash_input_scope=bash_input_scope,
            )
        if concurrent:
            with ThreadPoolExecutor(
                max_workers=min(len(runnable), self._budget.limits.max_concurrency)
            ) as pool:
                futures = [
                    pool.submit(self._execute_one, item, context,
                                replaying_model_response=replaying_model_response)
                    for item in runnable
                ]
                executed = [future.result() for future in futures]
        else:
            executed = [
                self._execute_one(item, context, replaying_model_response=replaying_model_response)
                for item in runnable
            ]
        usage = usage.model_copy(
            update={
                "tool_calls": usage.tool_calls
                + sum(isinstance(item, ToolCallProposal) for item in runnable),
                "agent_calls": usage.agent_calls
                + sum(isinstance(item, AgentDelegationProposal) for item in runnable),
            }
        )
        by_id = {item.action_id: item for item in (*executed, *denied)}
        for action_id, item in tuple(by_id.items()):
            if isinstance(item.interaction_input, ActionObservation):
                by_id[action_id] = _ActionResult(
                    action_id,
                    item.interaction_input.model_copy(
                        update={"plan_step_id": plan_step_id}
                    ),
                )
        ordered_calls = proposal.actions
        if partially_decoded is not None:
            ordered_calls = partially_decoded.calls
            by_id.update({
                call.action_id: _ActionResult(call.action_id, call)
                for call in partially_decoded.calls if isinstance(call, DecisionFeedback)
            })
        return (
            [by_id[call.action_id] for call in ordered_calls],
            usage,
            concurrent,
        )

    @staticmethod
    def _committed_call_ids(trace: InteractionTrace) -> frozenset[str]:
        return frozenset((*trace.execution_order, *(item.action_id for item in trace.accepted_tool_requests),
            *(item.call_id for item in trace.goal_operations if item.decision_turn < trace.current_step_no)))

    def _duplicate_call_feedback(self, call_id: str, *, action_name: str = "") -> DecisionFeedback:
        return DecisionFeedback(action_id=call_id, action_name=action_name, reason_code="duplicate_action_id",
            message=self._prompts.render("conversation.service.duplicate_call_id", call_id=call_id),
            immutable_fields=("action_id", "kind"),
            required_repair=self._prompts.get("conversation.service.duplicate_call_repair").template)

    @staticmethod
    def _has_knowledge_inventory(inputs) -> bool:
        return any(isinstance(item, ActionObservation) and item.capability_id == _LIST_PERSONAL_KNOWLEDGE_CAPABILITY
                   and item.status == "succeeded" for item in inputs)

    def _admit(self, action, *, run_ref, committed_action_ids, committed_inputs):
        if isinstance(action, ToolCallProposal) and action.tool_name in {"retrieval_experiment", "bash"}:
            trace = self._journal.get(run_ref)
            binding = (trace.bash_profile_digest if action.tool_name == "bash"
                       else trace.deployment_digest) if trace is not None else None
            if binding is None:
                return DecisionFeedback(action_id=action.action_id, reason_code="capability_missing",
                    message=self._prompts.render('conversation.service.execution_permission_missing'), immutable_fields=("action_id",),
                    required_repair=self._prompts.render('conversation.service.execution_permission_repair'), disposition="fail_closed")
        if action.action_id in committed_action_ids:
            return self._duplicate_call_feedback(action.action_id)
        if (
            isinstance(action, ToolCallProposal)
            and action.tool_name in FILE_READ_CAPABILITIES
        ):
            # Service-owned: the artifact port serves it, so the tool registry has no
            # entry to validate against and its schema is the contract.
            if self._artifact_port is None or (action.tool_name == GREP_FILE_CAPABILITY and self._artifact_search is None):
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="capability_missing",
                    message=f"Tool {action.tool_name!r} is not currently available.",
                    repairable_fields=("tool_name", "arguments"),
                    immutable_fields=("action_id",),
                    required_repair="Choose an available tool or explain the capability limitation.",
                )
            try:
                argument_type = GrepFileArguments if action.tool_name == GREP_FILE_CAPABILITY else ReadFileArguments
                arguments = argument_type.model_validate(action.arguments, context=self._prompts)
            except ValidationError as error:
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="invalid_arguments",
                    message=str(error),
                    repairable_fields=("arguments",),
                    immutable_fields=("action_id", "tool_name"),
                    required_repair="Revise only the arguments to satisfy the declared tool schema.",
                )
            try:
                trace = self._journal.get(run_ref)
                resource_ref = resolve_artifact_file(
                    arguments.file_path,
                    self._journal.readable_resource_refs(trace),
                    principal=trace.principal,
                    prompts=self._prompts,
                )
            except PermissionError:
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="artifact_reference_invalid",
                    message=(
                        self._prompts.render('conversation.service.resource_reference_not_allowed')
                    ),
                    repairable_fields=("arguments",),
                    immutable_fields=("action_id", "tool_name"),
                    required_repair=(
                        self._prompts.render('conversation.service.resource_reference_repair')
                    ),
                )
            if resource_ref in self._history_snapshot_refs(trace) and self._history is not None:
                self._history.validate(trace)
            return None
        if isinstance(action, ToolCallProposal):
            offloaded = self._offloaded_resources(committed_inputs)
            request_digest = canonical_digest({
                "tool_name": action.tool_name,
                "arguments": action.arguments,
            })
            if any(
                capability_id == action.tool_name and prior_digest == request_digest
                for capability_id, prior_digest, _ in offloaded.values()
            ):
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code=OFFLOADED_OUTPUT_REFETCH,
                    message=self._prompts.get("conversation.service.artifact_refetch").template,
                    immutable_fields=("action_id",),
                )
        if (
            isinstance(action, ToolCallProposal)
            and action.tool_name == _SEARCH_PERSONAL_KNOWLEDGE_CAPABILITY
        ):
            if self._knowledge_reader is None:
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="capability_missing",
                    message=f"Tool {action.tool_name!r} is not currently available.",
                    immutable_fields=("action_id",),
                    required_repair="Explain the capability limitation.",
                    disposition="fail_closed",
                )
            try:
                SearchPersonalKnowledgeArguments.model_validate(action.arguments)
            except ValidationError as error:
                return self._invalid_special_arguments(action, error)
            if any(
                isinstance(item, ActionObservation)
                and item.capability_id == _SEARCH_PERSONAL_KNOWLEDGE_CAPABILITY
                and item.status == "succeeded"
                for item in committed_inputs
            ):
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="personal_knowledge_already_searched",
                    message=(
                        "The current interaction already has a successful authoritative "
                        "personal-knowledge search Observation."
                    ),
                    immutable_fields=("action_id", "tool_name"),
                    required_repair=(
                        "Use the committed search Observation to continue or answer; do not "
                        "repeat the read in this interaction."
                    ),
                )
            return None
        if (
            isinstance(action, ToolCallProposal)
            and action.tool_name == _LIST_PERSONAL_KNOWLEDGE_CAPABILITY
        ):
            if self._knowledge_reader is None:
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="capability_missing",
                    message=f"Tool {action.tool_name!r} is not currently available.",
                    immutable_fields=("action_id",),
                    required_repair="Explain the capability limitation.",
                    disposition="fail_closed",
                )
            try:
                ListPersonalKnowledgeArguments.model_validate(action.arguments)
            except ValidationError as error:
                return self._invalid_special_arguments(action, error)
            if self._has_knowledge_inventory(committed_inputs):
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="knowledge_list_already_observed",
                    message=self._prompts.get("conversation.knowledge.inventory_already_returned").template,
                    immutable_fields=("action_id", "tool_name"),
                    required_repair=self._prompts.get("conversation.knowledge.inventory_reuse").template,
                )
            return None
        if isinstance(action, ToolCallProposal):
            if self._tool_port is None:
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="capability_missing",
                    message=f"Tool {action.tool_name!r} is not currently available.",
                    repairable_fields=("tool_name", "arguments"),
                    immutable_fields=("action_id",),
                    required_repair="Choose an available tool or explain the capability limitation.",
                )
            validation = self._tool_port.validate_interaction_call(
                action.tool_name,
                action.arguments,
            )
            if validation.status != "accepted":
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code=validation.status,
                    message=validation.message,
                    repairable_fields=(
                        ("tool_name", "arguments")
                        if validation.status == "capability_missing"
                        else ("arguments",)
                    ),
                    immutable_fields=(
                        ("action_id",)
                        if validation.status == "capability_missing"
                        else ("action_id", "tool_name")
                    ),
                    required_repair=(
                        "Choose an available tool or explain the capability limitation."
                        if validation.status == "capability_missing"
                        else "Revise only the arguments to satisfy the declared tool schema."
                    ),
                )
            return None
        profile = (
            self._agent_port.profile(action.agent_id) if self._agent_port else None
        )
        if profile is None:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="capability_missing",
                message=f"Agent {action.agent_id!r} is not currently available.",
                repairable_fields=("agent_id", "bounded_sub_goal"),
                immutable_fields=("action_id",),
                required_repair="Choose an available agent or explain the capability limitation.",
            )
        observed_artifact_refs = {
            str(artifact_ref)
            for item in committed_inputs
            if isinstance(item, ActionObservation) and item.kind == "agent_artifact"
            for artifact_ref in item.payload.get("artifact_refs", ())
            if str(artifact_ref)
        }
        artifact_agent_ids = {
            item.capability_id
            for item in committed_inputs
            if isinstance(item, ActionObservation)
            and item.kind == "agent_artifact"
            and item.payload.get("artifact_refs")
        }
        if action.agent_id in artifact_agent_ids:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="agent_artifact_already_returned",
                message=(
                    "This agent already returned an AgentArtifact in the current interaction. "
                    "The child terminal status does not erase that execution fact."
                ),
                repairable_fields=(
                    "agent_id",
                    "bounded_sub_goal",
                    "context_projection_refs",
                ),
                immutable_fields=("action_id",),
                required_repair=(
                    "Assess the existing artifact and return the parent synthesis. If a distinct downstream "
                    "specialist is genuinely required, select a different available agent and cite the observed "
                    "artifact_ref as its context dependency."
                ),
            )
        if observed_artifact_refs and observed_artifact_refs.isdisjoint(
            action.context_projection_refs
        ):
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="delegation_requires_observed_artifact_dependency",
                message=(
                    "A successful AgentArtifact is already available. A later delegation must be a "
                    "distinct dependent subtask grounded in an observed artifact reference."
                ),
                repairable_fields=("context_projection_refs", "bounded_sub_goal"),
                immutable_fields=("action_id", "agent_id"),
                required_repair=(
                    "If another dependent delegation is genuinely required, cite at least one supplied "
                    "artifact_ref in context_projection_refs. Otherwise assess the existing artifact and "
                    "return the parent synthesis without another delegation."
                ),
            )
        return None

    def _safe_for_concurrency(self, action):
        if isinstance(action, ToolCallProposal):
            if action.tool_name == _LIST_PERSONAL_KNOWLEDGE_CAPABILITY:
                return True
            return bool(
                self._tool_port
                and self._tool_port.interaction_call_is_safe_for_concurrency(
                    action.tool_name
                )
            )
        profile = (
            self._agent_port.profile(action.agent_id) if self._agent_port else None
        )
        return bool(profile and set(profile.allowed_operations) <= {"delegate", "read"})

    def _load_skill_scripts(
        self, trace: InteractionTrace, scope: ExecutionScope, *, source_platform: str, result: dict[str, Any],
    ) -> PublishedSkillScripts | None:
        if (self._skill_scripts is None or self._skill_catalog is None
                or trace.bash_profile_digest is None or not self._tool_profile.enables("bash")):
            return None
        loaded = LoadedSkill.model_validate(result["data"])
        skill = self._skill_catalog.visible(scope.principal, scope.thread_id, source_platform=source_platform)[loaded.name]
        return self._skill_scripts(skill, scope)

    def _fit_observation_payload(
        self,
        payload: dict[str, Any],
        *,
        capability_id: str,
        execution_scope: ExecutionScope,
    ) -> dict[str, Any]:
        """Keep a bounded preview and save the full tool text as a session file."""

        data = payload.get("data")
        if capability_id == "bash" and isinstance(data, dict) and "receipt" in data:
            # Bash already bounds both stream previews and publishes their original files.
            BashToolResult.model_validate(data)
            return payload
        original_bytes = serialized_utf8_size(payload)
        if original_bytes <= MAX_TOOL_OBSERVATION_BYTES:
            return payload
        retrieval: dict[str, Any] = {
            "original_bytes": original_bytes,
            "original_chars": serialized_length(payload),
        }
        # 抓取契约在读取边界校验；明确选择来源载荷，不依赖最长叶子或工具名注册表。
        source_output = (
            WebReadOutput.model_validate(data)
            if isinstance(data, dict) and data.get("format") == WEB_SOURCE_FORMAT
            else None
        )
        search_output = (
            WebSearchOutput.model_validate(data)
            if capability_id == "web_search" and payload.get("ok") else None
        )
        full_text = (
            source_output.source_text if source_output and source_output.source_text
            else search_output.model_dump_json(exclude={"query", "limit"}) if search_output
            else select_offload_text(payload)
        )
        try:
            if self._artifact_port is None:
                raise RuntimeError("Tool output storage is unavailable")
            resource_ref = self._artifact_port.write_tool_output(
                execution_scope=execution_scope, capability_id=capability_id, content=full_text,
            )
        except Exception as error:  # offload failure must be visible, not silent
            retrieval["unavailable_reason"] = (
                f"Offload failed ({type(error).__name__}); the omitted part cannot be "
                "re-read in this turn."
            )
        else:
            retrieval["resource_ref"] = resource_ref.model_dump(mode="json")
            retrieval["total_lines"] = len(TextCoordinates(full_text).lines)

        # Keep source metadata once. The complete protocol payload is already in
        # the artifact, so repeated representations do not compete for preview space.
        fitted = {key: value for key, value in payload.items()
                  if key in {"ok", "error", "error_kind", "status"}}
        if source_output is not None:
            fitted["data"] = source_output.model_copy(update={"source_text": ""}).model_dump(mode="json")
        elif search_output is not None:
            fitted["data"] = search_output.model_copy(update={"results": ()}).model_dump(mode="json")
        fitted["retrieval"] = retrieval
        tool_text = data.get("text") if isinstance(data, dict) else None
        preview = tool_text if isinstance(tool_text, str) and tool_text else full_text
        return fit_observation_preview(fitted, preview, previously_omitted=0)

    def _execute_file_tool(self, action: ToolCallProposal, *, principal, owner, run_ref: str) -> _ActionResult:
        trace = self._journal.get(run_ref)
        try:
            searching = action.tool_name == GREP_FILE_CAPABILITY
            argument_type = GrepFileArguments if searching else ReadFileArguments
            arguments = argument_type.model_validate(action.arguments, context=self._prompts)
            ref = resolve_artifact_file(
                arguments.file_path, self._journal.readable_resource_refs(trace),
                principal=principal, prompts=self._prompts,
            )
            snapshot = self._artifact_port.read_snapshot(ref, principal=principal, owner=owner)
            if isinstance(arguments, GrepFileArguments):
                result = grep_file_text(snapshot, arguments=arguments, matcher=self._artifact_search, prompts=self._prompts)
            else:
                result = read_file_text(snapshot, arguments=arguments, prompts=self._prompts)
            observation = ActionObservation(
                kind="tool_result", action_id=action.action_id, capability_id=action.tool_name,
                evidence_eligible=ref not in self._recorded_history_snapshot_refs(trace) and ref not in trace_goal_draft_refs(trace),
                status="succeeded", payload={"ok": True, **result.model_dump(mode="json")},
            )
        except (ValidationError, ValueError) as error:
            observation = ActionObservation(
                kind="tool_result", action_id=action.action_id, capability_id=action.tool_name,
                status="failed", payload={"ok": False, "error_kind": "invalid_param", "error": str(error)},
            )
        except (OSError, RuntimeError) as error:
            observation = ActionObservation(
                kind="tool_result", action_id=action.action_id, capability_id=action.tool_name,
                status="failed", payload={"ok": False, "error_kind": "execution_failure", "error": str(error)},
            )
        return _ActionResult(action.action_id, observation)

    def _execute_one(self, action, context, *, replaying_model_response: bool = False):
        conversation_id, run_ref, principal, owner, source_platform = context
        execution_scope = ExecutionScope(
            principal=principal,
            execution_id=run_ref,
            thread_id=conversation_id,
            task_id=action.action_id,
        )
        if (
            isinstance(action, ToolCallProposal)
            and action.tool_name in FILE_READ_CAPABILITIES
        ):
            return self._execute_file_tool(action, principal=principal, owner=owner, run_ref=run_ref)
        if (
            isinstance(action, ToolCallProposal)
            and action.tool_name == _SEARCH_PERSONAL_KNOWLEDGE_CAPABILITY
        ):
            arguments = SearchPersonalKnowledgeArguments.model_validate(action.arguments)
            evidence = self._knowledge_reader.select_personal_evidence(
                question=arguments.query,
                owner_id=owner.principal_id,
                user_id=principal.user_id,
                limit=arguments.limit,
            )
            return _ActionResult(
                action.action_id,
                ActionObservation(
                    kind="tool_result",
                    action_id=action.action_id,
                    capability_id=action.tool_name,
                    status="succeeded",
                    payload=evidence.model_dump(mode="json"),
                ),
            )
        if (
            isinstance(action, ToolCallProposal)
            and action.tool_name == _LIST_PERSONAL_KNOWLEDGE_CAPABILITY
        ):
            arguments = ListPersonalKnowledgeArguments.model_validate(action.arguments)
            items = self._knowledge_reader.list_personal_knowledge(
                owner_id=owner.principal_id,
                user_id=principal.user_id,
                limit=arguments.limit,
            )
            return _ActionResult(
                action.action_id,
                ActionObservation(
                    kind="tool_result",
                    action_id=action.action_id,
                    capability_id=action.tool_name,
                    status="succeeded",
                    payload={
                        "items": [item.model_dump(mode="json") for item in items],
                        "count": len(items),
                    },
                ),
            )
        if isinstance(action, ToolCallProposal):
            trace = self._journal.get(run_ref)
            request_digest = canonical_digest({"tool_name": action.tool_name, "arguments": action.arguments})
            mcp_write = (
                any(item.action_id == action.action_id for item in trace.mcp_write_dispatches or ())
                or self._tool_port.interaction_call_is_mcp_write(action.tool_name)
            )
            if mcp_write and not self._journal.begin_mcp_write_dispatch(
                execution_scope,
                MCPWriteDispatch(action_id=action.action_id, tool_name=action.tool_name, request_digest=request_digest),
                replaying_model_response=replaying_model_response,
            ):
                return _ActionResult(action.action_id, ActionObservation(
                    kind="tool_result", action_id=action.action_id, capability_id=action.tool_name,
                    status="unknown", evidence_eligible=False, execution_request_digest=request_digest,
                ))
            accepted = next((item for item in trace.accepted_tool_requests if item.action_id == action.action_id), None)
            if isinstance(accepted, AcceptedArtifactToolRequest) and accepted.receipt is None and accepted.failure is None:
                self._journal.check_tool_binding(trace, accepted)
            known_execution = any(item.action_id == action.action_id and item.command is not None
                                  for item in trace.experiment_records)
            known_execution = known_execution or any(
                isinstance(item, AcceptedBashToolRequest) and item.action_id == action.action_id
                and item.command is not None for item in trace.accepted_tool_requests
            )
            if action.tool_name in {"write_artifact", "retrieval_experiment", "bash"} and (
                deadline_elapsed(trace.run_deadline_at) and not known_execution):
                result = {"ok": False, "error": self._prompts.render('conversation.service.experiment_mutation_deadline'), "error_kind": "permission", "data": None, "evidence": []}
            else:
                result = self._tool_port.invoke_interaction(
                action.tool_name,
                action.arguments,
                execution_scope=execution_scope,
                tool_call_id=action.action_id,
                source_platform=source_platform,
                allowed_resource_refs=self._journal.readable_resource_refs(self._journal.get(run_ref)),
                accepted_request_digest=next((item.request_digest for item in self._journal.get(run_ref).accepted_tool_requests
                                              if item.action_id == action.action_id), None),
            )
            skill_scripts = None
            if action.tool_name == LOAD_SKILL_CAPABILITY and result.get("ok"):
                try:
                    skill_scripts = self._load_skill_scripts(
                        trace, execution_scope, source_platform=source_platform, result=result,
                    )
                except (OSError, ValueError):
                    result = {
                        "ok": False, "error": self._prompts.get("skills.scripts_unavailable").template,
                        "error_kind": "unrecoverable", "data": None, "evidence": [],
                    }
            completed = _ActionResult(
                action.action_id,
                ActionObservation(
                    kind="tool_result",
                    action_id=action.action_id,
                    capability_id=action.tool_name,
                    status="succeeded" if result.get("ok") else "failed",
                    execution_request_digest=request_digest,
                    skill_scripts=skill_scripts,
                    payload=self._fit_observation_payload(
                        result,
                        capability_id=action.tool_name,
                        execution_scope=execution_scope,
                    ),
                ),
            )
            if action.tool_name == "write_artifact":
                self._journal.record_artifact_result(
                    execution_scope=execution_scope, action_id=action.action_id,
                    receipt=ArtifactWriteReceipt.model_validate(result["data"]) if result.get("ok") else None,
                    failure=completed.interaction_input if not result.get("ok") else None,
                )
            return completed
        gateway_context = AgentGatewayContext(
            execution_scope=execution_scope,
            source_platform=source_platform,
        )
        grant = self._delegation_grant(action, run_ref)
        delegation_started = monotonic()
        provider_wait_started: float | None = None
        provider_terminal_status: str | None = None
        application_observation_status = "failed"
        try:
            run = self._agent_port.submit(
                action.agent_id,
                AgentTask(
                    task_text=action.bounded_sub_goal,
                    task_type="research",
                    metadata={
                        "expected_artifact_types": action.expected_artifact_types
                    },
                ),
                gateway_context,
                grant,
                submission_key=sha256(
                    f"{run_ref}:{action.action_id}".encode("utf-8")
                ).hexdigest(),
            )
            provider_wait_started = monotonic()
            deadline = provider_wait_started + action.time_budget_seconds
            while run.projection.status in {"created", "queued", "running"}:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    run = self._agent_port.timeout(
                        run.definition.agent_run_id,
                        gateway_context,
                    )
                    break
                sleep(min(0.25, remaining))
                run = self._agent_port.poll(
                    run.definition.agent_run_id, gateway_context
                )
            provider_terminal_status = run.projection.status
            payload = {
                "child_agent_run_ref": run.definition.agent_run_id,
                "status": run.projection.status,
                "artifact_refs": [
                    item.artifact_ref.model_dump(mode="json")
                    for item in run.artifact_index.artifacts
                ],
                "artifacts": [],
            }
            for item in run.artifact_index.artifacts:
                content = self._artifact_port.read_text(
                    item.artifact_ref,
                    principal=principal,
                    owner=owner,
                )
                payload["artifacts"].append(
                    {
                        "artifact_ref": item.artifact_ref.model_dump(mode="json"),
                        "kind": item.kind,
                        "content_excerpt": content[:6_000],
                        "content_length": len(content),
                        "content_sha256": sha256(content.encode("utf-8")).hexdigest(),
                    }
                )
            status = {
                "completed": "succeeded",
                "completed_degraded": "succeeded",
                "failed": "failed",
                "timed_out": "failed",
                "cancelled": "cancelled",
            }.get(run.projection.status, "running")
            application_observation_status = status
            return _ActionResult(
                action.action_id,
                ActionObservation(
                    kind="agent_artifact"
                    if payload["artifact_refs"]
                    else "agent_status",
                    action_id=action.action_id,
                    capability_id=action.agent_id,
                    status=status,
                    payload=payload,
                ),
            )
        except Exception as exc:
            return _ActionResult(
                action.action_id,
                ActionObservation(
                    kind="agent_status",
                    action_id=action.action_id,
                    capability_id=action.agent_id,
                    status="failed",
                    payload={"error": str(exc)},
                ),
            )
        finally:
            finished = monotonic()
            _LOGGER.info(
                "conversation.agent_delegation | %s",
                json.dumps(
                    {
                        "action_id": action.action_id,
                        "agent_id": action.agent_id,
                        "authorized_time_budget_seconds": action.time_budget_seconds,
                        "provider_wait_elapsed_seconds": (
                            round(finished - provider_wait_started, 6)
                            if provider_wait_started is not None
                            else None
                        ),
                        "delegation_elapsed_seconds": round(
                            finished - delegation_started,
                            6,
                        ),
                        "provider_terminal_status": provider_terminal_status,
                        "application_observation_status": (
                            application_observation_status
                        ),
                    },
                    sort_keys=True,
                ),
            )

    @staticmethod
    def _delegation_grant(action, run_ref):
        digest = sha256(
            json.dumps(action.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        return DelegationGrant(
            request_id=run_ref,
            action_ref=action.action_id,
            authorization_digest=digest,
            execution_command_digest=digest,
            granted_resource_selector=ResourceSelector(),
            granted_operation_scope=OperationScope(
                operations=frozenset({"delegate"}), side_effect_class="external_network"
            ),
            granted_data_egress="content",
            granted_credential_mode="provider_managed",
            retry_family_id=digest,
            dependency_set=GrantDependencySet(
                task_revision=1,
                goal_definition_fingerprint=digest,
                action_fingerprint=digest,
                capability_definition_revision=1,
                provider_binding_revision=1,
                authority_revision=1,
                policy_bundle_hash="interaction-loop-v1",
            ),
            agent_binding_ref=f"agent:{action.agent_id}",
            bounded_sub_goal=action.bounded_sub_goal,
            context_projection_refs=action.context_projection_refs,
            token_budget=action.token_budget,
            cost_budget=action.cost_budget,
            time_budget_seconds=action.time_budget_seconds,
            completion_contract="return typed status and artifact refs to parent",
        )

    def _budget_exhausted(
        self,
        conversation_id,
        run_ref,
        principal,
        messages,
        inputs,
        usage,
        execution_order,
        concurrent_batches,
        context_composition,
        working_plan=None,
        *,
        partially_decoded: PartiallyDecodedToolBatch | None = None,
    ):
        message = self._prompts.render("conversation.service.execution_budget_limitation")
        if partially_decoded is not None:
            inputs.extend(
                call if isinstance(call, DecisionFeedback) else DecisionFeedback(
                    action_id=call.action_id,
                    action_name=call.tool_name,
                    reason_code="budget_exhausted",
                    message=message,
                    disposition="fail_closed",
                )
                for call in partially_decoded.calls
            )
        return self._fail_closed_limitation(
            conversation_id,
            run_ref,
            principal,
            messages,
            inputs,
            usage,
            execution_order,
            concurrent_batches,
            context_composition,
            working_plan=working_plan,
            message=message,
        )

    def _fail_closed_limitation(
        self,
        conversation_id,
        run_ref,
        principal,
        messages,
        inputs,
        usage,
        execution_order,
        concurrent_batches,
        context_composition,
        *,
        message,
        working_plan=None,
    ):
        final = FinalMessage(disposition="limitation", segments=(ConversationAnswerSegment(text=message),))
        while True:
            try:
                self._commit(
                    run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
                    context_composition, final_message=final, working_plan=working_plan,
                )
                break
            except ConversationSteeringPending:
                # No further model call is permitted on a limitation path.
                self._journal.claim_steering(ExecutionScope(
                    principal=principal, execution_id=run_ref, thread_id=conversation_id,
                ))
        return ConversationTurnView(
            interaction_run_ref=run_ref,
            conversation_id=conversation_id,
            disposition="limitation",
            message=ConversationMessage(
                role="assistant",
                content=final.message,
            ),
            working_plan=working_plan,
        )

    def _commit(
        self,
        run_ref,
        principal,
        messages,
        inputs,
        usage,
        execution_order,
        concurrent_batches,
        context_composition,
        final_message=None,
        knowledge_save_operation=None,
        knowledge_delete_command_ref=None,
        working_plan=None,
        model_response=None,
        call_dispositions=(),
        goal_operation: GoalOperationRecord | None = None,
    ):
        prior = self._journal.get(run_ref)
        if prior is None:
            raise ConversationOperationNotFound("interaction run not found")
        updates = {"total_tokens": max(prior.usage.total_tokens, usage.total_tokens)}
        for name in ("model_calls", "input_tokens", "output_tokens"):
            old, new = getattr(prior.usage, name), getattr(usage, name)
            updates[name] = None if old is None or new is None else max(old, new)
        updates["provider_usage_complete"] = prior.usage.provider_usage_complete and usage.provider_usage_complete
        usage = usage.model_copy(update=updates)
        self._append_artifact_sources(run_ref, inputs)
        step_no = prior.current_step_no
        if model_response is None:
            main = next((record for record in reversed(prior.model_decisions)
                         if record.step_no == step_no and record.assistant is not None), None)
            if (main is not None and len(main.assistant.call_ids) == 1
                    and any(action.kind == "answer_result" for action in self._journal.model_request(run_ref, main).action_definitions
                            if action.name == main.assistant.payload["tool_calls"][0].get("function", {}).get("name"))
                    and (any(isinstance(item, SubmittedFinal) for item in inputs[main.input_start:])
                         or final_message is not None)
                    and not any(isinstance(item, DecisionFeedback) for item in inputs[main.input_start:])
                    and not main.dispositions):
                call_dispositions = (*call_dispositions, ModelCallDisposition(
                    call_id=main.assistant.call_ids[0], operation="answer_result", status="accepted"))
        new_inputs = inputs[len(prior.inputs):]
        consumed_inner_operations = set()
        if any(isinstance(item, ActionObservation) and item.capability_id == _VERIFICATION_CAPABILITY
               for item in new_inputs):
            consumed_inner_operations.update({"interaction_cited_support", "interaction_semantic_verification",
                "interaction_goal_verification", GOAL_COMPLIANCE_OPERATION})
        if any((isinstance(item, ActionObservation) and item.capability_id == "bash")
               or (isinstance(item, DecisionFeedback) and item.reason_code == "action_goal_conflict")
               for item in new_inputs):
            consumed_inner_operations.add(GOAL_COMPLIANCE_OPERATION)
        # Bind feedback to the model step that produced the rejected action.
        for index in range(len(prior.inputs), len(inputs)):
            item = inputs[index]
            if isinstance(item, DecisionFeedback):
                inputs[index] = item.model_copy(
                    update={"decision_turn": step_no or None}
                )
        next_trace = InteractionTrace(
            action_goal_reviews=prior.action_goal_reviews,
            goal_compliance_history_compacted_through=prior.goal_compliance_history_compacted_through,
            goal_operations=(*prior.goal_operations,
                             *((goal_operation,) if goal_operation is not None else ())),
            revision=prior.revision + 1,
            interaction_run_ref=run_ref,
            conversation_id=prior.conversation_id,
            principal=principal,
            messages=tuple(messages),
            steering=prior.steering,
            input_artifact_refs=prior.input_artifact_refs,
            accepted_tool_requests=prior.accepted_tool_requests,
            mcp_write_dispatches=prior.mcp_write_dispatches,
            experiment_records=prior.experiment_records,
            research_experiment_delivery=prior.research_experiment_delivery,
            history_compaction=prior.history_compaction,
            history_tool_pruning=prior.history_tool_pruning,
            verification_history_compactions=prior.verification_history_compactions,
            deployment_digest=prior.deployment_digest,
            bash_authorization_digest=prior.bash_authorization_digest,
            answer_protocol_version=prior.answer_protocol_version,
            answer_result_binding=prior.answer_result_binding,
            feature_flags_binding=prior.feature_flags_binding,
            tool_profile_binding=prior.tool_profile_binding,
            skill_scope_digest=prior.skill_scope_digest,
            goal_mode=prior.goal_mode,
            run_deadline_at=prior.run_deadline_at,
            max_execution_seconds=prior.max_execution_seconds,
            inputs=tuple(inputs),
            usage=usage,
            execution_order=tuple(execution_order),
            concurrent_batches=tuple(concurrent_batches),
            context_composition=tuple(context_composition),
            model_decisions=tuple(record.model_copy(update={"consumed": True})
                if record.status != "pending" and (
                    (record.step_no is None and record.operation in consumed_inner_operations)
                    or (record.step_no is not None and record.step_no <= step_no and (
                        final_message is not None or record.blocked_by is not None
                        or len(inputs) > record.input_start
                        or (record.assistant is not None and bool(record.assistant.call_ids)
                            and len(record.assistant.call_ids) == len(record.dispositions)))))
                else record for record in update_decisions(prior, inputs=inputs, step_no=step_no,
                response=model_response, dispositions=call_dispositions)),

            final_message=final_message,
            knowledge_save_operation=knowledge_save_operation,
            workspace_changes=prior.workspace_changes,
            knowledge_delete_command_ref=(
                knowledge_delete_command_ref
                if knowledge_delete_command_ref is not None
                else prior.knowledge_delete_command_ref
            ),
            working_plan=(working_plan if working_plan is not None or (
                goal_operation is not None and goal_operation.patch is not None
                and goal_operation.patch.task is not None
                and goal_operation.patch.task.action != "continue"
            ) else prior.working_plan),
        )
        try:
            self._journal.put(next_trace)
        except ConversationSteeringPending:
            self._journal.put(next_trace.model_copy(update={
                "final_message": None,
                "working_plan": prior.working_plan,
            }))
            raise


__all__ = [
    "ConversationOperationConflict",
    "ConversationOperationNotFound",
    "ConversationService",
    "ConversationFailure",
    "InMemoryInteractionJournal",
]

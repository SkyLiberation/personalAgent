from __future__ import annotations

from personal_agent.capabilities.contracts.verification import ConversationAnswerSegment
from personal_agent.kernel.prompts import get_prompt

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from hashlib import sha256
import json
import logging
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from personal_agent.application.capture.web_source import WEB_SOURCE_FORMAT, WebReadOutput, WebSearchOutput

from personal_agent.capabilities.contracts.grants import (
    DelegationGrant,
    GrantDependencySet,
)
from personal_agent.capabilities.contracts.model import (
    ModelInvocationUnavailable,
    ModelCapacityRefused,
    StructuredOutputFailure,
    StructuredModelResponse,
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.capabilities.contracts.verification import VerificationVerdict
from personal_agent.kernel.contracts.agent import AgentGatewayContext, AgentTask
from personal_agent.kernel.contracts.derivation import canonical_digest
from personal_agent.application.artifacts.models import ArtifactWriteReceipt, resolve_artifact_ref
from personal_agent.application.retrieval_experiment.models import (
    ExperimentToolArgs, PublishedExperimentResult, RetrievalDeployment,
)
from personal_agent.application.python_execution.models import ExecutePythonArgs, PythonExecutionAuthorization
from personal_agent.application.retrieval_experiment.delivery import DeliveryIncomplete
from .research_delivery import (
    ResearchExperimentCompletionUseCase, experiment_submission, pending_experiment_submission,
)
from .tool_requests import WriteArtifactArgs
from .artifact_sources import input_resource_refs
from .history_compaction import HistoryCompactor, checkpoint_refs
from .model_history import (
    project_model_history, update_decisions,
)
from personal_agent.kernel.contracts.resource import OperationScope, ResourceRef, ResourceSelector
from personal_agent.kernel.contracts.scope import (
    ExecutionScope,
    AuthenticatedPrincipal,
)
from personal_agent.kernel.observability import PolicyDecisionRecorder
from personal_agent.kernel.contracts.policy import PolicyDecisionEvent
from personal_agent.kernel.logging_utils import log_event

from .observation_bounds import (
    MAX_OBSERVATION_PAYLOAD_CHARS,
    bound_observation_payload,
    excerpt_payload_text,
    select_offload_text,
    serialized_length,
)
from .context_materialization import (
    READ_ACTION_OUTPUT_CAPABILITY,
    READ_ARTIFACT_CAPABILITY,
    SEARCH_ACTION_OUTPUT_CAPABILITY,
    ARTIFACT_OUTPUT_CAPABILITIES,
    materialize_interaction_inputs,
)
from .artifact_search import ArtifactSearchPort, SearchActionOutputArguments, search_artifact_text
from .artifact_reading import ReadArtifactArguments, read_artifact_text
from .citations import (
    CitationBindingError, materialize_cited_draft, materialize_citation_context,
    selected_citation_ids, bound_citation_ids,
)
from .interaction_prompt import build_interaction_system_prompt
from .answer_results import DirectAnswerResult, ClaimAnswerResult
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig

from .research import (
    current_claims, ResearchEvidenceSelection, editable_research_claims,
    applicable_research_review, research_review_context, research_goal_requirements,
    validate_research_selection,
)
from personal_agent.capabilities.contracts.research import ResearchClaims, ResearchReview
from .source_reading import materialize_source_reading_state
from .model_actions import (
    build_model_action_definitions,
    decode_model_action_invocations,
    model_visible_capability_policy_json,
)
from .errors import (
    ConversationFailureStage,
    ConversationInputError,
    ConversationOperationConflict,
    ConversationOperationNotFound,
    ConversationFailure,
)
from .journal import (
    FileInteractionJournal,
    InMemoryInteractionJournal,
)
from .knowledge_save import ConversationKnowledgeSaveUseCase
from .models import (
    ModelCallDisposition,
    ActionObservation,
    ArtifactSourceInput,
    AcceptedArtifactToolRequest,
    AcceptedExperimentToolRequest,
    AcceptedPythonToolRequest,
    AgentDelegationProposal,
    CommittedUsage,
    ConversationInteractionMode,
    ConversationKnowledgeSaveOperation,
    ConversationMessage,
    ConversationTurnView,
    DecisionFeedback,
    ActionProtocolDiagnostic,
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
    PrepareKnowledgeDeleteArguments,
    ReadActionOutputArguments,
    ReviewCriteria,
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
from .interaction_intent import (
    AdmittedInteractionIntent,
    derive_interaction_intent,
    ungrounded_background_requirement_feedback,
)
from .interaction_intent import ungrounded_criteria_feedback
from .verification_admission import observed_receipts
from .working_plan import (
    active_working_plan_step_id,
    admit_continue_turn_progress,
    admit_new_plan_interaction_mode,
    admit_plan_wait_boundary,
    admit_working_plan,
    complete_working_plan,
    required_plan_review_feedback,
    supersede_pending_working_plan,
)


_KNOWLEDGE_SAVE_CAPABILITY = "prepare_conversation_knowledge_save"
_VERIFICATION_CAPABILITY = "verify_interaction_draft"
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
        budget_policy: LoopBudgetPolicy | None = None,
        journal: InMemoryInteractionJournal | None = None,
        action_diagnostics_reveal_field_names: bool = False,
        policy_decisions: PolicyDecisionRecorder | None = None,
        experiment_deployment: RetrievalDeployment | None = None,
        experiment_model_capacity_valid: bool = False,
        experiment_completion: ResearchExperimentCompletionUseCase | None = None,
        python_authorization: PythonExecutionAuthorization | None = None,
        answer_result: DirectAnswerResult | None = None,
    ) -> None:
        self._model_client = model_client
        self._policy_decisions = policy_decisions or PolicyDecisionRecorder()
        self._tool_port = tool_port
        self._agent_port = agent_port
        self._artifact_port = artifact_port
        self._artifact_search = artifact_search
        self._experiment_deployment = experiment_deployment
        self._experiment_model_capacity_valid = experiment_model_capacity_valid
        self._experiment_completion = experiment_completion
        self._python_authorization = python_authorization
        self._answer_result = answer_result or ClaimAnswerResult(AnswerResultConfig())
        self._knowledge_writer = knowledge_writer
        self._knowledge_reader = knowledge_reader
        self._knowledge_lifecycle = knowledge_lifecycle
        self._action_diagnostics_reveal_field_names = (
            action_diagnostics_reveal_field_names
        )
        self._run_conversation_ids: dict[str, str] = {}
        if agent_port is not None and artifact_port is None:
            raise ValueError(
                "agent delegation requires the canonical Artifact read port"
            )
        self._budget_policy = budget_policy or LoopBudgetPolicy()
        self._journal = journal or InMemoryInteractionJournal()
        self._history = HistoryCompactor(
            journal=self._journal, artifacts=self._artifact_port,
            generate=lambda request, run_ref: self._generate_model(request, run_ref=run_ref, usage=self._journal.get(run_ref).usage),
            record_usage=self._record_model_usage,
        ) if self._artifact_port is not None and self._model_client is not None else None
        self._knowledge_save = ConversationKnowledgeSaveUseCase(
            writer=self._knowledge_writer,
            journal=self._journal,
        )

    def respond(
        self,
        *,
        conversation_id: str,
        messages: list[ConversationMessage],
        principal: AuthenticatedPrincipal,
        source_platform: str = "web",
        interaction_run_ref: str | None = None,
        interaction_mode: ConversationInteractionMode = "default",
        input_artifact_refs: tuple[ResourceRef, ...] = (),
    ) -> ConversationTurnView:
        run_ref = interaction_run_ref or f"irun_{uuid4().hex[:16]}"
        with (self._journal.exclusive_conversation(conversation_id, principal),
              self._journal.exclusive_run(run_ref)):
            try:
                return self._respond_locked(
                    conversation_id=conversation_id,
                    messages=messages,
                    principal=principal,
                    source_platform=source_platform,
                    interaction_run_ref=run_ref,
                    interaction_mode=interaction_mode,
                    input_artifact_refs=input_artifact_refs,
                )
            except ConversationFailure as error:
                trace = self._journal.get(run_ref)
                research_bound = trace is not None and trace.python_profile_digest is not None
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
                                review_criteria=trace.review_criteria, working_plan=trace.working_plan,
                                message=str(error),
                            )
                raise

    def _respond_locked(
        self,
        *,
        conversation_id: str,
        messages: list[ConversationMessage],
        principal: AuthenticatedPrincipal,
        source_platform: str = "web",
        interaction_run_ref: str | None = None,
        interaction_mode: ConversationInteractionMode = "default",
        input_artifact_refs: tuple[ResourceRef, ...] = (),
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

        run_ref = interaction_run_ref or f"irun_{uuid4().hex[:16]}"
        prior = self._journal.get(run_ref)
        new_run = prior is None
        if prior is not None and prior.input_artifact_refs != tuple(input_artifact_refs):
            raise ConversationOperationConflict("interaction_run_ref is bound to different input_artifact_refs")
        if prior is not None:
            self._require_trace_scope(
                prior,
                principal,
                action="conversation_run_resume",
            )
        if prior is not None and prior.conversation_id != conversation_id:
            raise ConversationOperationConflict("interaction_run_ref is bound to a different conversation")
        if prior is None:
            if any(
                item.answer_result_binding != self._answer_result.config
                for item in self._journal.conversation_traces(conversation_id, principal)
            ):
                raise ConversationOperationConflict("同一对话不能更换回答模块或核验装配，请使用独立对话。")
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
            authorization = self._python_authorization
            analysis_bound = (authorization is not None and authorization.authorized_principal == principal
                              and authorization.conversation_id == conversation_id)
            if analysis_bound:
                if datetime.now(UTC) >= authorization.expires_at:
                    raise PermissionError("Python分析授权已过期")
                if any(item.python_authorization_digest is not None
                       and item.python_authorization_digest != authorization.authorization_digest
                       for item in self._journal.conversation_traces(conversation_id, principal)):
                    raise PermissionError("同一分析对话不能更换授权身份并重置额度")
            now = datetime.now(UTC)
            prior = InteractionTrace(
                answer_result_binding=self._answer_result.config,
                interaction_run_ref=run_ref, conversation_id=conversation_id, principal=principal,
                messages=tuple(messages), input_artifact_refs=tuple(input_artifact_refs), inputs=tuple(sources),
                usage=CommittedUsage(provider_usage_complete=True, model_calls=0, input_tokens=0, output_tokens=0),
                deployment_digest=deployment.deployment_digest if bound else None,
                python_authorization_digest=authorization.authorization_digest if analysis_bound else None,
                run_deadline_at=(min(now + timedelta(seconds=authorization.turn_timeout_seconds), authorization.expires_at)
                                 if analysis_bound else now + timedelta(seconds=deployment.limits.run_timeout_seconds)
                                 if bound else None),
                max_execution_seconds=(authorization.max_execution_seconds if analysis_bound
                                       else deployment.limits.max_execution_seconds if bound else None),
            )
            self._journal.put(prior)
        elif prior.deployment_digest is not None and (
            self._experiment_deployment is None or self._experiment_deployment.deployment_digest != prior.deployment_digest):
            raise PermissionError("original experiment deployment is no longer available")
        if prior.python_authorization_digest is not None:
            self._require_python_authorization(prior)
        if prior.answer_result_binding != self._answer_result.config:
            raise ConversationOperationConflict("原运行的回答模块绑定缺失或与本次装配不同，请使用新对话进行独立运行。")
        if prior.deployment_digest is not None and current_claims(prior.inputs) is not None:
            raise ValueError("旧 claim 研究记录不能作为初步实验交付的提交；请使用新的准备身份。")
        working_plan = (
            prior.working_plan
            if prior is not None and prior.working_plan is not None
            else self._journal.working_plan(conversation_id, principal)
        )
        self._run_conversation_ids[run_ref] = conversation_id
        if prior is not None and tuple(messages) != prior.messages:
            raise ConversationOperationConflict(
                "interaction_run_ref is already bound to different user input"
            )
        if prior is not None and prior.knowledge_save_operation is not None:
            return self._knowledge_save.turn_view(
                conversation_id,
                run_ref,
                prior.knowledge_save_operation,
            )
        if prior is not None and prior.knowledge_delete_command_ref is not None:
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
        if prior is not None and prior.final_message is not None:
            resources = ()
            if prior.deployment_digest is not None and prior.final_message.disposition == "answer":
                if self._experiment_completion is None:
                    raise ConversationFailure("实验完成校验不可用，无法恢复已完成回答。")
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
        inputs: list[InteractionInput]
        if not new_run:
            inputs = list(prior.inputs)
        elif working_plan is not None and not self._journal.plan_result_delivered(
            conversation_id, principal, working_plan,
        ):
            inputs = [*prior.inputs, *self._journal.working_plan_observations(
                conversation_id,
                principal,
                working_plan,
            )]
        else:
            inputs = list(prior.inputs)
        if new_run and prior.python_authorization_digest is not None:
            observed = {item.action_id for item in inputs if isinstance(item, ActionObservation)}
            for observation in self._journal.analysis_observations(prior):
                if observation.action_id not in observed:
                    inputs.append(observation)
                    observed.add(observation.action_id)
        # The review owner checks its exact original input and current version.
        # Restarting this invocation does not change those persisted facts.
        source_review_start_index = 0
        execution_order = list(prior.execution_order if prior else ())
        concurrent_batches = list(prior.concurrent_batches if prior else ())
        context_composition = list(prior.context_composition if prior else ())
        usage = prior.usage if prior else CommittedUsage(
            provider_usage_complete=True,
            model_calls=0,
            input_tokens=0,
            output_tokens=0,
        )
        review_criteria = prior.review_criteria if prior else None
        inputs, usage, execution_order = self._recover_accepted_requests(
            run_ref=run_ref, principal=principal, owner=owner, conversation_id=conversation_id,
            source_platform=source_platform, inputs=inputs, usage=usage, execution_order=execution_order,
        )
        if (
            prior.deployment_digest is not None and pending_experiment_submission(inputs) is not None
            and review_criteria is not None
            and (not review_criteria.plan_review_required or working_plan is not None)
            and self._unread_offloaded_resource(inputs) is None
        ):
            if self._experiment_completion is None:
                raise ConversationFailure("实验交付服务不可用，不能恢复报告提交。")
            try:
                self._experiment_completion.validate(self._journal.get(run_ref))
            except DeliveryIncomplete as error:
                inputs.append(self._experiment_completion_feedback(error))
                self._commit(
                    run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
                    context_composition, review_criteria=review_criteria, working_plan=working_plan,
                )
            else:
                return self._complete_experiment_answer(
                    run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
                    context_composition, review_criteria=review_criteria, working_plan=working_plan,
                )
        background_continuation_requested = False
        if review_criteria is None:
            intent, derivation_responses, derivation_feedback = (
                self._derive_interaction_intent(messages, run_ref=run_ref, usage=usage)
            )
            review_criteria = intent.review_criteria
            background_continuation_requested = (
                intent.background_continuation_requested
            )
            for derivation_response in derivation_responses:
                usage = self._record_model_usage(usage, derivation_response)
            inputs.extend(derivation_feedback)
            if (self._answer_result.verification_enabled and prior.deployment_digest is None
                    and review_criteria.requires_review and not self._verification_available()):
                inputs.append(self._verification_unavailable_feedback())
                review_criteria = ReviewCriteria()
            elif (
                review_criteria.ungrounded_spans and not review_criteria.requires_review
            ):
                inputs.append(ungrounded_criteria_feedback(review_criteria))
            if not intent.background_requirement_grounded:
                inputs.append(ungrounded_background_requirement_feedback())
            if (
                working_plan is not None
                and review_criteria.final_result_required
                and any(step.status == "pending" for step in working_plan.steps)
            ):
                working_plan = supersede_pending_working_plan(working_plan)
            self._commit(
                run_ref,
                principal,
                messages,
                inputs,
                usage,
                execution_order,
                concurrent_batches,
                context_composition,
                review_criteria=review_criteria,
                working_plan=working_plan,
            )
        if background_continuation_requested:
            return self._background_continuation_unavailable(
                conversation_id=conversation_id,
                run_ref=run_ref,
                principal=principal,
                messages=messages,
                inputs=inputs,
                usage=usage,
                execution_order=execution_order,
                concurrent_batches=concurrent_batches,
                context_composition=context_composition,
                review_criteria=review_criteria,
                working_plan=working_plan,
            )

        while True:
            trace = self._journal.get(run_ref)
            usage = trace.usage
            capabilities = self._effective_capabilities(run_ref=run_ref)
            trace = self._model_journal_call("agent_interaction_turn", self._journal.recover_model_response_originals,
                ExecutionScope(principal=principal, execution_id=run_ref, thread_id=conversation_id))
            usage = trace.usage
            evidence_selection, selected_ids = self._current_research_selection(run_ref, inputs, review_criteria)
            decision = self._pending_final_candidate(inputs)
            if decision is None and isinstance(self._answer_result, ClaimAnswerResult):
                recovery = self._answer_result.recovery_steps(inputs=inputs, messages=messages,
                    criteria=review_criteria, reuse_start_index=source_review_start_index)
                response_value = None
                while True:
                    try:
                        step = recovery.send(response_value)
                    except StopIteration as finished:
                        decision = finished.value
                        break
                    if isinstance(step, StructuredModelRequest):
                        response_value = self._generate_model(step, run_ref=run_ref, usage=usage).value
                        usage = self._journal.get(run_ref).usage
                    else:
                        inputs.append(step)
                        response_value = None
                        self._commit(run_ref, principal, messages, inputs, usage, execution_order,
                            concurrent_batches, context_composition, review_criteria=review_criteria, working_plan=working_plan)
            model_response = None
            protocol_feedback = None
            paid_main = any(not record.consumed and record.response_refs
                and record.operation == "agent_interaction_turn" for record in self._journal.get(run_ref).model_decisions)
            if decision is None and not paid_main:
                if trace.run_deadline_at is not None and datetime.now(UTC) >= trace.run_deadline_at:
                    return self._fail_closed_limitation(
                        conversation_id, run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition, review_criteria=review_criteria,
                        working_plan=working_plan, message="本次任务运行时限已到；已提交产物保留，未完成部分不计为完整交付。",
                    )
                repeated_feedback = self._repeated_action_feedback(tuple(inputs))
                if repeated_feedback is not None:
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
                        review_criteria=review_criteria,
                        working_plan=working_plan,
                        message=(
                            "模型连续提交了同一类无效动作，本次交互已安全停止；"
                            "所有被拒绝的动作均未执行。"
                        ),
                    )
                if (
                    usage.model_turns >= self._budget_policy.max_model_turns
                    or self._remaining_model_tokens(run_ref, usage) <= 0
                    or (
                        self._budget_policy.max_tool_calls > 0
                        and usage.tool_calls >= self._budget_policy.max_tool_calls
                    )
                ):
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
                        review_criteria,
                        working_plan,
                    )
            if decision is None:
                decision, model_response, composition, protocol_feedback = self._decide(
                    run_ref=run_ref, messages=messages,
                    capabilities=self._model_visible_capabilities_for_turn(capabilities, inputs, run_ref=run_ref),
                    inputs=inputs, usage=usage, review_criteria=review_criteria,
                    turn_index=usage.model_turns, working_plan=working_plan,
                    interaction_mode=interaction_mode, evidence_selection=evidence_selection,
                    selected_ids=selected_ids, source_review_start_index=source_review_start_index)
                usage = self._record_model_usage(self._journal.get(run_ref).usage, model_response, model_turn=True, run_ref=run_ref)
                if not any(item.turn_index == composition.turn_index for item in context_composition):
                    context_composition.append(composition)
                self._commit(run_ref, principal, messages, inputs, usage, execution_order,
                    concurrent_batches, context_composition, review_criteria=review_criteria,
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
                    review_criteria=review_criteria,
                    working_plan=working_plan,
                )
                continue
            assert decision is not None
            if isinstance(decision, ResearchEvidenceSelection):
                try:
                    validate_research_selection(decision, review_criteria, current_claims(inputs))
                    selected_citation_ids(decision.references, inputs)
                except (CitationBindingError, ValueError) as error:
                    inputs.append(DecisionFeedback(action_id=model_response.action_invocations[0].call_id,
                        reason_code="research_selection_invalid", message=str(error),
                        required_repair="覆盖全部requirements且每项恰好一次，只关联当前claim与已返回引用；本次选择未接纳。"))
                else:
                    self._accept_research_selection(run_ref, decision, inputs, review_criteria)
                    if decision.next_step == "acquire":
                        inputs.append(DecisionFeedback(action_id=model_response.action_invocations[0].call_id,
                            reason_code="research_needs_evidence", message=decision.reason,
                            required_repair="根据缺口调用当前合法工具；取得新证据后重新选证。"))
                    elif decision.next_step == "limit":
                        decision = FinalMessage(disposition="limitation", segments=(ConversationAnswerSegment(text=decision.reason),))
                if isinstance(decision, ResearchEvidenceSelection):
                    self._commit(run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition, review_criteria=review_criteria, working_plan=working_plan)
                    continue
            if self._answer_result.handles_submission(decision):
                checks = self._answer_result.submission_steps(
                    decision, inputs=inputs, messages=messages, criteria=review_criteria,
                    reference=ResourceRef(
                        resource_id=f"{run_ref}:research", resource_type="conversation_research", owner=principal,
                    ), selected_ids=selected_ids, reuse_start_index=source_review_start_index,
                )
                response_value = None
                resolution = None
                while True:
                    try:
                        step = checks.send(response_value)
                    except StopIteration as finished:
                        resolution = finished.value
                        break
                    self._commit(
                        run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition,
                        review_criteria=review_criteria, working_plan=working_plan,
                    )
                    if isinstance(step, StructuredModelRequest):
                        if self._remaining_model_tokens(run_ref, usage) <= 0:
                            checks.close()
                            break
                        response = self._generate_model(step, run_ref=run_ref, usage=usage)
                        usage = self._record_model_usage(usage, response)
                        response_value = response.value
                    else:
                        inputs.append(step)
                        response_value = None
                if resolution is None or resolution.final is None:
                    self._commit(
                        run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition,
                        review_criteria=review_criteria, working_plan=working_plan,
                    )
                    continue
                decision = resolution.final
            if isinstance(decision, FinalMessage):
                if (
                    review_criteria.plan_review_required
                    and working_plan is None
                ):
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
                        review_criteria=review_criteria,
                        working_plan=working_plan,
                    )
                    continue
                if (
                    decision.disposition != "answer"
                    and self._has_failed_action_observation(inputs)
                ):
                    unread = self._unread_offloaded_resource(inputs)
                    if unread is not None:
                        inputs.append(self._unread_output_feedback(decision, unread))
                        self._commit(
                            run_ref,
                            principal,
                            messages,
                            inputs,
                            usage,
                            execution_order,
                            concurrent_batches,
                            context_composition,
                            review_criteria=review_criteria,
                            working_plan=working_plan,
                        )
                        continue
                    self._commit(
                        run_ref,
                        principal,
                        messages,
                        inputs,
                        usage,
                        execution_order,
                        concurrent_batches,
                        context_composition,
                        review_criteria=review_criteria,
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
                    inputs.append(SubmittedFinal(
                        action_id=f"final-{usage.model_turns}",
                        resource_ref=ResourceRef(
                            resource_id=f"{run_ref}:final", resource_type="conversation_final",
                            owner=principal, revision=usage.model_turns,
                        ),
                        final=decision,
                    ))
                    # Save the real report and billed response before checking or publishing files.
                    self._commit(
                        run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition,
                        review_criteria=review_criteria, working_plan=working_plan,
                    )
                    unread = self._unread_offloaded_resource(inputs)
                    if unread is not None:
                        inputs.append(self._unread_output_feedback(decision, unread))
                    else:
                        if self._experiment_completion is None:
                            raise ConversationFailure("实验交付服务不可用，不能检查报告提交。")
                        try:
                            self._experiment_completion.validate(self._journal.get(run_ref))
                        except DeliveryIncomplete as error:
                            inputs.append(self._experiment_completion_feedback(error))
                        else:
                            return self._complete_experiment_answer(
                                run_ref, principal, messages, inputs, usage, execution_order,
                                concurrent_batches, context_composition,
                                review_criteria=review_criteria, working_plan=working_plan,
                            )
                    self._commit(
                        run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition,
                        review_criteria=review_criteria, working_plan=working_plan,
                    )
                    continue
                if decision.disposition == "answer" and self._pending_final_candidate(inputs) != decision:
                    inputs.append(SubmittedFinal(
                        action_id=f"final-{usage.model_turns}",
                        resource_ref=ResourceRef(resource_id=f"{run_ref}:final", resource_type="conversation_final",
                                                 owner=principal, revision=usage.model_turns),
                        final=decision,
                    ))
                    self._commit(
                        run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition,
                        review_criteria=review_criteria, working_plan=working_plan,
                    )
                result_feedback = self._answer_result.validate_final(
                    decision, inputs, reuse_start_index=source_review_start_index,
                    requires_review=review_criteria.requires_review, experiment_run=prior.deployment_digest is not None,
                )
                if result_feedback is not None:
                    inputs.append(result_feedback)
                    self._commit(
                        run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition,
                        review_criteria=review_criteria, working_plan=working_plan,
                    )
                    continue
                if (self._answer_result.needs_direct_verification(review_criteria, inputs)
                        and decision.disposition == "answer"):
                    verified, result, usage = (
                        self._verify_before_send(
                            decision,
                            review_criteria=review_criteria,
                            verification_inputs=tuple(inputs),
                            conversation_id=conversation_id,
                            run_ref=run_ref,
                            principal=principal,
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
                            review_criteria=review_criteria,
                            working_plan=working_plan,
                        )
                        continue
                    decision = verified
                unread = self._unread_offloaded_resource(inputs)
                if unread is not None:
                    inputs.append(self._unread_output_feedback(decision, unread))
                    self._commit(
                        run_ref,
                        principal,
                        messages,
                        inputs,
                        usage,
                        execution_order,
                        concurrent_batches,
                        context_composition,
                        review_criteria=review_criteria,
                        working_plan=working_plan,
                    )
                    continue
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
                    review_criteria=review_criteria,
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
                    review_criteria=review_criteria,
                    working_plan=working_plan,
                )
                continue

            previous_plan = working_plan
            if decision.working_plan is not None:
                result_delivered = (
                    working_plan is not None
                    and self._journal.plan_result_delivered(
                        conversation_id, principal, working_plan,
                    )
                )
                mode_feedback = admit_new_plan_interaction_mode(
                    decision,
                    current=working_plan,
                    result_delivered=result_delivered,
                    interaction_mode=interaction_mode,
                    unsafe_execution_started=(
                        self._unsafe_execution_started_before_plan(
                            execution_order,
                            inputs,
                            capabilities,
                        )
                    ),
                )
                if mode_feedback is not None:
                    inputs.append(mode_feedback)
                    self._commit(
                        run_ref,
                        principal,
                        messages,
                        inputs,
                        usage,
                        execution_order,
                        concurrent_batches,
                        context_composition,
                        review_criteria=review_criteria,
                        working_plan=working_plan,
                    )
                    continue
                feedback, admitted_plan = admit_working_plan(
                    decision.working_plan,
                    current=working_plan,
                    inputs=tuple(inputs),
                    wait_for_user=decision.wait_for_user,
                    result_delivered=result_delivered,
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
                        review_criteria=review_criteria,
                        working_plan=working_plan,
                    )
                    continue
                working_plan = admitted_plan
                if decision.working_plan_call_id is not None:
                    self._commit(run_ref, principal, messages, inputs, usage, execution_order,
                        concurrent_batches, context_composition, review_criteria=review_criteria,
                        working_plan=working_plan, call_dispositions=(ModelCallDisposition(
                            call_id=decision.working_plan_call_id, operation="working_plan", status="accepted",
                            plan_id=working_plan.plan_id, plan_revision=working_plan.revision),))
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
                    review_criteria=review_criteria,
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
                    review_criteria=review_criteria,
                    working_plan=working_plan,

                )
                return ConversationTurnView(
                    interaction_run_ref=run_ref,
                    conversation_id=conversation_id,
                    disposition="plan_ready",
                    message=ConversationMessage(
                        role="assistant",
                        content=(
                            decision.message.strip()
                            or "计划已准备好，等待你调整或确认后继续。"
                        ),
                    ),
                    working_plan=working_plan,
                )

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
                        review_criteria=review_criteria,
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
                    review_criteria=review_criteria,
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
                        review_criteria=review_criteria,
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
                        review_criteria=review_criteria,
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
                    review_criteria=review_criteria,
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
                review_criteria=review_criteria,
                working_plan=working_plan,
            )
            if self._journal.get(run_ref).python_authorization_digest is not None:
                self._admit_research_model_call(run_ref, usage)
            latest = self._journal.get(run_ref)
            if decision.actions and (self._remaining_model_tokens(run_ref, latest.usage) <= 0
                    or (latest.run_deadline_at is not None and datetime.now(UTC) >= latest.run_deadline_at)):
                return self._budget_exhausted(conversation_id, run_ref, principal, messages, inputs,
                    latest.usage, execution_order, concurrent_batches, context_composition, review_criteria, working_plan)
            results, usage, concurrent = self._execute_actions(
                decision,
                conversation_id=conversation_id,
                run_ref=run_ref,
                principal=principal,
                owner=owner,
                source_platform=source_platform,
                usage=usage,
                committed_action_ids=frozenset(execution_order),
                committed_inputs=tuple(inputs),
                plan_step_id=active_working_plan_step_id(working_plan),
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
                review_criteria=review_criteria,
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
            review_criteria,
            working_plan,
        )

    @staticmethod
    def _experiment_completion_feedback(error: DeliveryIncomplete) -> DecisionFeedback:
        return DecisionFeedback(
            action_id="experiment-delivery", reason_code="experiment_delivery_incomplete",
            message=json.dumps([gap.model_dump(mode="json") for gap in error.gaps], ensure_ascii=False),
            required_repair="沿实际缺口继续执行或补齐本任务成果；现有实验和原稿保留，不能仅改写报告宣称完成。",
        )

    def _complete_experiment_answer(
        self, run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
        context_composition, *, review_criteria, working_plan,
    ):
        if self._experiment_completion is None:
            raise ConversationFailure("实验完成校验不可用，不能完成回答。")
        submission = experiment_submission(self._journal.get(run_ref))
        # Persist the exact submission and its usage before completion checks.
        self._commit(
            run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
            context_composition, review_criteria=review_criteria, working_plan=working_plan,
        )
        try:
            self._experiment_completion.validate(self._journal.get(run_ref))
        except DeliveryIncomplete as error:
            # This boundary has no new model call. A missing physical result cannot be
            # converted into an answer by a previously successful semantic review.
            return self._fail_closed_limitation(
                self._run_conversation_ids[run_ref], run_ref, principal, messages, inputs, usage,
                execution_order, concurrent_batches, context_composition,
                review_criteria=review_criteria, working_plan=working_plan,
                message="实验交付尚未完整：" + str(error),
            )
        final = submission.final
        if working_plan is not None:
            working_plan = complete_working_plan(working_plan, inputs=tuple(inputs))
        self._commit(
            run_ref, principal, messages, inputs, usage, execution_order, concurrent_batches,
            context_composition, review_criteria=review_criteria, working_plan=working_plan, final_message=final,
        )
        return ConversationTurnView(
            interaction_run_ref=run_ref, conversation_id=self._run_conversation_ids[run_ref],
            disposition="answer", message=ConversationMessage(role="assistant", content=final.message),
            working_plan=working_plan,
        )

    def _append_artifact_sources(self, run_ref, inputs):
        if self._artifact_port is None:
            return
        trace = self._journal.get(run_ref)
        existing = set(input_resource_refs(inputs))
        refs = list(self._journal.readable_resource_refs(trace))
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
        for ref in dict.fromkeys(refs):
            if ref in checkpoint_refs(trace):
                continue
            if ref not in existing:
                try:
                    resource = self._artifact_port.resource_item(ref, principal=trace.principal, owner=trace.principal)
                except FileNotFoundError:
                    action_id = f"artifact-unavailable:{ref.resource_id}:{ref.revision}"
                    if not any(isinstance(item, DecisionFeedback) and item.action_id == action_id for item in inputs):
                        inputs.append(DecisionFeedback(action_id=action_id, reason_code="artifact_unavailable",
                            message=f"已提交的原件当前不可用：{ref.model_dump_json()}。未重新执行或替换原件。",
                            required_repair="根据仍可用的原件继续，或如实说明缺失；恢复原件后可再次读取，不能猜测其内容。"))
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
            pending_python = (
                isinstance(accepted, AcceptedPythonToolRequest)
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
            if was_observed and not (pending_python or pending_experiment):
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
                message="A knowledge delete proposal must be the only action in its turn.",
                repairable_fields=("actions",),
                immutable_fields=("action_id",),
                required_repair=(
                    "Propose only prepare_knowledge_delete so its canonical command can be confirmed."
                ),
            ), None
        if self._knowledge_reader is None or self._knowledge_lifecycle is None:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="capability_missing",
                message="The governed knowledge delete capability is unavailable.",
                immutable_fields=("action_id",),
                required_repair="Explain the limitation and do not claim deletion was prepared.",
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
                message="The target knowledge item was not observed in the caller's personal knowledge.",
                repairable_fields=("target_knowledge_item_id",),
                immutable_fields=("action_id", "reason"),
                required_repair=(
                    "Call list_personal_knowledge, select one returned knowledge_item_id, "
                    "then prepare the delete as a separate action."
                ),
            ), None
        return None, arguments

    @staticmethod
    def _invalid_special_arguments(action, error):
        return DecisionFeedback(
            action_id=action.action_id,
            reason_code="invalid_arguments",
            message=str(error),
            repairable_fields=("arguments",),
            immutable_fields=("action_id", "tool_name"),
            required_repair="Revise only the arguments to satisfy the declared capability schema.",
        )

    @staticmethod
    def _application_operation_feedback(action, error):
        return DecisionFeedback(
            action_id=action.action_id,
            reason_code="application_operation_rejected",
            message=str(error),
            immutable_fields=("action_id", "tool_name"),
            required_repair=(
                "Do not claim the operation started. Explain the rejection or ask for "
                "the missing business input without changing the user's goal."
            ),
            disposition="fail_closed",
        )

    @staticmethod
    def _knowledge_delete_turn_view(conversation_id, run_ref, operation):
        messages = {
            "awaiting_confirmation": "请确认是否删除该知识条目。确认前不会发生删除。",
            "rejected": "已取消删除，知识条目保持不变。",
            "executed": "该知识条目已删除。",
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

    def _derive_interaction_intent(self, messages, *, run_ref, usage):
        """Derive delivery requirements and the frozen verification standard.

        Runs once per interaction, before the first decision turn, so the
        standard exists before there is any answer to measure against it. A
        derivation failure degrades to "not a review request" rather than to a
        runtime-invented criterion.
        """
        trace = self._journal.get(run_ref)
        research_bound = trace.python_profile_digest is not None
        try:
            return derive_interaction_intent(
                self._model_client, messages=messages,
                generate=lambda request: self._generate_model(request, run_ref=run_ref, usage=self._journal.get(run_ref).usage),
                propagate_revision_failures=research_bound,
                deadline_at=trace.run_deadline_at if research_bound else None,
                remaining_tokens=self._remaining_model_tokens(run_ref, usage) if research_bound else None,
            )
        except ModelCapacityRefused as error:
            raise self._capacity_failure(error) from error
        except ConversationFailure:
            raise
        except ModelInvocationUnavailable as error:
            if research_bound:
                raise self._model_failure(
                    error, message="研究意图模型调用未完成；已保留已知消费。",
                    failure_stage="provider_request", component="conversation_intent_admission",
                ) from error
            return AdmittedInteractionIntent(), (), ()
        except StructuredOutputFailure as error:
            if research_bound:
                raise self._model_failure(
                    error, message="研究意图的结构化输出未满足协议；已保留已知消费。",
                    failure_stage="provider_structured_decode", component="conversation_intent_admission",
                ) from error
            return AdmittedInteractionIntent(), (), ()

    def _background_continuation_unavailable(
        self,
        *,
        conversation_id,
        run_ref,
        principal,
        messages,
        inputs,
        usage,
        execution_order,
        concurrent_batches,
        context_composition,
        review_criteria,
        working_plan,
    ):
        feedback = DecisionFeedback(
            action_id="background-continuation",
            reason_code="capability_missing",
            message="Background continuation is not a supported application capability.",
            immutable_fields=("messages",),
            required_repair=(
                "Explain that work can run only in the current Conversation; do not "
                "claim background work started."
            ),
            disposition="fail_closed",
        )
        inputs.append(feedback)
        final = FinalMessage(
            disposition="limitation",
            segments=(ConversationAnswerSegment(text="当前不支持在本次响应结束后继续运行、稍后查询或调整的后台任务；"
                "系统没有启动后台工作。你可以改为在当前对话中继续完成。"),),
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
            review_criteria=review_criteria,
            final_message=final,
            working_plan=working_plan,
        )
        return ConversationTurnView(
            interaction_run_ref=run_ref,
            conversation_id=conversation_id,
            disposition="limitation",
            message=ConversationMessage(role="assistant", content=final.message),
            working_plan=working_plan,
        )

    def _record_model_usage(self, usage, response, *, model_turn=False, run_ref=None):
        if response.response_records:
            if not model_turn:
                return usage
            if run_ref is None:
                raise ConversationOperationConflict("主模型决策计数缺少运行绑定")
            invocation_id = response.response_records[-1].invocation_id
            record = next((record for record in self._journal.get(run_ref).model_decisions
                           if record.invocation_id == invocation_id), None)
            if record is None or record.turn_index is None:
                raise ConversationOperationConflict("主模型决策计数缺少已存响应轮次")
            return usage.model_copy(update={"model_turns": max(usage.model_turns, record.turn_index)})
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

    def _verification_available(self) -> bool:
        """Whether this deployment can actually verify a review answer.

        Checked before the criteria are frozen, so a deployment without the
        verifier registered answers as an ordinary request instead of deriving a
        standard it has no way to enforce.
        """
        if self._tool_port is None:
            return False
        validation = self._tool_port.validate_workflow_call(
            _VERIFICATION_CAPABILITY,
            {},
        )
        return validation.status != "capability_missing"

    @staticmethod
    def _verification_unavailable_feedback():
        return DecisionFeedback(
            action_id="interaction_turn",
            reason_code="verification_capability_unavailable",
            message=(
                "This request states review requirements, but the semantic "
                "verification capability is not available in this deployment."
            ),
            immutable_fields=("messages",),
            required_repair=(
                "Answer the request directly and state that the answer was not "
                "verified against the stated requirements. Never claim that a "
                "review or verification was performed."
            ),
            disposition="fail_closed",
        )

    @staticmethod
    def _has_failed_action_observation(inputs) -> bool:
        return any(
            isinstance(item, ActionObservation)
            and item.kind == "tool_result"
            and (item.status == "failed" or item.payload.get("ok") is False)
            for item in inputs
        )

    @staticmethod
    def _unread_output_feedback(decision, resource_id: str) -> DecisionFeedback:
        """Reject the exit, not the conclusion.

        What the omitted part says is the model's call, including that it does not
        contain what was asked for. What is not the model's call is ending the turn
        without looking.
        """

        return DecisionFeedback(
            action_id="interaction_turn",
            reason_code="offloaded_output_unread",
            message=(
                f"This turn cannot end as {decision.disposition!r} while the output of "
                "an earlier call is still unread. Its excerpt omitted part of the "
                "output, and the omitted part is held by this run, not by the user."
            ),
            repairable_fields=("disposition", "message"),
            required_repair=(
                "Call search_action_output or read_artifact for resource_id "
                f"{resource_id!r} with the selected tool's keyword or start_line to locate what "
                "is missing. If the omitted part turns out not to contain it, say so "
                "from what the windows showed."
            ),
        )

    @staticmethod
    def _unread_offloaded_resource(inputs) -> str | None:
        """The output this turn fetched, offloaded, and never came back for.

        A turn that fetched an oversized output holds evidence the user does not
        have. Ending it as a clarification, limitation, or failure asks the user
        for something already sitting in this run's own artifact, so the omitted
        part has to be read, or found absent, before that exit is honest. Only a
        succeeded observation counts: a failed call's offloaded error text is not
        evidence anyone was reaching for.
        """

        offloaded = ConversationService._unread_offloaded_resources(inputs)
        return next(iter(offloaded), None)

    @staticmethod
    def _unread_offloaded_resources(
        inputs,
    ) -> dict[str, tuple[str, str | None, dict[str, Any]]]:
        """Map artifact ids that have not yet yielded any readable window."""

        offloaded = ConversationService._offloaded_resources(inputs)
        for item in inputs:
            if (
                isinstance(item, ActionObservation)
                and item.capability_id in ARTIFACT_OUTPUT_CAPABILITIES
                and item.status == "succeeded"
            ):
                ref = ResourceRef.model_validate(item.payload["resource_ref"])
                binding = offloaded.get(ref.resource_id)
                if binding is not None and ResourceRef.model_validate(binding[2]) == ref:
                    offloaded.pop(ref.resource_id)
        return offloaded

    @staticmethod
    def _offloaded_resources(
        inputs,
    ) -> dict[str, tuple[str, str | None, dict[str, Any]]]:
        """Map every readable artifact id to the exact request that produced it.

        Reading one bounded window satisfies the minimum-look completion gate; it
        does not consume the artifact. Later windows, later model turns, and a
        resumed interaction must keep using the same immutable resource instead
        of re-running the producing tool.
        """

        offloaded: dict[
            str,
            tuple[str, str | None, dict[str, Any]],
        ] = {}
        for item in inputs:
            if not isinstance(item, ActionObservation):
                continue
            if item.capability_id in ARTIFACT_OUTPUT_CAPABILITIES:
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

    def _verify_before_send(
        self,
        decision,
        *,
        review_criteria,
        verification_inputs,
        conversation_id,
        run_ref,
        principal,
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
        try:
            cited_units = materialize_cited_draft(
                decision.segments, verification_inputs,
            )
        except CitationBindingError as exc:
            return None, _ActionResult(action_id, DecisionFeedback(
                action_id=action_id,
                action_name="final_message",
                reason_code=exc.reason_code,
                message=f"{exc}\n完整被拒稿及逐段引用见最新 submitted_final。",
                repairable_fields=("segments",),
                required_repair="修正引用或补读后重新提交草稿和对应引用，不要编造证据。",
            )), usage
        arguments = {
            "draft": decision.message,
            "success_criteria": list(review_criteria.criteria),
            "cited_units": [unit.model_dump(mode="json") for unit in cited_units],
            "source_reading_state": [
                state.model_dump(mode="json")
                for state in materialize_source_reading_state(
                    verification_inputs, verifier_capability_id=_VERIFICATION_CAPABILITY,
                )
            ],
        }
        expected_digest = canonical_digest({"tool_name": _VERIFICATION_CAPABILITY, "arguments": arguments})
        previous = next((item for item in reversed(verification_inputs) if isinstance(item, ActionObservation)
            and item.capability_id == _VERIFICATION_CAPABILITY and item.execution_request_digest == expected_digest), None)
        if previous is not None:
            receipts = observed_receipts((previous,), capability_names=frozenset({_VERIFICATION_CAPABILITY}))
            passed = receipts[-1] if receipts and receipts[-1].verdict == "passed" else None
            if passed is not None and decision.message != passed.verified_draft:
                raise ValueError("verified receipt must bind the submitted answer")
            return (decision if passed is not None else None), _ActionResult(previous.action_id, previous), usage
        if self._budget_policy.max_tool_calls > 0 and usage.tool_calls >= self._budget_policy.max_tool_calls:
            raise ConversationFailure("本次工具调用额度已用完，尚未启动新的核验。",
                reason_code="dependency_unavailable", failure_stage="application_budget")
        execution_scope = ExecutionScope(
            principal=principal,
            execution_id=run_ref,
            thread_id=conversation_id,
            task_id=action_id,
        )
        tool_result = self._tool_port.invoke_workflow(
            _VERIFICATION_CAPABILITY,
            arguments,
            execution_scope=execution_scope,
            tool_call_id=action_id,
            source_platform=source_platform,
        )
        result = _ActionResult(
            action_id,
            ActionObservation(
                kind="tool_result",
                action_id=action_id,
                capability_id=_VERIFICATION_CAPABILITY,
                status="succeeded" if tool_result.get("ok") else "failed",
                execution_request_digest=canonical_digest({
                    "tool_name": _VERIFICATION_CAPABILITY,
                    "arguments": arguments,
                }),
                payload=self._fit_observation_payload(
                    tool_result,
                    action_id=action_id,
                    capability_id=_VERIFICATION_CAPABILITY,
                    run_ref=run_ref,
                    owner=owner,
                    execution_scope=execution_scope,
                ),
            ),
        )
        usage = self._journal.get(run_ref).usage
        usage = usage.model_copy(update={"tool_calls": usage.tool_calls + 1})
        receipts = observed_receipts(
            (result.interaction_input,),
            capability_names=frozenset({_VERIFICATION_CAPABILITY}),
        )
        receipt = receipts[-1] if receipts else None
        verdict: VerificationVerdict | None = (
            receipt.verdict if receipt is not None else None
        )
        passed = receipt if verdict == "passed" else None
        if passed is None:
            return None, result, usage
        if decision.message != passed.verified_draft:
            raise ValueError("verified receipt must bind the submitted answer")
        return (decision, result, usage)

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
    def _pending_final_candidate(inputs):
        index = next((i for i in range(len(inputs) - 1, -1, -1) if isinstance(inputs[i], SubmittedFinal)), None)
        if index is None:
            return None
        later = inputs[index + 1:]
        if any(isinstance(item, (DecisionFeedback, ResearchClaims, ResearchReview)) for item in later):
            return None
        if any(isinstance(item, ActionObservation) and item.capability_id != _VERIFICATION_CAPABILITY for item in later):
            return None
        for item in later:
            if isinstance(item, ActionObservation) and item.capability_id == _VERIFICATION_CAPABILITY:
                receipts = observed_receipts((item,), capability_names=frozenset({_VERIFICATION_CAPABILITY}))
                if not receipts or receipts[-1].verdict != "passed":
                    return None
        return inputs[index].final

    @staticmethod
    def _research_selection_scope(inputs, criteria):
        current = current_claims(inputs)
        evidence = materialize_citation_context(materialize_interaction_inputs(inputs))
        digest = canonical_digest([item.model_dump(mode="json") for item in evidence
            if isinstance(item.observation, (ActionObservation, ArtifactSourceInput))])
        return current.resource_ref if current else None, digest, canonical_digest(criteria.model_dump(mode="json"))

    def _current_research_selection(self, run_ref, inputs, criteria):
        claim_ref, evidence_digest, criteria_digest = self._research_selection_scope(inputs, criteria)
        record = next((item for item in reversed(self._journal.get(run_ref).model_decisions)
                       if item.research_selection is not None), None)
        if (record is None or record.research_claim_ref != claim_ref
                or record.research_evidence_digest != evidence_digest or record.research_criteria_digest != criteria_digest):
            return None, frozenset()
        selection = record.research_selection
        return selection, selected_citation_ids(selection.references, inputs)

    def _accept_research_selection(self, run_ref, selection, inputs, criteria):
        trace = self._journal.get(run_ref)
        claim_ref, evidence_digest, criteria_digest = self._research_selection_scope(inputs, criteria)
        index = next(i for i in range(len(trace.model_decisions) - 1, -1, -1)
                     if trace.model_decisions[i].turn_index == trace.usage.model_turns)
        records = list(trace.model_decisions)
        record = records[index]
        records[index] = record.model_copy(update={"research_selection": selection,
            "research_claim_ref": claim_ref, "research_evidence_digest": evidence_digest,
            "research_criteria_digest": criteria_digest,
            "dispositions": (*record.dispositions, ModelCallDisposition(
                call_id=record.assistant.call_ids[0], operation="answer_result", status="accepted"))})
        self._journal.update(ExecutionScope(principal=trace.principal, execution_id=run_ref,
            thread_id=trace.conversation_id), lambda current: current.model_copy(update={
                "revision": current.revision + 1, "model_decisions": tuple(records)}))

    def _decide(self, **arguments):
        run_ref = arguments["run_ref"]
        while True:
            try:
                return self._decide_once(**arguments)
            except ConversationFailure as error:
                self._compact_after_capacity(error, run_ref)
                arguments["usage"] = self._journal.get(run_ref).usage
                arguments["capabilities"] = self._model_visible_capabilities_for_turn(
                    self._effective_capabilities(run_ref=run_ref), arguments["inputs"], run_ref=run_ref)

    def _decide_once(
        self,
        *,
        run_ref,
        messages,
        capabilities,
        inputs,
        usage,
        review_criteria,
        turn_index,
        working_plan,
        interaction_mode,
        evidence_selection: ResearchEvidenceSelection | None = None,
        selected_ids: frozenset[str] = frozenset(),
        source_review_start_index: int = 0,
    ):
        """Run one decision turn, and record what its input was made of.

        The composition is measured from the strings this method assembled rather
        than recomputed from the same sources, so the record cannot drift into
        describing an input that was never sent. It is read after ``generate``
        returns and takes no part in assembly, so the sealed context digest is
        unchanged by measuring.

        Scope is this loop's decision turns. The review-criteria derivation is a
        separate call with no capability projection, so folding it in here would
        put a turn with a structurally different input shape into the same series.
        """
        decision_trace = self._journal.get(run_ref)
        research_mode = self._answer_result.uses_claims(inputs,
            requires_review=review_criteria.requires_review,
            experiment_run=decision_trace.deployment_digest is not None)
        answer_actions = self._answer_result.action_definitions(inputs,
            requires_review=review_criteria.requires_review,
            experiment_run=decision_trace.deployment_digest is not None,
            selection=evidence_selection, selected_ids=selected_ids)
        action_definitions = build_model_action_definitions(capabilities,
            experiment_run=decision_trace.deployment_digest is not None, answer_actions=answer_actions)
        capability_projection = model_visible_capability_policy_json(capabilities, definitions=action_definitions)
        claims = current_claims(inputs)
        prompt_name = "conversation.action"
        system_content = build_interaction_system_prompt(
            capabilities,
            usage,
            review_criteria,
            budget_policy=self._visible_budget_policy(run_ref, usage),
            capability_projection=capability_projection,
            working_plan=working_plan,
            interaction_mode=interaction_mode,
            explicit_research_entry=decision_trace.deployment_digest is not None,
            wall_seconds_at_input=(
                max(0.0, (decision_trace.run_deadline_at - datetime.now(UTC)).total_seconds())
                if decision_trace.run_deadline_at is not None else None
            ),
            answer_result=self._answer_result,
        )
        if research_mode:
            system_content += get_prompt("conversation.research.evidence_selection").template
            if evidence_selection is not None and evidence_selection.next_step == "write":
                system_content += get_prompt("conversation.research.writer").template
        visible_messages = [{"role": "system", "content": system_content}]
        conversation_content = [item.model_dump(mode="json") for item in messages]
        visible_messages.extend(conversation_content)
        typed_inputs_content = ""
        model_history = ()
        if inputs:
            review = applicable_research_review(claims, inputs, reuse_start_index=source_review_start_index)
            latest_submission_index = next((index for index in range(len(inputs) - 1, -1, -1)
                                            if isinstance(inputs[index], SubmittedFinal)), None)
            latest_verification_index = next(
                (
                    index
                    for index in range(len(inputs) - 1, -1, -1)
                    if isinstance(inputs[index], ActionObservation)
                    and inputs[index].capability_id == _VERIFICATION_CAPABILITY
                ),
                None,
            )
            decision_inputs = tuple(
                item
                for index, item in enumerate(inputs)
                if not (
                    (research_mode and isinstance(item, DecisionFeedback)
                     and item.reason_code == "research_needs_evidence")
                    or
                    (isinstance(item, ActionObservation)
                     and item.capability_id == _VERIFICATION_CAPABILITY
                     and index != latest_verification_index)
                    or (isinstance(item, SubmittedFinal) and index != latest_submission_index)
                    or (isinstance(item, ResearchClaims) and item is not claims)
                    or (isinstance(item, ResearchReview) and item is not review)
                )
            )
            visible_inputs = materialize_interaction_inputs(decision_inputs)
            final_inputs = materialize_citation_context(visible_inputs)
            if research_mode and evidence_selection is not None and evidence_selection.next_step == "write":
                inherited_ids = selected_citation_ids(
                    tuple(reference for claim in claims.claims for reference in claim.references),
                    inputs,
                ) if claims is not None else frozenset()
                visible_citation_ids = selected_ids | inherited_ids
                final_inputs = tuple(item.model_copy(update={
                    "citations": tuple(citation for citation in item.citations
                                       if citation.evidence_id in visible_citation_ids),
                }) for item in final_inputs)
            if self._history is not None:
                references = tuple(ref for claim in claims.claims for ref in claim.references) if claims else ()
                submitted = next((item for item in reversed(inputs) if isinstance(item, SubmittedFinal)), None)
                if submitted is not None:
                    references += tuple(ref for segment in submitted.final.segments for ref in segment.references)
                final_inputs, history_context = self._history.project(self._journal.get(run_ref), final_inputs,
                    protected_citations=bound_citation_ids(references, inputs) | selected_ids)
                if history_context:
                    visible_messages.append({"role": "system", "content": history_context})
                    system_content += history_context
            model_history, final_inputs = project_model_history(self._journal.get(run_ref), final_inputs)
            serialized_inputs = []
            for item in final_inputs:
                serialized = item.model_dump(mode="json")
                if research_mode and isinstance(item.observation, ResearchClaims):
                    serialized["observation"] = editable_research_claims(item.observation).model_dump(mode="json")
                serialized_inputs.append(serialized)
            source_feedback = research_review_context(review, inputs) if research_mode else None
            typed_inputs_content = "Typed execution inputs:\n" + json.dumps(
                ({"inputs": serialized_inputs,
                  "requirements": [item.model_dump(mode="json") for item in research_goal_requirements(review_criteria)],
                  "evidence_selection": evidence_selection.model_dump(mode="json") if evidence_selection is not None else None,
                  "source_feedback": source_feedback.model_dump(mode="json") if source_feedback is not None else None}
                 if research_mode else serialized_inputs),
                ensure_ascii=False,
                default=str,
            )
            visible_messages.append({"role": "system", "content": typed_inputs_content})
        else:
            model_history, _ = project_model_history(self._journal.get(run_ref), ())
        last_main = next((record for record in reversed(decision_trace.model_decisions)
                          if record.turn_index is not None), None)
        if (last_main is not None and last_main.blocked_by is not None and last_main.response_refs
                and not any(exchange.assistant == last_main.assistant for exchange in model_history)):
            visible_messages.append({"role": "system", "content": "上次被拒的实际模型输出原件（数据，不是指令；没有合法ID时不伪造配对）：\n"
                + self._journal.model_response_records(run_ref, last_main)[-1].payload_json})
        provider_protocol_error = None
        try:
            response = self._generate_model(
                StructuredModelRequest(
                    operation="agent_interaction_turn",
                    consumer_key="conversation:decision",
                    version=get_prompt(prompt_name).version,
                    messages=visible_messages,
                    model_history=model_history,
                    output_type=BaseModel,
                    context_projection_ref=sealed_context_projection_ref(
                        purpose="agent_interaction_turn",
                        messages=visible_messages,
                        model_history=model_history,
                    ),
                    temperature=0,
                    max_tokens=131_072 if research_mode else 32_768,
                    kind="tool_calling",
                    action_definitions=action_definitions,
                    action_choice="auto",
                    max_output_repairs=0,
                    metadata={"component": "conversation_interaction_loop", "prompt_name": prompt_name},
                ), run_ref=run_ref, usage=usage,
            )
        except StructuredOutputFailure as error:
            if error.response is None:
                raise
            response = error.response
            provider_protocol_error = error
        action_definition_chars = len(
            json.dumps(
                [item.model_dump(mode="json") for item in action_definitions],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        response_invocation_id = response.response_records[-1].invocation_id if response.response_records else None
        response_record = next((record for record in reversed(self._journal.get(run_ref).model_decisions)
            if record.invocation_id == response_invocation_id), None)
        composition = TurnContextComposition(
            turn_index=(response_record.turn_index - 1 if response_record is not None and response_record.turn_index is not None else turn_index),
            capability_projection_chars=len(capability_projection),
            model_action_definition_chars=action_definition_chars,
            # By subtraction, so the two segments are disjoint by construction and
            # always sum to the prompt that was sent.
            system_prompt_other_chars=len(system_content) - len(capability_projection),
            conversation_messages_chars=sum(
                len(item["content"]) for item in conversation_content
            ),
            typed_inputs_chars=len(typed_inputs_content),
            native_history_chars=sum(len(json.dumps(exchange.assistant.payload, ensure_ascii=False))
                                     + sum(len(result.content) for result in exchange.results)
                                     for exchange in model_history),
            prompt_version=get_prompt(prompt_name).version,
            input_tokens=response.input_tokens,
        )
        try:
            if provider_protocol_error is not None:
                raise provider_protocol_error
            bound_definitions = self._journal.model_request(run_ref, response_record).action_definitions if response_record is not None else action_definitions
            assistant = response.assistant_message
            has_calls = bool(response.action_invocations or (assistant is not None and assistant.call_ids))
            if has_calls:
                decision = decode_model_action_invocations(response.action_invocations, bound_definitions,
                    reveal_invalid_action_field_names=self._action_diagnostics_reveal_field_names)
            else:
                try:
                    decision = self._answer_result.decode_assistant_message(assistant, inputs,
                        requires_review=review_criteria.requires_review, experiment_run=decision_trace.deployment_digest is not None)
                except (ValueError, CitationBindingError) as error:
                    return None, response, composition, DecisionFeedback(
                        action_id="assistant_message", reason_code="answer_result_payload_invalid",
                        message=str(error), repairable_fields=("content",),
                        required_repair="依据当前回答模块提交完整可见正文或合法原生操作；本次正文未接纳。")
            if isinstance(decision, AnswerResultInvocation):
                try:
                    decision = self._answer_result.decode_operation(decision, inputs,
                        requires_review=review_criteria.requires_review, experiment_run=decision_trace.deployment_digest is not None)
                except (ValueError, CitationBindingError) as error:
                    return None, response, composition, DecisionFeedback(
                        action_id=response.action_invocations[0].call_id, reason_code="answer_result_payload_invalid",
                        message=str(error), repairable_fields=("arguments",),
                        required_repair="按当前操作Schema和合法基稿ID修正；本次完整操作未应用。")
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
            return None, response, composition, self._provider_action_feedback(exc, response)
        return decision, response, composition, None

    @staticmethod
    def _provider_action_feedback(
        error: StructuredOutputFailure, response: StructuredModelResponse,
    ) -> DecisionFeedback:
        return DecisionFeedback(
            action_id="provider_action_protocol",
            action_name=error.action_name or "provider_action_protocol",
            reason_code=error.reason_code,
            action_diagnostics=tuple(
                ActionProtocolDiagnostic(field_path=path, error_type=kind)
                for path, kind in zip(error.field_paths, error.error_types, strict=True)
            ),
            rejected_action_invocations=response.action_invocations,
            message=(
                "本次动作集合不符合声明的交互协议；该集合中的全部动作均未准入或执行。"
            ),
            repairable_fields=("action_calls",),
            immutable_fields=("messages", "inputs"),
            required_repair=get_prompt("conversation.action_protocol_repair").template,
        )

    def _require_python_authorization(self, trace):
        authorization = self._python_authorization
        if (authorization is None or authorization.authorization_digest != trace.python_authorization_digest
                or authorization.authorized_principal != trace.principal
                or authorization.conversation_id != trace.conversation_id
                or authorization.max_execution_seconds != trace.max_execution_seconds
                or trace.run_deadline_at is None or trace.run_deadline_at > authorization.expires_at):
            raise PermissionError("原Python分析授权不可用或绑定已变化")
        return authorization

    def _remaining_model_tokens(self, run_ref, usage):
        remaining = self._budget_policy.max_total_tokens - usage.total_tokens
        trace = self._journal.get(run_ref)
        if trace.python_authorization_digest is not None:
            authorization = self._require_python_authorization(trace)
            consumed = self._journal.conversation_usage(trace).total_tokens
            consumed += max(0, usage.total_tokens - trace.usage.total_tokens)
            remaining = min(remaining, authorization.max_total_tokens - consumed)
        return max(0, remaining)

    def _visible_budget_policy(self, run_ref, usage):
        return self._budget_policy.model_copy(update={
            "max_total_tokens": max(1, usage.total_tokens + self._remaining_model_tokens(run_ref, usage)),
        })

    def _admit_research_model_call(self, run_ref, usage):
        trace = self._journal.get(run_ref)
        if trace.run_deadline_at is not None and datetime.now(UTC) >= trace.run_deadline_at:
            raise ConversationFailure(
                "本次任务运行时限已到，不能启动新增工作；已提交成果保留。",
                reason_code="run_deadline_exceeded", failure_stage="application_budget",
            )
        if self._remaining_model_tokens(run_ref, usage) <= 0:
            raise ConversationFailure(
                "本次已知模型消费达到额度，不能启动新增工作；已提交成果保留。",
                reason_code="model_token_budget_exhausted", failure_stage="application_budget",
            )

        if trace.python_profile_digest is None:
            return
        if trace.python_authorization_digest is not None:
            self._require_python_authorization(trace)
            if self._journal.execution_budget(trace).unsettled_action_ids:
                raise ConversationFailure("本分析任务仍有未决工具执行，需先恢复执行状态。",
                    reason_code="dependency_unavailable", failure_stage="application_budget")
        if not self._experiment_model_capacity_valid:
            raise ConversationFailure(
                "执行配置缺少与当前模型匹配的容量配置，尚未启动本次模型调用。",
                reason_code="capacity_profile_mismatch", failure_stage="model_capacity",
            )

    def _compact_after_capacity(self, error, run_ref):
        if (error.reason_code != "context_capacity_exceeded" or self._history is None):
            raise error
        for response in (*error.prior_responses, *((error.response,) if error.response else ())):
            self._history.record_response(run_ref, response)
        error.response, error.prior_responses = None, ()
        try:
            self._history.compact(run_ref)
        except ConversationFailure:
            raise
        except ModelCapacityRefused as failure:
            raise self._capacity_failure(failure) from failure
        except (ModelInvocationUnavailable, StructuredOutputFailure) as failure:
            raise self._model_failure(failure, message="历史摘要未完成，原始记录和已发生费用保留。",
                failure_stage=("provider_request" if isinstance(failure, ModelInvocationUnavailable)
                               else "provider_structured_decode"), component="conversation_history") from failure
        except (ValueError, OSError, ConversationOperationConflict) as failure:
            raise ConversationFailure(f"历史摘要未激活：{failure}",
                reason_code="context_capacity_exceeded", failure_stage="model_capacity") from failure

    @staticmethod
    def _model_journal_call(operation, callback, *args, **kwargs):
        """Classify IO only at the explicit model-original Journal boundary."""
        try:
            return callback(*args, **kwargs)
        except (OSError, ConversationOperationConflict) as error:
            raise ConversationFailure("模型调用记录或恢复未完成；已保存原件和实际费用保留。",
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
                message="模型请求未取得可用响应。",
                failure_stage="provider_request",
                component=str(request.metadata.get("component", "conversation")),
            ) from exc
        except StructuredOutputFailure as exc:
            if request.kind == "tool_calling" and exc.response is not None:
                raise
            raise self._model_failure(
                exc,
                message="模型输出不符合当前交互契约。",
                failure_stage=(
                    "provider_action_decode"
                    if request.kind == "tool_calling"
                    else "provider_structured_decode"
                ),
                component=str(request.metadata.get("component", "conversation")),
            ) from exc
        except Exception as error:
            if getattr(error, "model_response_recording_failed", False):
                raise ConversationFailure("模型响应记录未完成；已保存原件和实际费用保留。",
                    reason_code="runtime_failure", failure_stage="application_persistence",
                    operation=request.operation) from error
            raise

    @staticmethod
    def _capacity_failure(error: ModelCapacityRefused) -> ConversationFailure:
        return ConversationFailure(
            "当前模型请求超过已声明的容量边界，或部署容量信息与实际请求不匹配；本次调用已停止。",
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

    def _effective_capabilities(self, *, run_ref: str | None = None) -> EffectiveCapabilities:
        tools: list[EffectiveToolCapability] = []
        if self._knowledge_writer is not None:
            tools.append(
                EffectiveToolCapability(
                    name=_KNOWLEDGE_SAVE_CAPABILITY,
                    description=(
                        "Prepare an immutable, user-confirmed save of knowledge already present "
                        "in selected user messages. This action does not write knowledge."
                    ),
                    input_schema=KnowledgeSaveArguments.model_json_schema(),
                    read_only=False,
                    planning_safe=False,
                    safely_retryable=False,
                )
            )
        if self._artifact_port is not None:
            tools.append(
                EffectiveToolCapability(
                    name=READ_ARTIFACT_CAPABILITY,
                    description=get_prompt("conversation.read_artifact.description").template,
                    input_schema=ReadArtifactArguments.model_json_schema(),
                    read_only=True,
                    planning_safe=True,
                    safely_retryable=True,
                )
            )
        if self._artifact_port is not None and self._artifact_search is not None:
            tools.append(EffectiveToolCapability(
                name=SEARCH_ACTION_OUTPUT_CAPABILITY,
                description=get_prompt("conversation.search_output.description").template,
                input_schema=SearchActionOutputArguments.model_json_schema(),
                read_only=True, planning_safe=True, safely_retryable=True,
            ))
        if self._knowledge_reader is not None:
            tools.append(
                EffectiveToolCapability(
                    name=_SEARCH_PERSONAL_KNOWLEDGE_CAPABILITY,
                    description=(
                        "Search the caller's personal knowledge for evidence only when the latest "
                        "user request asks to recall or use their stored facts. Questions such as "
                        "'what is my saved X?' or 'do I still have X saved?' are already sufficient "
                        "requests: call without asking for a storage location or separate consent. "
                        "Do not call when personal data is mentioned only to exclude, withhold, "
                        "protect, or forbid its use. Return original evidence quotes and conflict "
                        "facts."
                    ),
                    input_schema=SearchPersonalKnowledgeArguments.model_json_schema(),
                    read_only=True,
                    planning_safe=True,
                    safely_retryable=True,
                )
            )
            tools.append(
                EffectiveToolCapability(
                    name=_LIST_PERSONAL_KNOWLEDGE_CAPABILITY,
                    description=(
                        "List the caller's current personal knowledge items with canonical "
                        "knowledge_item_id, title, summary, and state. Use only to inspect the "
                        "inventory or select a delete target; do not use it to answer from stored "
                        "personal facts."
                    ),
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
                    description=(
                        "Prepare the canonical governed deletion command for one observed personal "
                        "knowledge item. This does not delete anything; user confirmation is required."
                    ),
                    input_schema=PrepareKnowledgeDeleteArguments.model_json_schema(),
                    read_only=False,
                    planning_safe=False,
                    safely_retryable=False,
                )
            )
        if self._tool_port is not None:
            for candidate in self._tool_port.list_interaction_tools():
                if candidate.name == "retrieval_experiment" and (
                    run_ref is None or self._journal.get(run_ref).deployment_digest is None):
                    continue
                if candidate.name == "execute_python":
                    trace = self._journal.get(run_ref) if run_ref is not None else None
                    if trace is None or trace.python_profile_digest is None:
                        continue
                    deployment = self._experiment_deployment
                    budget = self._journal.execution_budget(trace)
                    if trace.python_authorization_digest is not None:
                        self._require_python_authorization(trace)
                    elif (deployment is None or trace.principal != deployment.authorized_principal
                          or trace.deployment_digest != deployment.deployment_digest):
                        continue
                    if (trace.run_deadline_at is None
                            or datetime.now(UTC) >= trace.run_deadline_at
                            or budget.remaining_seconds <= 0 or budget.unsettled_action_ids):
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
            for profile in (self._agent_port.profiles() if self._agent_port else ())
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
        personal_search_succeeded = any(
            isinstance(item, ActionObservation)
            and item.capability_id == _SEARCH_PERSONAL_KNOWLEDGE_CAPABILITY
            and item.status == "succeeded"
            for item in inputs
        )
        readable_refs = input_resource_refs(inputs)
        inspectable_refs = readable_refs
        if run_ref is not None and self._history is not None:
            self._history.validate(self._journal.get(run_ref))
            readable_refs = tuple(dict.fromkeys((*readable_refs, *checkpoint_refs(self._journal.get(run_ref)))))
        has_readable_offloaded_output = bool(readable_refs)
        projected_tools = []
        for tool in capabilities.tools:
            if tool.name == "inspect_artifact" and not inspectable_refs:
                continue
            if tool.name in {*ARTIFACT_OUTPUT_CAPABILITIES, "inspect_artifact"} and readable_refs:
                schema = deepcopy(tool.input_schema)
                allowed_refs = inspectable_refs if tool.name == "inspect_artifact" else readable_refs
                schema["properties"]["resource_id"]["enum"] = list(dict.fromkeys(ref.resource_id for ref in allowed_refs))
                tool = tool.model_copy(update={"input_schema": schema})
            if tool.name in {"execute_python", "write_artifact"} and inspectable_refs:
                schema = deepcopy(tool.input_schema)
                definition, field = (("PythonInputBinding", "resource_id") if tool.name == "execute_python"
                                     else ("PatchArtifact", "base_resource_id"))
                schema["$defs"][definition]["properties"][field]["enum"] = list(dict.fromkeys(
                    ref.resource_id for ref in inspectable_refs if ref.resource_type == "artifact"
                ))
                tool = tool.model_copy(update={"input_schema": schema})
            projected_tools.append(tool)
        return capabilities.model_copy(update={
            "tools": tuple(
                tool
                for tool in projected_tools
                if not (
                    personal_search_succeeded
                    and tool.name == _SEARCH_PERSONAL_KNOWLEDGE_CAPABILITY
                )
                and not (
                    not has_readable_offloaded_output
                    and tool.name in ARTIFACT_OUTPUT_CAPABILITIES
                )
            ),
        })

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

    @staticmethod
    def _repeated_action_feedback(
        inputs: tuple[InteractionInput, ...],
    ) -> DecisionFeedback | None:
        """Stop after one bounded repair of the same rejected model action."""
        last_progress = next(
            (
                index
                for index in range(len(inputs) - 1, -1, -1)
                if isinstance(item := inputs[index], ResearchClaims)
                or (isinstance(item, ActionObservation) and item.status == "succeeded")
            ),
            -1,
        )
        attempts: dict[tuple[str, str, int | None], set[int]] = {}
        for item in inputs[last_progress + 1 :]:
            if not isinstance(item, DecisionFeedback) or item.decision_turn is None:
                continue
            key = (
                # Unknown names share the existing protocol repair allowance.
                "provider_action_protocol"
                if item.reason_code == "provider_action_unknown"
                else item.action_name or item.action_id,
                item.reason_code,
                item.working_plan_revision,
            )
            attempts.setdefault(key, set()).add(item.decision_turn)
            if len(attempts[key]) >= 2:
                return item
        return None

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
                or not (
                    action.tool_name in ARTIFACT_OUTPUT_CAPABILITIES
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
        runnable: list[ToolCallProposal | AgentDelegationProposal] = []
        remaining_tool_calls = max(
            0,
            self._budget_policy.max_tool_calls - usage.tool_calls,
        )
        remaining_agent_calls = max(
            0,
            self._budget_policy.max_agent_calls - usage.agent_calls,
        )
        for action in accepted:
            if isinstance(action, ToolCallProposal):
                if remaining_tool_calls == 0:
                    denied.append(
                        _ActionResult(
                            action.action_id,
                            self._name_action_feedback(
                                self._budget_feedback(action.action_id, "tool"),
                                proposal.actions,
                            ),
                        )
                    )
                    continue
                remaining_tool_calls -= 1
                runnable.append(action)
            elif remaining_agent_calls == 0:
                denied.append(
                    _ActionResult(
                        action.action_id,
                        self._name_action_feedback(
                            self._budget_feedback(action.action_id, "agent"),
                            proposal.actions,
                        ),
                    )
                )
            else:
                remaining_agent_calls -= 1
                runnable.append(action)
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
        for action in runnable:
            if not isinstance(action, ToolCallProposal) or action.tool_name not in {"write_artifact", "retrieval_experiment", "execute_python"}:
                continue
            argument_type = {"write_artifact": WriteArtifactArgs,
                             "retrieval_experiment": ExperimentToolArgs,
                             "execute_python": ExecutePythonArgs}[action.tool_name]
            self._journal.accept_tool_request(
                execution_scope=ExecutionScope(principal=principal, execution_id=run_ref,
                                                thread_id=conversation_id, task_id=action.action_id),
                action_id=action.action_id, arguments=argument_type.model_validate(action.arguments),
                plan_step_id=plan_step_id,
            )
        if concurrent:
            with ThreadPoolExecutor(
                max_workers=min(len(runnable), self._budget_policy.max_concurrency)
            ) as pool:
                futures = [
                    pool.submit(self._execute_one, item, context) for item in runnable
                ]
                executed = [future.result() for future in futures]
        else:
            executed = [self._execute_one(item, context) for item in runnable]
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
        return (
            [by_id[action.action_id] for action in proposal.actions],
            usage,
            concurrent,
        )

    def _admit(self, action, *, run_ref, committed_action_ids, committed_inputs):
        if (isinstance(action, ToolCallProposal) and action.tool_name == "inspect_artifact"
                and action.arguments.get("resource_id") in [ref.resource_id
                    for ref in checkpoint_refs(self._journal.get(run_ref))]):
            return DecisionFeedback(action_id=action.action_id, reason_code="artifact_reference_invalid",
                message="历史原件仅可作为工作上下文读取，不能作为来源核验材料。",
                immutable_fields=("action_id",), repairable_fields=("tool_name", "arguments"),
                required_repair="使用 read_artifact 或 search_action_output 读取历史原件。")
        if isinstance(action, ToolCallProposal) and action.tool_name in {"retrieval_experiment", "execute_python"}:
            trace = self._journal.get(run_ref)
            binding = (trace.python_profile_digest if action.tool_name == "execute_python"
                       else trace.deployment_digest) if trace is not None else None
            if binding is None:
                return DecisionFeedback(action_id=action.action_id, reason_code="capability_missing",
                    message="本任务尚未绑定该工具的执行许可。", immutable_fields=("action_id",),
                    required_repair="使用本任务可用能力，或说明缺少获准执行环境。", disposition="fail_closed")
        if action.action_id in committed_action_ids:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="duplicate_action_id",
                message="The action_id is already bound to a committed interaction action.",
                repairable_fields=("action_id",),
                immutable_fields=("kind",),
                required_repair="Create a new proposal with a fresh action_id; do not replay the prior action.",
            )
        if (
            isinstance(action, ToolCallProposal)
            and action.tool_name in ARTIFACT_OUTPUT_CAPABILITIES
        ):
            # Service-owned: the artifact port serves it, so the tool registry has no
            # entry to validate against and its schema is the contract.
            if action.tool_name == READ_ACTION_OUTPUT_CAPABILITY or self._artifact_port is None or (action.tool_name == SEARCH_ACTION_OUTPUT_CAPABILITY and self._artifact_search is None):
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="capability_missing",
                    message=f"Tool {action.tool_name!r} is not currently available.",
                    repairable_fields=("tool_name", "arguments"),
                    immutable_fields=("action_id",),
                    required_repair="Choose an available tool or explain the capability limitation.",
                )
            try:
                argument_type = SearchActionOutputArguments if action.tool_name == SEARCH_ACTION_OUTPUT_CAPABILITY else ReadArtifactArguments
                arguments = argument_type.model_validate(action.arguments)
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
                resource_ref = resolve_artifact_ref(
                    arguments.resource_id,
                    (*input_resource_refs(committed_inputs), *checkpoint_refs(self._journal.get(run_ref))),
                    principal=self._journal.get(run_ref).principal,
                )
            except PermissionError:
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="artifact_reference_invalid",
                    message=(
                        "只能读取本任务输入或已提交回执提供的确切资源引用。"
                    ),
                    repairable_fields=("arguments",),
                    immutable_fields=("action_id", "tool_name"),
                    required_repair=(
                        "使用当前输入或已提交回执提供的 resource_id。"
                    ),
                )
            if resource_ref in checkpoint_refs(self._journal.get(run_ref)) and self._history is not None:
                self._history.validate(self._journal.get(run_ref))
            return None
        if isinstance(action, ToolCallProposal):
            offloaded = self._offloaded_resources(committed_inputs)
            request_digest = canonical_digest({
                "tool_name": action.tool_name,
                "arguments": action.arguments,
            })
            unread_resource = next(
                (
                    resource_id
                    for resource_id, (
                        capability_id,
                        prior_digest,
                        _resource_ref,
                    ) in offloaded.items()
                    if capability_id == action.tool_name
                    and prior_digest == request_digest
                ),
                None,
            )
            if unread_resource is not None:
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="offloaded_output_refetch",
                    message=(
                        f"Tool {action.tool_name!r} already produced an offloaded output "
                        "for this exact request. Calling it again cannot expose the omitted middle."
                    ),
                    repairable_fields=("tool_name", "arguments"),
                    immutable_fields=("action_id",),
                    required_repair=(
                        "Use search_action_output or read_artifact with the previously supplied resource_id "
                        f"for resource_id {unread_resource!r} and the corresponding search or read parameters."
                    ),
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
            if any(
                isinstance(item, ActionObservation)
                and item.capability_id == _LIST_PERSONAL_KNOWLEDGE_CAPABILITY
                and item.status == "succeeded"
                for item in committed_inputs
            ):
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="knowledge_list_already_observed",
                    message=(
                        "The current interaction already has a successful authoritative "
                        "personal-knowledge list Observation."
                    ),
                    immutable_fields=("action_id", "tool_name"),
                    required_repair=(
                        "Use the committed list Observation to continue or answer; do not "
                        "repeat the same read in this interaction."
                    ),
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

    def _fit_observation_payload(
        self,
        payload: dict[str, Any],
        *,
        action_id: str,
        capability_id: str,
        run_ref: str,
        owner,
        execution_scope,
    ) -> dict[str, Any]:
        """Fit one observation into the context, offloading whatever did not fit.

        The bound is what keeps ``max_total_tokens`` meaningful for a single
        oversized return. Offloading is what keeps the bound from destroying
        evidence: the omitted text stays readable through ``read_artifact``,
        so choosing which part matters remains the model's decision.
        """

        bounded = bound_observation_payload(payload)
        if not bounded.is_bounded:
            return bounded.payload
        retrieval: dict[str, Any] = {
            "omitted_chars": bounded.omitted_chars,
            "original_chars": bounded.original_chars,
        }
        # 抓取契约在读取边界校验；明确选择来源载荷，不依赖最长叶子或工具名注册表。
        data = payload.get("data")
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
            resource_ref = self._artifact_port.write_generated(
                owner=owner,
                execution_scope=execution_scope,
                producer_key=f"{run_ref}:{action_id}:observation",
                producer_ref=capability_id,
                kind="action_output",
                content=full_text,
                content_digest=sha256(full_text.encode("utf-8")).hexdigest(),
                source_artifact_refs=(),
                evidence_refs=(),
                limitations=(
                    f"Offloaded for re-read: the observation was {bounded.original_chars} "
                    "characters, beyond one observation's context budget.",
                ),
            )
        except Exception as error:  # offload failure must be visible, not silent
            retrieval["unavailable_reason"] = (
                f"Offload failed ({type(error).__name__}); the omitted part cannot be "
                "re-read in this turn."
            )
        else:
            retrieval["resource_ref"] = resource_ref.model_dump(mode="json")
            retrieval["total_lines"] = len(full_text.splitlines())
            retrieval["read_more"] = (
                "This excerpt omits the middle of the output. To read the omitted part, "
                "call search_action_output with this resource_ref.resource_id and keyword to "
                "locate it, or call read_artifact with start_line to read sequentially."
            )
        # retrieval 自身也占 Context，原有边界不能在附加引用后被突破。
        search_metadata = (
            search_output.model_copy(update={"results": ()}).model_dump(mode="json")
            if search_output else None
        )
        final_bound = bound_observation_payload(
            payload, max_chars=MAX_OBSERVATION_PAYLOAD_CHARS
            - serialized_length({"retrieval": retrieval}) - 32
            - (serialized_length({"data": search_metadata}) if search_metadata else 0),
        )
        fitted = dict(final_bound.payload)
        if search_metadata is not None:
            fitted = {key: value for key, value in fitted.items()
                      if key in {"ok", "error", "error_kind", "status"}}
            fitted["observation_excerpt_removed"] = True
            fitted["data"] = search_metadata
        retrieval["omitted_chars"] = final_bound.omitted_chars
        fitted["retrieval"] = retrieval
        return fitted

    def _search_action_output(self, action, *, principal, owner, inputs, run_ref):
        try:
            arguments = SearchActionOutputArguments.model_validate(action.arguments)
            ref = resolve_artifact_ref(arguments.resource_id,
                self._journal.readable_resource_refs(self._journal.get(run_ref)), principal=principal)
            snapshot = self._artifact_port.read_snapshot(ref, principal=principal, owner=owner)
            result = search_artifact_text(snapshot, arguments=arguments, matcher=self._artifact_search)
            return _ActionResult(action.action_id, ActionObservation(
                kind="tool_result", action_id=action.action_id, capability_id=SEARCH_ACTION_OUTPUT_CAPABILITY,
                evidence_eligible=ref not in checkpoint_refs(self._journal.get(run_ref)),
                status="succeeded", payload={"ok": True, **result.model_dump(mode="json")}))
        except (ValidationError, ValueError) as error:
            error_kind = "invalid_param"
            message = str(error)
        except Exception as error:
            error_kind = "execution_failure"
            message = f"{type(error).__name__}: {error}"
        return _ActionResult(action.action_id, ActionObservation(
            kind="tool_result", action_id=action.action_id, capability_id=SEARCH_ACTION_OUTPUT_CAPABILITY,
            status="failed", payload={"ok": False, "error_kind": error_kind, "error": message}))

    def _read_artifact(self, action, *, principal, owner, run_ref):
        try:
            arguments = ReadArtifactArguments.model_validate(action.arguments)
            ref = resolve_artifact_ref(arguments.resource_id,
                self._journal.readable_resource_refs(self._journal.get(run_ref)), principal=principal)
            snapshot = self._artifact_port.read_snapshot(ref, principal=principal, owner=owner)
            result = read_artifact_text(snapshot, arguments=arguments)
            return _ActionResult(action.action_id, ActionObservation(
                kind="tool_result", action_id=action.action_id, capability_id=READ_ARTIFACT_CAPABILITY,
                evidence_eligible=ref not in checkpoint_refs(self._journal.get(run_ref)),
                status="succeeded", payload={"ok": True, **result.model_dump(mode="json")}))
        except (ValidationError, ValueError) as error:
            error_kind, message = "invalid_param", str(error)
        except Exception as error:
            error_kind, message = "execution_failure", f"{type(error).__name__}: {error}"
        return _ActionResult(action.action_id, ActionObservation(
            kind="tool_result", action_id=action.action_id, capability_id=READ_ARTIFACT_CAPABILITY,
            status="failed", payload={"ok": False, "error_kind": error_kind, "error": message}))

    def _read_action_output(self, action, *, principal, owner):
        """Serve a window of an offloaded action output back to the model.

        This is executed here rather than as a registered tool because the artifact
        belongs to this interaction: the principal and scope that wrote it are the
        resolved request identity, which the model neither knows nor may assert.
        Which window matters stays the model's choice.
        """

        observation = partial(
            ActionObservation,
            kind="tool_result",
            action_id=action.action_id,
            capability_id=READ_ACTION_OUTPUT_CAPABILITY,
        )
        try:
            arguments = ReadActionOutputArguments.model_validate(action.arguments)
        except ValidationError as error:
            return _ActionResult(
                action.action_id,
                observation(
                    status="failed",
                    payload={
                        "ok": False,
                        "error_kind": "invalid_param",
                        "error": str(error),
                    },
                ),
            )
        try:
            text = self._artifact_port.read_text(
                arguments.resource_ref,
                principal=principal,
                owner=owner,
            )
        except Exception as error:
            return _ActionResult(
                action.action_id,
                observation(
                    status="failed",
                    payload={
                        "ok": False,
                        "error_kind": "execution_failure",
                        "error": f"{type(error).__name__}: {error}",
                    },
                ),
            )
        read_request = arguments.model_dump(mode="json", exclude={"resource_ref"})
        # 为两份实际参数及状态说明预留空间，避免把可执行续读参数截成不完整字符串。
        envelope_chars = serialized_length({
                "ok": True, "resource_ref": arguments.resource_ref.model_dump(mode="json"),
                "lines": [], "total_lines": len(text),

                "read_state": {"request": read_request, "continuation": {
                    "start_line": max(len(text), arguments.start_line),
                }},
            }) + 1_024
        if envelope_chars >= MAX_OBSERVATION_PAYLOAD_CHARS:
            return _ActionResult(action.action_id, observation(
                status="failed", payload={"ok": False, "error_kind": "invalid_param",
                    "error": "读取参数过长，无法在输出预算内完整回显和提供续读参数；请缩短字面关键词。"},
            ))
        excerpt = excerpt_payload_text(
            text, start_line=arguments.start_line,
            max_chars=MAX_OBSERVATION_PAYLOAD_CHARS - envelope_chars,
        )
        payload = {
            "ok": True,
            # Naming the source makes each window attributable when several outputs were
            # offloaded, and lets the loop tell a read remainder from an unread one.
            "resource_ref": arguments.resource_ref.model_dump(mode="json"),
            "lines": [{"line": number, "text": line} for number, line in excerpt.lines],
            "total_lines": excerpt.total_lines,
            "read_state": excerpt.read_state.model_dump(mode="json"),
        }
        # A window is already line-bounded, but one line can still be huge. Bound it
        # without offloading again: the remainder is still in the same artifact, so a
        # narrower range is the model's remedy, not a second copy.
        metadata = {key: value for key, value in payload.items() if key != "lines"}
        # 截断只作用于正文，不能改写请求回显或可执行的 continuation。
        bounded = bound_observation_payload(
            {"lines": payload["lines"]},
            max_chars=MAX_OBSERVATION_PAYLOAD_CHARS - serialized_length(metadata) - 512,
        )
        window = {**metadata, **bounded.payload}
        if bounded.is_bounded:
            window["retrieval"] = {
                "omitted_chars": bounded.omitted_chars,
                "original_chars": bounded.original_chars,
                "read_more": (
                    "This window was too large to show in full. Request a narrower "
                    "start_line range."
                ),
            }
        assert serialized_length(window) <= MAX_OBSERVATION_PAYLOAD_CHARS
        return _ActionResult(
            action.action_id,
            observation(
                status="succeeded",
                payload=window,
            ),
        )

    def _execute_one(self, action, context):
        conversation_id, run_ref, principal, owner, source_platform = context
        execution_scope = ExecutionScope(
            principal=principal,
            execution_id=run_ref,
            thread_id=conversation_id,
            task_id=action.action_id,
        )
        if (
            isinstance(action, ToolCallProposal)
            and action.tool_name in ARTIFACT_OUTPUT_CAPABILITIES
        ):
            if action.tool_name == SEARCH_ACTION_OUTPUT_CAPABILITY:
                trace = self._journal.get(run_ref)
                return self._search_action_output(action, principal=principal, owner=owner,
                                                  inputs=trace.inputs if trace else (), run_ref=run_ref)
            return self._read_artifact(action, principal=principal, owner=owner, run_ref=run_ref)
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
            known_execution = any(item.action_id == action.action_id and item.command is not None
                                  for item in trace.experiment_records)
            known_execution = known_execution or any(
                isinstance(item, AcceptedPythonToolRequest) and item.action_id == action.action_id
                and item.command is not None for item in trace.accepted_tool_requests
            )
            if action.tool_name in {"write_artifact", "retrieval_experiment", "execute_python"} and (
                trace.run_deadline_at is not None and datetime.now(UTC) >= trace.run_deadline_at
                and not known_execution):
                result = {"ok": False, "error": "实验运行时限已到，不能派发新的变更调用。", "error_kind": "permission", "data": None, "evidence": []}
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
            completed = _ActionResult(
                action.action_id,
                ActionObservation(
                    kind="tool_result",
                    action_id=action.action_id,
                    capability_id=action.tool_name,
                    status="succeeded" if result.get("ok") else "failed",
                    execution_request_digest=canonical_digest({
                        "tool_name": action.tool_name,
                        "arguments": action.arguments,
                    }),
                    payload=self._fit_observation_payload(
                        result,
                        action_id=action.action_id,
                        capability_id=action.tool_name,
                        run_ref=run_ref,
                        owner=owner,
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

    @staticmethod
    def _budget_feedback(action_id, kind):
        return DecisionFeedback(
            action_id=action_id,
            reason_code="budget_exhausted",
            message=f"The committed {kind} call budget is exhausted.",
            immutable_fields=("action_id",),
            required_repair="Stop or request additional budget.",
            disposition="fail_closed",
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
        review_criteria=None,
        working_plan=None,
    ):
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
            review_criteria=review_criteria,
            working_plan=working_plan,
            message="本次交互已达到执行预算上限，未生成替代答案。可增加预算后基于已提交结果继续。",
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
        review_criteria=None,
        working_plan=None,
    ):
        final = FinalMessage(disposition="limitation", segments=(ConversationAnswerSegment(text=message),))
        self._commit(
            run_ref,
            principal,
            messages,
            inputs,
            usage,
            execution_order,
            concurrent_batches,
            context_composition,
            review_criteria=review_criteria,
            final_message=final,
            working_plan=working_plan,
        )
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
        review_criteria=None,
        final_message=None,
        knowledge_save_operation=None,
        knowledge_delete_command_ref=None,
        working_plan=None,
        model_response=None,
        call_dispositions=(),
    ):
        prior = self._journal.get(run_ref)
        if prior is not None:
            updates = {"total_tokens": max(prior.usage.total_tokens, usage.total_tokens)}
            for name in ("model_calls", "input_tokens", "output_tokens"):
                old, new = getattr(prior.usage, name), getattr(usage, name)
                updates[name] = None if old is None or new is None else max(old, new)
            updates["provider_usage_complete"] = prior.usage.provider_usage_complete and usage.provider_usage_complete
            usage = usage.model_copy(update=updates)
        self._append_artifact_sources(run_ref, inputs)
        if model_response is None and prior is not None:
            main = next((record for record in reversed(prior.model_decisions)
                         if record.turn_index == usage.model_turns and record.assistant is not None), None)
            if (main is not None and len(main.assistant.call_ids) == 1
                    and any(action.kind == "answer_result" for action in self._journal.model_request(run_ref, main).action_definitions
                            if action.name == main.assistant.payload["tool_calls"][0].get("function", {}).get("name"))
                    and (any(isinstance(item, (SubmittedFinal, ResearchClaims)) for item in inputs[main.input_start:])
                         or final_message is not None)
                    and not any(isinstance(item, DecisionFeedback) for item in inputs[main.input_start:])
                    and not main.dispositions):
                call_dispositions = (*call_dispositions, ModelCallDisposition(
                    call_id=main.assistant.call_ids[0], operation="answer_result", status="accepted"))
        new_inputs = inputs[len(prior.inputs):] if prior is not None else inputs
        consumed_inner_operations = set()
        if review_criteria is not None and (prior is None or prior.review_criteria is None):
            consumed_inner_operations.update({"interaction_intent", "interaction_intent_revision"})
        if any(isinstance(item, ResearchReview) for item in new_inputs):
            consumed_inner_operations.add("conversation_research_support")
        if any(isinstance(item, ActionObservation) and item.capability_id == _VERIFICATION_CAPABILITY
               for item in new_inputs):
            consumed_inner_operations.update({"interaction_cited_support", "interaction_semantic_verification"})
        # Admission creates per-action feedback; only this loop owns the decision
        # boundary. A batch of rejected siblings is one attempt, including on resume.
        for index in range(len(prior.inputs) if prior is not None else 0, len(inputs)):
            item = inputs[index]
            if isinstance(item, DecisionFeedback):
                inputs[index] = item.model_copy(
                    update={"decision_turn": usage.model_turns or None}
                )
        self._journal.put(
            InteractionTrace(
                revision=(prior.revision + 1 if prior is not None else 1),
                interaction_run_ref=run_ref,
                conversation_id=self._run_conversation_ids[run_ref],
                principal=principal,
                messages=tuple(messages),
                input_artifact_refs=prior.input_artifact_refs if prior else (),
                accepted_tool_requests=prior.accepted_tool_requests if prior else (),
                experiment_records=prior.experiment_records if prior else (),
                research_experiment_delivery=prior.research_experiment_delivery if prior else None,
                history_compaction=prior.history_compaction if prior else None,
                deployment_digest=prior.deployment_digest if prior else None,
                python_authorization_digest=prior.python_authorization_digest if prior else None,
                answer_result_binding=prior.answer_result_binding if prior else self._answer_result.config,
                run_deadline_at=prior.run_deadline_at if prior else None,
                max_execution_seconds=prior.max_execution_seconds if prior else None,
                inputs=tuple(inputs),
                usage=usage,
                execution_order=tuple(execution_order),
                concurrent_batches=tuple(concurrent_batches),
                context_composition=tuple(context_composition),
                model_decisions=tuple(record.model_copy(update={"consumed": True})
                    if record.status != "pending" and (
                        (record.turn_index is None and record.operation in consumed_inner_operations)
                        or (record.turn_index is not None and record.turn_index <= usage.model_turns and (
                            final_message is not None or record.blocked_by is not None
                            or len(inputs) > record.input_start or record.research_selection is not None
                            or (record.assistant is not None and bool(record.assistant.call_ids)
                                and len(record.assistant.call_ids) == len(record.dispositions)))))
                    else record for record in update_decisions(prior, inputs=inputs, turn_index=usage.model_turns,
                    response=model_response, dispositions=call_dispositions)),
                review_criteria=review_criteria,
                final_message=final_message,
                knowledge_save_operation=knowledge_save_operation,
                knowledge_delete_command_ref=(
                    knowledge_delete_command_ref
                    if knowledge_delete_command_ref is not None
                    else (
                        prior.knowledge_delete_command_ref
                        if prior is not None
                        else None
                    )
                ),
                working_plan=(
                    working_plan
                    if working_plan is not None
                    else (prior.working_plan if prior is not None else None)
                ),
            )
        )


__all__ = [
    "ConversationOperationConflict",
    "ConversationOperationNotFound",
    "ConversationService",
    "ConversationFailure",
    "FileInteractionJournal",
    "InMemoryInteractionJournal",
]

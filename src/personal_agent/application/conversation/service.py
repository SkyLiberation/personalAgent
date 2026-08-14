from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from hashlib import sha256
import json
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from personal_agent.capabilities.contracts.grants import (
    DelegationGrant,
    GrantDependencySet,
)
from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.kernel.contracts.agent import AgentGatewayContext, AgentTask
from personal_agent.kernel.contracts.resource import OperationScope, ResourceSelector
from personal_agent.kernel.contracts.scope import (
    ExecutionScope,
    AuthenticatedPrincipal,
)
from personal_agent.kernel.observability import record_policy_decision

from .observation_bounds import (
    bound_observation_payload,
    excerpt_payload_text,
    select_offload_text,
)
from .context_materialization import (
    READ_ACTION_OUTPUT_CAPABILITY,
    materialize_interaction_inputs,
)
from .interaction_prompt import build_interaction_system_prompt
from .errors import (
    ConversationOperationConflict,
    ConversationOperationNotFound,
    ConversationUnavailable,
)
from .journal import (
    FileInteractionJournal,
    InMemoryInteractionJournal,
)
from .knowledge_save import ConversationKnowledgeSaveUseCase
from .models import (
    ActionObservation,
    AgentDelegationProposal,
    AgentTurnDecision,
    AgentTurnDecisionWithPlan,
    CommittedUsage,
    ConversationInteractionMode,
    ConversationKnowledgeSaveOperation,
    ConversationMessage,
    ConversationTurnView,
    DecisionFeedback,
    EffectiveAgentCapability,
    EffectiveCapabilities,
    EffectiveToolCapability,
    FinalMessage,
    InteractionTrace,
    KnowledgeDeleteConfirmation,
    KnowledgeSaveArguments,
    ListPersonalKnowledgeArguments,
    LoopBudgetPolicy,
    PrepareKnowledgeDeleteArguments,
    ProjectReference,
    ReadActionOutputArguments,
    StartDurableInvestigationArguments,
    SteerInvestigationProjectArguments,
    ToolCallProposal,
    TurnContextComposition,
)
from .ports import (
    ConversationKnowledgeLifecyclePort,
    ConversationKnowledgeWriter,
    ConversationProjectPort,
    ConversationKnowledgeReadPort,
    InteractionAgentPort,
    InteractionArtifactPort,
    InteractionToolPort,
)
from .review_admission import (
    ReviewCriteria,
    derive_review_criteria,
    ungrounded_criteria_feedback,
)
from .verification_admission import observed_receipts
from .working_plan import (
    admit_action_plan_bindings,
    admit_final_plan_resolution,
    admit_new_plan_interaction_mode,
    admit_plan_wait_boundary,
    admit_working_plan,
)


_KNOWLEDGE_SAVE_CAPABILITY = "prepare_conversation_knowledge_save"
_VERIFICATION_CAPABILITY = "verify_interaction_draft"
_LIST_PERSONAL_KNOWLEDGE_CAPABILITY = "list_personal_knowledge"
_PERSONAL_KNOWLEDGE_CONTEXT_CAPABILITY = "personal_knowledge_context"
_PREPARE_KNOWLEDGE_DELETE_CAPABILITY = "prepare_knowledge_delete"
_START_DURABLE_INVESTIGATION_CAPABILITY = "start_durable_investigation"
_PROJECT_CONTEXT_CAPABILITY = "investigation_project_context"
_STEER_INVESTIGATION_PROJECT_CAPABILITY = "steer_investigation_project"
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
        knowledge_writer: ConversationKnowledgeWriter | None = None,
        knowledge_reader: ConversationKnowledgeReadPort | None = None,
        knowledge_lifecycle: ConversationKnowledgeLifecyclePort | None = None,
        project_port: ConversationProjectPort | None = None,
        budget_policy: LoopBudgetPolicy | None = None,
        journal: InMemoryInteractionJournal | None = None,
    ) -> None:
        self._model_client = model_client
        self._tool_port = tool_port
        self._agent_port = agent_port
        self._artifact_port = artifact_port
        self._knowledge_writer = knowledge_writer
        self._knowledge_reader = knowledge_reader
        self._knowledge_lifecycle = knowledge_lifecycle
        self._project_port = project_port
        self._run_conversation_ids: dict[str, str] = {}
        self._run_project_references: dict[str, ProjectReference] = {}
        if agent_port is not None and artifact_port is None:
            raise ValueError(
                "agent delegation requires the canonical Artifact read port"
            )
        self._budget_policy = budget_policy or LoopBudgetPolicy()
        self._journal = journal or InMemoryInteractionJournal()
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
    ) -> ConversationTurnView:
        if not messages or messages[-1].role != "user":
            raise ValueError("conversation must end with a user message")
        if self._model_client is None:
            raise ConversationUnavailable("conversation model is not configured")
        owner = principal

        run_ref = interaction_run_ref or f"irun_{uuid4().hex[:16]}"
        prior = self._journal.get(run_ref)
        if prior is not None:
            self._require_trace_scope(
                prior,
                principal,
                action="conversation_run_resume",
            )
        if prior is not None and prior.conversation_id != conversation_id:
            raise ValueError("interaction_run_ref is bound to a different conversation")
        linked_projects = self._journal.project_references(conversation_id, principal)
        if len(linked_projects) > 1:
            raise ConversationOperationConflict(
                "conversation is linked to multiple durable investigations"
            )
        linked_project = linked_projects[0] if linked_projects else None
        working_plan = (
            prior.working_plan
            if prior is not None and prior.working_plan is not None
            else self._journal.working_plan(conversation_id, principal)
        )
        self._run_conversation_ids[run_ref] = conversation_id
        if linked_project is not None:
            self._run_project_references[run_ref] = linked_project
        capabilities = self._effective_capabilities(
            linked_project_reference=linked_project
        )
        if prior is not None and tuple(messages) != prior.messages:
            raise ValueError(
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
            return ConversationTurnView(
                interaction_run_ref=run_ref,
                conversation_id=conversation_id,
                disposition=prior.final_message.disposition,
                message=ConversationMessage(
                    role="assistant", content=prior.final_message.message
                ),
                project_reference=prior.project_reference,
                working_plan=working_plan,
            )
        if prior is not None and prior.project_reference is not None:
            return self._project_turn_view(
                conversation_id, run_ref, prior.project_reference
            )
        if prior is not None:
            inputs = list(prior.inputs)
        elif working_plan is not None and any(
            step.status == "pending" for step in working_plan.steps
        ):
            inputs = list(self._journal.working_plan_observations(
                conversation_id,
                principal,
                working_plan,
            ))
        else:
            inputs = []
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
        answer_only_pending = bool(
            prior is not None
            and prior.final_message is None
            and working_plan is not None
            and all(step.status == "completed" for step in working_plan.steps)
        )
        if self._knowledge_reader is not None and not any(
            isinstance(item, ActionObservation)
            and item.capability_id == _PERSONAL_KNOWLEDGE_CONTEXT_CAPABILITY
            for item in inputs
        ):
            evidence = self._knowledge_reader.select_personal_evidence(
                question=messages[-1].content,
                owner_id=principal.principal_id,
                user_id=principal.user_id,
                limit=8,
            )
            if (
                evidence.citations
                or evidence.claim_summaries
                or evidence.conflicted_claim_ids
                or evidence.potential_conflicted_claim_ids
            ):
                inputs.append(ActionObservation(
                    kind="context_evidence",
                    action_id="context-personal-knowledge",
                    capability_id=_PERSONAL_KNOWLEDGE_CONTEXT_CAPABILITY,
                    status="succeeded",
                    payload=evidence.model_dump(mode="json"),
                ))
        if (
            linked_project is not None
            and self._project_port is not None
            and not any(
                isinstance(item, ActionObservation)
                and item.capability_id == _PROJECT_CONTEXT_CAPABILITY
                for item in inputs
            )
        ):
            try:
                project_snapshot = self._project_port.get(
                    principal=principal,
                    reference=linked_project,
                )
                inputs.append(ActionObservation(
                    kind="context_evidence",
                    action_id="context-investigation-project",
                    capability_id=_PROJECT_CONTEXT_CAPABILITY,
                    status="succeeded",
                    payload=project_snapshot.model_dump(mode="json"),
                ))
            except (KeyError, PermissionError, ValueError) as error:
                inputs.append(ActionObservation(
                    kind="context_evidence",
                    action_id="context-investigation-project",
                    capability_id=_PROJECT_CONTEXT_CAPABILITY,
                    status="failed",
                    payload={
                        "error_kind": "application_operation_rejected",
                        "error": str(error),
                    },
                ))
        if review_criteria is None:
            review_criteria, derivation_response = self._derive_review_criteria(messages)
            if derivation_response is not None:
                usage = self._record_model_usage(usage, derivation_response)
            if review_criteria.requires_review and not self._verification_available():
                inputs.append(self._verification_unavailable_feedback())
                review_criteria = ReviewCriteria()
            elif (
                review_criteria.ungrounded_spans and not review_criteria.requires_review
            ):
                inputs.append(ungrounded_criteria_feedback(review_criteria))
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

        while True:
            if answer_only_pending:
                if usage.total_tokens >= self._budget_policy.max_total_tokens:
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
                decision, completion_response = self._decide_answer_only(
                    messages=messages,
                    inputs=tuple(inputs),
                )
                usage = self._record_model_usage(
                    usage,
                    completion_response,
                    model_turn=False,
                )
                answer_only_pending = False
            else:
                if usage.model_turns >= self._budget_policy.max_model_turns:
                    break
                if usage.total_tokens >= self._budget_policy.max_total_tokens:
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
                decision, model_response, composition = self._decide(
                    messages=messages,
                    capabilities=capabilities,
                    inputs=inputs,
                    usage=usage,
                    review_criteria=review_criteria,
                    turn_index=usage.model_turns,
                    working_plan=working_plan,
                    interaction_mode=interaction_mode,
                )
                context_composition.append(composition)
                usage = self._record_model_usage(
                    usage,
                    model_response,
                    model_turn=True,
                )
            if isinstance(decision, FinalMessage):
                if decision.disposition == "answer" and working_plan is not None:
                    incomplete_feedback, resolved_plan = admit_final_plan_resolution(
                        decision.resolved_plan_step_ids,
                        working_plan=working_plan,
                        inputs=tuple(inputs),
                    )
                    if incomplete_feedback is not None:
                        inputs.append(incomplete_feedback)
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
                    working_plan = resolved_plan
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
                if review_criteria.requires_review and decision.disposition != "answer":
                    inputs.append(self._review_answer_required_feedback(decision))
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
                if review_criteria.requires_review:
                    verified, result, usage = self._verify_before_send(
                        decision,
                        review_criteria=review_criteria,
                        conversation_id=conversation_id,
                        run_ref=run_ref,
                        principal=principal,
                        owner=owner,
                        source_platform=source_platform,
                        usage=usage,
                        attempt=len(execution_order),
                    )
                    inputs.append(result.interaction_input)
                    execution_order.append(result.action_id)
                    if verified is None:
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
                        role="assistant", content=decision.message.strip()
                    ),
                    project_reference=self._run_project_references.get(run_ref),
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

            if decision.working_plan is not None:
                mode_feedback = admit_new_plan_interaction_mode(
                    decision,
                    current=working_plan,
                    interaction_mode=interaction_mode,
                    execution_started=bool(execution_order),
                )
                if mode_feedback is not None:
                    inputs.append(mode_feedback)
                    answer_only_pending = bool(
                        execution_order
                        and not decision.actions
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
                    continue
                feedback, admitted_plan = admit_working_plan(
                    decision.working_plan,
                    current=working_plan,
                    inputs=tuple(inputs),
                )
                if feedback is not None:
                    if (
                        feedback.reason_code == "working_plan_no_change"
                        and decision.actions
                    ):
                        admitted_plan = working_plan
                    else:
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
                answer_only_pending = bool(
                    working_plan is not None
                    and all(step.status == "completed" for step in working_plan.steps)
                    and not decision.actions
                    and not decision.wait_for_user
                )
            action_plan_feedback = admit_action_plan_bindings(
                decision.actions,
                working_plan=working_plan,
            )
            if action_plan_feedback is not None:
                inputs.append(action_plan_feedback)
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
                    inputs.append(self._application_operation_feedback(action, error))
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
                )
                return self._knowledge_delete_turn_view(
                    conversation_id,
                    run_ref,
                    operation,
                )

            project_actions = [
                action
                for action in decision.actions
                if isinstance(action, ToolCallProposal)
                and action.tool_name == _START_DURABLE_INVESTIGATION_CAPABILITY
            ]
            if project_actions:
                action = project_actions[0]
                feedback, arguments = self._admit_project_start(
                    action,
                    all_actions=decision.actions,
                    linked_project_reference=linked_project,
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
                try:
                    project_reference = self._project_port.start(
                        principal=principal,
                        owner=owner,
                        request=arguments,
                        idempotency_key=sha256(
                            f"{run_ref}:{action.action_id}".encode("utf-8")
                        ).hexdigest(),
                    )
                except (KeyError, PermissionError, ValueError) as error:
                    inputs.append(self._application_operation_feedback(action, error))
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
                self._run_project_references[run_ref] = project_reference
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
                    project_reference=project_reference,
                    working_plan=working_plan,
                )
                return self._project_turn_view(
                    conversation_id,
                    run_ref,
                    project_reference,
                )

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

    @staticmethod
    def _require_trace_scope(
        trace: InteractionTrace,
        principal: AuthenticatedPrincipal,
        *,
        action: str,
    ) -> None:
        if trace.principal == principal:
            return
        record_policy_decision(
            action=action,
            effect="deny",
            rule="conversation_run_scope_mismatch",
            reason="authenticated principal does not own the interaction run",
            permission_scope="conversation_run:read",
            resource=trace.interaction_run_ref,
            user_id=principal.principal_id,
            run_id=trace.interaction_run_ref,
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

    def _admit_project_start(
        self,
        action,
        *,
        all_actions,
        linked_project_reference,
    ):
        if linked_project_reference is not None:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="conversation_project_already_linked",
                message="This Conversation already owns a durable investigation.",
                immutable_fields=("action_id",),
                required_repair=(
                    "Read or steer the linked investigation; do not start a second one."
                ),
                disposition="fail_closed",
            ), None
        if len(all_actions) != 1:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="project_start_requires_independent_commit",
                message="A durable investigation start must be the only action in its turn.",
                repairable_fields=("actions",),
                immutable_fields=("action_id",),
                required_repair="Propose only start_durable_investigation with the complete goal contract.",
            ), None
        if self._project_port is None:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="capability_missing",
                message="Durable investigation is unavailable.",
                immutable_fields=("action_id",),
                required_repair="Explain the limitation; do not claim background work started.",
                disposition="fail_closed",
            ), None
        try:
            return None, StartDurableInvestigationArguments.model_validate(
                action.arguments
            )
        except ValidationError as error:
            return self._invalid_special_arguments(action, error), None

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

    @staticmethod
    def _project_turn_view(conversation_id, run_ref, project_reference):
        return ConversationTurnView(
            interaction_run_ref=run_ref,
            conversation_id=conversation_id,
            disposition="background_started",
            message=ConversationMessage(
                role="assistant",
                content=(
                    "已创建可持续、可恢复的后台调查。你可以随后查看进度、暂停或调整要求。"
                ),
            ),
            project_reference=project_reference,
        )

    def _derive_review_criteria(self, messages):
        """Derive this interaction's frozen verification standard.

        Runs once per interaction, before the first decision turn, so the
        standard exists before there is any answer to measure against it. A
        derivation failure degrades to "not a review request" rather than to a
        runtime-invented criterion.
        """
        try:
            return derive_review_criteria(self._model_client, messages=messages)
        except Exception:
            return ReviewCriteria(), None

    @staticmethod
    def _record_model_usage(usage, response, *, model_turn=False):
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
        validation = self._tool_port.validate_interaction_call(
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
    def _review_answer_required_feedback(decision):
        """Close the non-answer route around verification.

        A review request supplies both the text and the standard, so nothing is
        missing from the user. Ending the turn as a clarification, limitation, or
        failure would deliver unverified text under a disposition the verify step
        never sees, so the runtime rejects the disposition itself and asks for the
        revision that was requested.
        """
        return DecisionFeedback(
            action_id="interaction_turn",
            reason_code="review_requires_sendable_answer",
            message=(
                f"A review request cannot end as {decision.disposition!r}. The user "
                "supplied both the text to review and the requirements it must meet."
            ),
            repairable_fields=("disposition", "message"),
            immutable_fields=("messages",),
            required_repair=(
                "Return disposition 'answer' whose message is the revised sendable "
                "text. Satisfy a requirement that forbids an unevidenced claim by "
                "removing that claim, not by asking the user for the evidence."
            ),
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
                "Call read_action_output for resource_id "
                f"{resource_id!r} with a keyword or start_line that would locate what "
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
    def _unread_offloaded_resources(inputs) -> dict[str, str]:
        """Map unread artifact ids to the capability that produced them."""

        offloaded: dict[str, str] = {}
        for item in inputs:
            if not isinstance(item, ActionObservation):
                continue
            if item.capability_id == READ_ACTION_OUTPUT_CAPABILITY:
                if item.status == "succeeded":
                    offloaded.pop(str(item.payload.get("resource_id", "")), None)
                continue
            if item.status != "succeeded":
                continue
            reference = item.payload.get("retrieval", {})
            if isinstance(reference, dict) and "resource_ref" in reference:
                resource_id = str(reference["resource_ref"].get("resource_id", ""))
                if resource_id:
                    offloaded[resource_id] = item.capability_id
        return offloaded

    def _verify_before_send(
        self,
        decision,
        *,
        review_criteria,
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

        Returns ``(final_message | None, action_result, usage)``: ``None`` means
        the verdict was not ``passed``, and the observation goes back into the
        loop as revision material.
        """
        action_id = f"runtime-verify-{attempt}"
        result = self._execute_one(
            ToolCallProposal(
                action_id=action_id,
                tool_name=_VERIFICATION_CAPABILITY,
                arguments={
                    "draft": decision.message,
                    "success_criteria": list(review_criteria.criteria),
                },
            ),
            (conversation_id, run_ref, principal, owner, source_platform),
        )
        usage = usage.model_copy(update={"tool_calls": usage.tool_calls + 1})
        receipts = observed_receipts(
            (result.interaction_input,),
            capability_names=frozenset({_VERIFICATION_CAPABILITY}),
        )
        passed = next(
            (receipt for receipt in receipts if receipt.verdict == "passed"),
            None,
        )
        if passed is None:
            return None, result, usage
        return (
            FinalMessage(disposition="answer", message=passed.verified_draft),
            result,
            usage,
        )

    def _decide(
        self,
        *,
        messages,
        capabilities,
        inputs,
        usage,
        review_criteria,
        turn_index,
        working_plan,
        interaction_mode,
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
        capability_projection = capabilities.model_dump_json()
        system_content = build_interaction_system_prompt(
            capabilities,
            usage,
            review_criteria,
            budget_policy=self._budget_policy,
            capability_projection=capability_projection,
            working_plan=working_plan,
            interaction_mode=interaction_mode,
        )
        visible_messages = [{"role": "system", "content": system_content}]
        conversation_content = [item.model_dump(mode="json") for item in messages]
        visible_messages.extend(conversation_content)
        typed_inputs_content = ""
        if inputs:
            visible_inputs = materialize_interaction_inputs(inputs)
            typed_inputs_content = "Typed execution inputs:\n" + json.dumps(
                [item.model_dump(mode="json") for item in visible_inputs],
                ensure_ascii=False,
                default=str,
            )
            visible_messages.append({"role": "system", "content": typed_inputs_content})
        response = self._model_client.generate(
            StructuredModelRequest(
                operation="agent_interaction_turn",
                version="v1",
                messages=visible_messages,
                output_type=(
                    AgentTurnDecisionWithPlan
                    if working_plan is not None
                    else AgentTurnDecision
                ),
                context_projection_ref=sealed_context_projection_ref(
                    purpose="agent_interaction_turn",
                    messages=visible_messages,
                ),
                temperature=0,
                max_tokens=1_600,
                metadata={"component": "conversation_interaction_loop"},
            )
        )
        decision = response.value.decision
        composition = TurnContextComposition(
            turn_index=turn_index,
            capability_projection_chars=len(capability_projection),
            # By subtraction, so the two segments are disjoint by construction and
            # always sum to the prompt that was sent.
            system_prompt_other_chars=len(system_content) - len(capability_projection),
            conversation_messages_chars=sum(
                len(item["content"]) for item in conversation_content
            ),
            typed_inputs_chars=len(typed_inputs_content),
            input_tokens=response.input_tokens,
        )
        return decision, response, composition

    def _decide_answer_only(self, *, messages, inputs):
        visible_messages = [{
            "role": "system",
            "content": (
                "Return only the next user-visible outcome as a FinalMessage. Use disposition "
                "answer when the provided typed observations are sufficient for the latest "
                "request; otherwise return a truthful clarification or limitation. Do not "
                "propose tools, agents, another plan, or additional work. A pending checklist "
                "status is not by itself proof that evidence is missing. Do not claim budget "
                "exhaustion unless the typed inputs contain a budget-exhaustion fact. Preserve opaque "
                "identifiers, dates, quantities, version strings, and other exact requested "
                "values byte-for-byte."
            ),
        }]
        visible_messages.extend(item.model_dump(mode="json") for item in messages)
        if inputs:
            visible_inputs = materialize_interaction_inputs(inputs)
            visible_messages.append({
                "role": "system",
                "content": "Typed execution inputs:\n"
                + json.dumps(
                    [item.model_dump(mode="json") for item in visible_inputs],
                    ensure_ascii=False,
                    default=str,
                ),
            })
        response = self._model_client.generate(
            StructuredModelRequest(
                operation="interaction_completion_answer",
                version="v1",
                messages=visible_messages,
                output_type=FinalMessage,
                context_projection_ref=sealed_context_projection_ref(
                    purpose="interaction_completion_answer",
                    messages=visible_messages,
                ),
                temperature=0,
                max_tokens=1_600,
                metadata={"component": "conversation_completion_answer"},
            )
        )
        return response.value, response

    def _effective_capabilities(
        self,
        *,
        linked_project_reference: ProjectReference | None = None,
    ) -> EffectiveCapabilities:
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
                    safely_retryable=False,
                )
            )
        if self._artifact_port is not None:
            tools.append(
                EffectiveToolCapability(
                    name=READ_ACTION_OUTPUT_CAPABILITY,
                    description=(
                        "Re-read the part of an earlier action output that was omitted from its "
                        "observation excerpt. Pass the retrieval.resource_ref from that observation, "
                        "plus a keyword to locate lines anywhere in the full output, or start_line to "
                        "read sequentially. Each keyword hit is returned with the few lines before "
                        "and after it, so a heading also shows what is written under it. Line numbers "
                        "are the source's own, counted from 1. Returns numbered lines, total_lines "
                        "and next_start_line. Read-only."
                    ),
                    input_schema=ReadActionOutputArguments.model_json_schema(),
                    read_only=True,
                    safely_retryable=True,
                )
            )
        if self._knowledge_reader is not None:
            tools.append(
                EffectiveToolCapability(
                    name=_LIST_PERSONAL_KNOWLEDGE_CAPABILITY,
                    description=(
                        "List the caller's current personal knowledge items with canonical "
                        "knowledge_item_id, title, summary, and state. Use this before answering "
                        "questions about stored personal facts or selecting a delete target."
                    ),
                    input_schema=ListPersonalKnowledgeArguments.model_json_schema(),
                    read_only=True,
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
                    safely_retryable=False,
                )
            )
        if self._project_port is not None and linked_project_reference is None:
            tools.append(
                EffectiveToolCapability(
                    name=_START_DURABLE_INVESTIGATION_CAPABILITY,
                    description=(
                        "Start a durable background investigation only when the user's goal requires "
                        "continuity across turns plus later progress inspection, pause, or steering. "
                        "Return a project reference; do not wait for the report in this interaction."
                    ),
                    input_schema=StartDurableInvestigationArguments.model_json_schema(),
                    read_only=False,
                    safely_retryable=False,
                )
            )
        if self._project_port is not None and linked_project_reference is not None:
            tools.append(
                EffectiveToolCapability(
                    name=_STEER_INVESTIGATION_PROJECT_CAPABILITY,
                    description=(
                        "Adjust requirements that are not frozen for the durable investigation "
                        "already linked to this Conversation. The current authoritative snapshot "
                        "is prefetched; the application supplies project identity and plan version."
                    ),
                    input_schema=SteerInvestigationProjectArguments.model_json_schema(),
                    read_only=False,
                    safely_retryable=False,
                ),
            )
        if self._tool_port is not None:
            for candidate in self._tool_port.list_interaction_tools():
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
                        read_only=candidate.read_only,
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
        accepted = [
            action
            for action, feedback in zip(proposal.actions, admitted, strict=True)
            if feedback is None
        ]
        denied = [
            _ActionResult(action.action_id, feedback)
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
                            self._budget_feedback(action.action_id, "tool"),
                        )
                    )
                    continue
                remaining_tool_calls -= 1
                runnable.append(action)
            elif remaining_agent_calls == 0:
                denied.append(
                    _ActionResult(
                        action.action_id,
                        self._budget_feedback(action.action_id, "agent"),
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
        plan_step_ids = {
            action.action_id: action.plan_step_id for action in proposal.actions
        }
        for action_id, item in tuple(by_id.items()):
            if isinstance(item.interaction_input, ActionObservation):
                by_id[action_id] = _ActionResult(
                    action_id,
                    item.interaction_input.model_copy(
                        update={"plan_step_id": plan_step_ids[action_id]}
                    ),
                )
        return (
            [by_id[action.action_id] for action in proposal.actions],
            usage,
            concurrent,
        )

    def _admit(self, action, *, run_ref, committed_action_ids, committed_inputs):
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
            and action.tool_name == READ_ACTION_OUTPUT_CAPABILITY
        ):
            # Service-owned: the artifact port serves it, so the tool registry has no
            # entry to validate against and its schema is the contract.
            if self._artifact_port is None:
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="capability_missing",
                    message=f"Tool {action.tool_name!r} is not currently available.",
                    repairable_fields=("tool_name", "arguments"),
                    immutable_fields=("action_id",),
                    required_repair="Choose an available tool or explain the capability limitation.",
                )
            try:
                ReadActionOutputArguments.model_validate(action.arguments)
            except ValidationError as error:
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="invalid_arguments",
                    message=str(error),
                    repairable_fields=("arguments",),
                    immutable_fields=("action_id", "tool_name"),
                    required_repair="Revise only the arguments to satisfy the declared tool schema.",
                )
            return None
        if (
            isinstance(action, ToolCallProposal)
            and action.tool_name == _STEER_INVESTIGATION_PROJECT_CAPABILITY
        ):
            if (
                self._project_port is None
                or run_ref not in self._run_project_references
            ):
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="linked_project_missing",
                    message="This Conversation has no uniquely linked durable investigation.",
                    immutable_fields=("action_id", "tool_name"),
                    required_repair="Ask the user to start or identify one investigation.",
                    disposition="fail_closed",
                )
            already_observed = any(
                isinstance(item, ActionObservation)
                and item.capability_id == _STEER_INVESTIGATION_PROJECT_CAPABILITY
                and item.status == "succeeded"
                for item in committed_inputs
            )
            if already_observed:
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="project_action_already_committed",
                    message=(
                        "This project action already returned a successful authoritative "
                        "Observation in the current interaction."
                    ),
                    immutable_fields=("action_id", "tool_name"),
                    required_repair=(
                        "Use the committed Observation to answer; do not repeat the read "
                        "or steering side effect."
                    ),
                )
            if (
                not any(
                    isinstance(item, ActionObservation)
                    and item.capability_id == _PROJECT_CONTEXT_CAPABILITY
                    and item.status == "succeeded"
                    for item in committed_inputs
                )
            ):
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="project_snapshot_required",
                    message="Steering requires the current authoritative project snapshot.",
                    immutable_fields=("action_id", "tool_name"),
                    required_repair="Wait for an authoritative linked-project context before steering.",
                )
            try:
                SteerInvestigationProjectArguments.model_validate(action.arguments)
            except ValidationError as error:
                return self._invalid_special_arguments(action, error)
            return None
        if isinstance(action, ToolCallProposal):
            unread = self._unread_offloaded_resources(committed_inputs)
            unread_resource = next(
                (
                    resource_id
                    for resource_id, capability_id in unread.items()
                    if capability_id == action.tool_name
                ),
                None,
            )
            if unread_resource is not None:
                return DecisionFeedback(
                    action_id=action.action_id,
                    reason_code="offloaded_output_refetch",
                    message=(
                        f"Tool {action.tool_name!r} already produced an offloaded output "
                        "that has not been read. Calling it again cannot expose the omitted middle."
                    ),
                    repairable_fields=("tool_name", "arguments"),
                    immutable_fields=("action_id",),
                    required_repair=(
                        "Call read_action_output with the previously supplied resource_ref "
                        f"for resource_id {unread_resource!r} and a keyword or start_line."
                    ),
                )
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
        evidence: the omitted text stays readable through ``read_action_output``,
        so choosing which part matters remains the model's decision.
        """

        bounded = bound_observation_payload(payload)
        if not bounded.is_bounded:
            return bounded.payload
        fitted = dict(bounded.payload)
        retrieval: dict[str, Any] = {
            "omitted_chars": bounded.omitted_chars,
            "original_chars": bounded.original_chars,
        }
        full_text = select_offload_text(payload)
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
            retrieval["read_more"] = (
                "This excerpt omits the middle of the output. To read the omitted part, "
                "call read_action_output with this resource_ref plus either a keyword to "
                "locate it or a start_line to read sequentially."
            )
        fitted["retrieval"] = retrieval
        return fitted

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
        excerpt = excerpt_payload_text(
            text, keyword=arguments.keyword, start_line=arguments.start_line
        )
        payload = {
            "ok": True,
            # Naming the source makes each window attributable when several outputs were
            # offloaded, and lets the loop tell a read remainder from an unread one.
            "resource_id": arguments.resource_ref.resource_id,
            "lines": [{"line": number, "text": line} for number, line in excerpt.lines],
            "total_lines": excerpt.total_lines,
            "keyword_match_count": len(excerpt.matched_lines),
            "next_start_line": excerpt.next_start_line,
        }
        # A window is already line-bounded, but one line can still be huge. Bound it
        # without offloading again: the remainder is still in the same artifact, so a
        # narrower range is the model's remedy, not a second copy.
        bounded = bound_observation_payload(payload)
        window = dict(bounded.payload)
        if bounded.is_bounded:
            window["retrieval"] = {
                "omitted_chars": bounded.omitted_chars,
                "original_chars": bounded.original_chars,
                "read_more": (
                    "This window was too large to show in full. Request a narrower "
                    "start_line range, or a more specific keyword."
                ),
            }
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
            and action.tool_name == READ_ACTION_OUTPUT_CAPABILITY
        ):
            return self._read_action_output(action, principal=principal, owner=owner)
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
        if (
            isinstance(action, ToolCallProposal)
            and action.tool_name == _STEER_INVESTIGATION_PROJECT_CAPABILITY
        ):
            reference = self._run_project_references[run_ref]
            try:
                arguments = SteerInvestigationProjectArguments.model_validate(
                    action.arguments
                )
                snapshot = self._project_port.steer(
                    principal=principal,
                    reference=reference,
                    request=arguments,
                    idempotency_key=sha256(
                        f"{run_ref}:{action.action_id}".encode("utf-8")
                    ).hexdigest(),
                )
            except (KeyError, PermissionError, ValueError) as error:
                return _ActionResult(
                    action.action_id,
                    ActionObservation(
                        kind="tool_result",
                        action_id=action.action_id,
                        capability_id=action.tool_name,
                        status="failed",
                        payload={
                            "error_kind": "application_operation_rejected",
                            "error": str(error),
                        },
                    ),
                )
            return _ActionResult(
                action.action_id,
                ActionObservation(
                    kind="tool_result",
                    action_id=action.action_id,
                    capability_id=action.tool_name,
                    status="succeeded",
                    payload=snapshot.model_dump(mode="json"),
                ),
            )
        if isinstance(action, ToolCallProposal):
            result = self._tool_port.invoke_interaction(
                action.tool_name,
                action.arguments,
                execution_scope=execution_scope,
                tool_call_id=action.action_id,
                source_platform=source_platform,
            )
            return _ActionResult(
                action.action_id,
                ActionObservation(
                    kind="tool_result",
                    action_id=action.action_id,
                    capability_id=action.tool_name,
                    status="succeeded" if result.get("ok") else "failed",
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
        gateway_context = AgentGatewayContext(
            execution_scope=execution_scope,
            source_platform=source_platform,
        )
        grant = self._delegation_grant(action, run_ref)
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
            deadline = monotonic() + action.time_budget_seconds
            while run.projection.status in {"created", "queued", "running"}:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    run = self._agent_port.cancel(
                        run.definition.agent_run_id,
                        gateway_context,
                    )
                    break
                sleep(min(0.25, remaining))
                run = self._agent_port.poll(
                    run.definition.agent_run_id, gateway_context
                )
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
        final = FinalMessage(
            disposition="limitation",
            message="本次交互已达到执行预算上限，未生成替代答案。可增加预算后基于已提交结果继续。",
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
            message=ConversationMessage(
                role="assistant",
                content=final.message,
            ),
            project_reference=self._run_project_references.get(run_ref),
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
        project_reference=None,
        working_plan=None,
    ):
        prior = self._journal.get(run_ref)
        self._journal.put(
            InteractionTrace(
                revision=(prior.revision + 1 if prior is not None else 1),
                interaction_run_ref=run_ref,
                conversation_id=self._run_conversation_ids[run_ref],
                principal=principal,
                messages=tuple(messages),
                inputs=tuple(inputs),
                usage=usage,
                execution_order=tuple(execution_order),
                concurrent_batches=tuple(concurrent_batches),
                context_composition=tuple(context_composition),
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
                project_reference=(
                    project_reference
                    if project_reference is not None
                    else (
                        prior.project_reference
                        if prior is not None
                        else self._run_project_references.get(run_ref)
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
    "ConversationUnavailable",
    "FileInteractionJournal",
    "InMemoryInteractionJournal",
]

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import RLock
from time import monotonic, sleep
from uuid import uuid4

from personal_agent.capabilities.contracts.grants import DelegationGrant, GrantDependencySet
from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.kernel.contracts.agent import AgentGatewayContext, AgentTask
from personal_agent.kernel.contracts.resource import OperationScope, ResourceSelector
from personal_agent.kernel.contracts.scope import (
    AuthenticatedPrincipal,
    ExecutionScope,
    SecurityScope,
)

from .models import (
    ActionObservation,
    AgentDelegationProposal,
    AgentTurnDecision,
    CommittedUsage,
    ContinueTurnProposal,
    ConversationKnowledgeSaveCommand,
    ConversationKnowledgeSaveOperation,
    ConversationKnowledgeSaveReceipt,
    ConversationMessage,
    ConversationTurnView,
    DecisionFeedback,
    EffectiveAgentCapability,
    EffectiveCapabilities,
    EffectiveToolCapability,
    FinalMessage,
    InteractionTrace,
    KnowledgeSaveArguments,
    LoopBudgetPolicy,
    ToolCallProposal,
)
from .ports import (
    ConversationKnowledgeWriter,
    InteractionAgentPort,
    InteractionArtifactPort,
    InteractionToolPort,
)


class ConversationUnavailable(RuntimeError):
    pass


class ConversationOperationNotFound(LookupError):
    pass


class ConversationOperationConflict(RuntimeError):
    pass


_KNOWLEDGE_SAVE_CAPABILITY = "prepare_conversation_knowledge_save"


@dataclass(frozen=True, slots=True)
class _ActionResult:
    action_id: str
    interaction_input: ActionObservation | DecisionFeedback


class InMemoryInteractionJournal:
    """Append-only execution facts used to rebuild transient interaction context."""

    def __init__(self) -> None:
        self._traces: dict[str, InteractionTrace] = {}
        self._lock = RLock()

    def put(self, trace: InteractionTrace) -> None:
        with self._lock:
            self._traces[trace.interaction_run_ref] = trace

    def get(self, interaction_run_ref: str) -> InteractionTrace | None:
        with self._lock:
            return self._traces.get(interaction_run_ref)


class FileInteractionJournal(InMemoryInteractionJournal):
    """Durable append-only snapshots of committed interaction facts."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, trace: InteractionTrace) -> None:
        super().put(trace)
        run_dir = self._root / trace.interaction_run_ref
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / f"{trace.revision:04d}.json"
        if target.exists():
            return
        temporary = run_dir / f".{trace.revision:04d}.{uuid4().hex}.tmp"
        temporary.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, target)

    def get(self, interaction_run_ref: str) -> InteractionTrace | None:
        cached = super().get(interaction_run_ref)
        if cached is not None:
            return cached
        run_dir = self._root / interaction_run_ref
        snapshots = sorted(run_dir.glob("*.json")) if run_dir.exists() else []
        if not snapshots:
            return None
        trace = InteractionTrace.model_validate_json(snapshots[-1].read_text(encoding="utf-8"))
        super().put(trace)
        return trace


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
        budget_policy: LoopBudgetPolicy | None = None,
        journal: InMemoryInteractionJournal | None = None,
    ) -> None:
        self._model_client = model_client
        self._tool_port = tool_port
        self._agent_port = agent_port
        self._artifact_port = artifact_port
        self._knowledge_writer = knowledge_writer
        self._confirmation_lock = RLock()
        if agent_port is not None and artifact_port is None:
            raise ValueError("agent delegation requires the canonical Artifact read port")
        self._budget_policy = budget_policy or LoopBudgetPolicy()
        self._journal = journal or InMemoryInteractionJournal()

    def respond(
        self,
        *,
        conversation_id: str,
        messages: list[ConversationMessage],
        principal: AuthenticatedPrincipal,
        security_scope: SecurityScope,
        source_platform: str = "web",
        interaction_run_ref: str | None = None,
    ) -> ConversationTurnView:
        if not messages or messages[-1].role != "user":
            raise ValueError("conversation must end with a user message")
        if self._model_client is None:
            raise ConversationUnavailable("conversation model is not configured")
        if (
            principal.tenant_id != security_scope.tenant_id
        ):
            raise PermissionError("conversation principal and security scope mismatch")

        run_ref = interaction_run_ref or f"irun_{uuid4().hex[:16]}"
        capabilities = self._effective_capabilities()
        prior = self._journal.get(run_ref)
        if prior is not None and tuple(messages) != prior.messages:
            raise ValueError("interaction_run_ref is already bound to different user input")
        if prior is not None and prior.knowledge_save_operation is not None:
            return self._knowledge_save_turn_view(
                conversation_id,
                run_ref,
                prior.knowledge_save_operation,
            )
        if prior is not None and prior.final_message is not None:
            return ConversationTurnView(
                interaction_run_ref=run_ref,
                conversation_id=conversation_id,
                disposition=prior.final_message.disposition,
                message=ConversationMessage(role="assistant", content=prior.final_message.message),
            )
        inputs = list(prior.inputs if prior else ())
        execution_order = list(prior.execution_order if prior else ())
        concurrent_batches = list(prior.concurrent_batches if prior else ())
        usage = prior.usage if prior else CommittedUsage()

        while usage.model_turns < self._budget_policy.max_model_turns:
            if usage.total_tokens >= self._budget_policy.max_total_tokens:
                return self._budget_exhausted(conversation_id, run_ref, messages, capabilities, inputs, usage, execution_order, concurrent_batches)
            decision, token_count = self._decide(
                messages=messages,
                capabilities=capabilities,
                inputs=inputs,
                usage=usage,
            )
            usage = usage.model_copy(update={
                "model_turns": usage.model_turns + 1,
                "total_tokens": usage.total_tokens + token_count,
            })
            verification_feedback = self._admit_final_verification(decision, inputs=inputs)
            if verification_feedback is not None:
                inputs.append(verification_feedback)
                self._commit(
                    run_ref, messages, capabilities, inputs, usage,
                    execution_order, concurrent_batches,
                )
                continue
            if isinstance(decision, FinalMessage):
                self._commit(run_ref, messages, capabilities, inputs, usage, execution_order, concurrent_batches, final_message=decision)
                return ConversationTurnView(
                    interaction_run_ref=run_ref,
                    conversation_id=conversation_id,
                    disposition=decision.disposition,
                    message=ConversationMessage(role="assistant", content=decision.message.strip()),
                )

            save_actions = [
                action for action in decision.actions
                if (
                    isinstance(action, ToolCallProposal)
                    and action.tool_name == _KNOWLEDGE_SAVE_CAPABILITY
                )
            ]
            if save_actions:
                action = save_actions[0]
                feedback, arguments = self._admit_knowledge_save(
                    action,
                    all_actions=decision.actions,
                    messages=messages,
                )
                if feedback is not None:
                    inputs.append(feedback)
                    self._commit(
                        run_ref, messages, capabilities, inputs, usage,
                        execution_order, concurrent_batches,
                    )
                    continue
                operation = self._prepare_knowledge_save(
                    action,
                    arguments=arguments,
                    run_ref=run_ref,
                    messages=messages,
                    principal=principal,
                    security_scope=security_scope,
                )
                self._commit(
                    run_ref, messages, capabilities, inputs, usage,
                    execution_order, concurrent_batches,
                    knowledge_save_operation=operation,
                )
                return self._knowledge_save_turn_view(
                    conversation_id,
                    run_ref,
                    operation,
                )

            results, usage, concurrent = self._execute_actions(
                decision,
                conversation_id=conversation_id,
                run_ref=run_ref,
                principal=principal,
                security_scope=security_scope,
                source_platform=source_platform,
                usage=usage,
                committed_action_ids=frozenset(execution_order),
                committed_inputs=tuple(inputs),
            )
            inputs.extend(item.interaction_input for item in results)
            execution_order.extend(item.action_id for item in results)
            if concurrent:
                concurrent_batches.append(tuple(item.action_id for item in results))
            self._commit(run_ref, messages, capabilities, inputs, usage, execution_order, concurrent_batches)

        return self._budget_exhausted(conversation_id, run_ref, messages, capabilities, inputs, usage, execution_order, concurrent_batches)

    def trace(self, interaction_run_ref: str) -> InteractionTrace | None:
        return self._journal.get(interaction_run_ref)

    def decide_knowledge_save(
        self,
        *,
        interaction_run_ref: str,
        principal: AuthenticatedPrincipal,
        security_scope: SecurityScope,
        decision: str,
        command_digest: str,
        confirmation_ref: str,
    ) -> ConversationKnowledgeSaveOperation:
        if decision not in {"confirm", "reject"}:
            raise ValueError("decision must be confirm or reject")
        if principal.tenant_id != security_scope.tenant_id:
            raise PermissionError("conversation principal and security scope mismatch")
        with self._confirmation_lock:
            trace = self._journal.get(interaction_run_ref)
            if trace is None or trace.knowledge_save_operation is None:
                raise ConversationOperationNotFound("knowledge save operation not found")
            operation = trace.knowledge_save_operation
            command = operation.command
            if (
                command.tenant_id != principal.tenant_id
                or command.user_id != principal.user_id
                or command.workspace_id != security_scope.workspace_id
            ):
                raise PermissionError("knowledge save operation scope mismatch")
            if command.command_digest != command_digest:
                raise ConversationOperationConflict("command digest mismatch")
            if operation.status == "executed":
                if decision != "confirm":
                    raise ConversationOperationConflict("executed operation cannot be rejected")
                return operation
            if operation.status == "rejected":
                if decision != "reject":
                    raise ConversationOperationConflict("rejected operation cannot be confirmed")
                return operation
            if decision == "reject":
                updated = ConversationKnowledgeSaveOperation(
                    command=command,
                    status="rejected",
                )
            else:
                normalized_confirmation_ref = confirmation_ref.strip()
                if not normalized_confirmation_ref:
                    raise ValueError("confirmation_ref is required when confirming")
                if self._knowledge_writer is None:
                    raise ConversationUnavailable("conversation knowledge writer is not configured")
                result = self._knowledge_writer.solidify_conversation(
                    [message.model_dump(mode="json") for message in command.messages],
                    user_id=command.user_id,
                    workspace_id=command.workspace_id,
                )
                ingest = result.ingest_result
                receipt = ConversationKnowledgeSaveReceipt(
                    command_id=command.command_id,
                    command_digest=command.command_digest,
                    confirmation_ref=normalized_confirmation_ref,
                    artifact_id=ingest.artifact.artifact_id,
                    claim_ids=tuple(claim.claim_id for claim in ingest.claims),
                    knowledge_item_ids=tuple(
                        item.knowledge_item_id for item in ingest.knowledge_items
                    ),
                    user_claim_count=result.user_claim_count,
                )
                updated = ConversationKnowledgeSaveOperation(
                    command=command,
                    status="executed",
                    receipt=receipt,
                )
            self._journal.put(trace.model_copy(update={
                "revision": trace.revision + 1,
                "knowledge_save_operation": updated,
            }))
            return updated

    def _admit_knowledge_save(self, action, *, all_actions, messages):
        if len(all_actions) != 1:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="knowledge_save_requires_independent_confirmation",
                message="A knowledge save proposal must be the only action in its turn.",
                repairable_fields=("actions",),
                immutable_fields=("messages",),
                required_repair="Propose only the knowledge_save action so its exact payload can be confirmed.",
            ), None
        if self._knowledge_writer is None:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="capability_missing",
                message="The governed knowledge save capability is unavailable.",
                immutable_fields=("messages",),
                required_repair="Explain that saving is unavailable; do not claim that knowledge was saved.",
                disposition="fail_closed",
            ), None
        try:
            arguments = KnowledgeSaveArguments.model_validate(action.arguments)
        except ValueError:
            return self._knowledge_save_index_feedback(action.action_id), None
        indexes = tuple(
            selection.source_message_index for selection in arguments.selections
        )
        if len(indexes) != len(set(indexes)):
            return self._knowledge_save_index_feedback(action.action_id), None
        if any(
            index < 0
            or index >= len(messages)
            or messages[index].role != "user"
            for index in indexes
        ):
            return self._knowledge_save_index_feedback(action.action_id), None
        if any(
            not selection.text_span.strip()
            or selection.text_span.strip() not in messages[
                selection.source_message_index
            ].content
            for selection in arguments.selections
        ):
            return self._knowledge_save_index_feedback(action.action_id), None
        return None, arguments

    @staticmethod
    def _knowledge_save_index_feedback(action_id):
        return DecisionFeedback(
            action_id=action_id,
            reason_code="invalid_knowledge_save_source",
            message=(
                "Knowledge save selections must be exact non-empty spans from unique "
                "existing user messages."
            ),
            repairable_fields=("selections",),
            immutable_fields=("messages", "action_id"),
            required_repair=(
                "Select the exact user-authored knowledge span, excluding the request "
                "to save and confirmation instructions."
            ),
        )

    def _prepare_knowledge_save(
        self,
        action,
        *,
        arguments,
        run_ref,
        messages,
        principal,
        security_scope,
    ):
        selected = tuple(
            ConversationMessage(
                role="user",
                content=selection.text_span.strip(),
            )
            for selection in arguments.selections
        )
        source_message_indexes = tuple(
            selection.source_message_index for selection in arguments.selections
        )
        command_id = "ksave_" + sha256(run_ref.encode("utf-8")).hexdigest()[:20]
        canonical = {
            "command_id": command_id,
            "action_id": action.action_id,
            "interaction_run_ref": run_ref,
            "tenant_id": principal.tenant_id,
            "workspace_id": security_scope.workspace_id,
            "user_id": principal.user_id,
            "source_message_indexes": source_message_indexes,
            "messages": [message.model_dump(mode="json") for message in selected],
            "policy_revision": "conversation-knowledge-save-v1",
        }
        digest = sha256(json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        return ConversationKnowledgeSaveOperation(
            command=ConversationKnowledgeSaveCommand(
                **canonical,
                command_digest=digest,
            ),
            status="awaiting_confirmation",
        )

    @staticmethod
    def _knowledge_save_turn_view(conversation_id, run_ref, operation):
        messages = {
            "awaiting_confirmation": "请确认是否保存所选内容。确认前不会写入长期知识。",
            "rejected": "已取消保存，未写入长期知识。",
            "executed": "已保存所选内容。",
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
                role="assistant",
                content=messages[operation.status],
            ),
            pending_confirmation=(
                operation if operation.status == "awaiting_confirmation" else None
            ),
        )

    def _decide(self, *, messages, capabilities, inputs, usage):
        visible_messages = [
            {"role": "system", "content": self._system_prompt(capabilities, usage)},
            *(item.model_dump(mode="json") for item in messages),
        ]
        if inputs:
            visible_messages.append({
                "role": "system",
                "content": "Typed execution inputs:\n" + json.dumps(
                    [item.model_dump(mode="json") for item in inputs], ensure_ascii=False, default=str
                ),
            })
        response = self._model_client.generate(StructuredModelRequest(
            operation="agent_interaction_turn",
            version="v1",
            messages=visible_messages,
            output_type=AgentTurnDecision,
            context_projection_ref=sealed_context_projection_ref(
                purpose="agent_interaction_turn", messages=visible_messages,
            ),
            temperature=0,
            max_tokens=1_600,
            metadata={"component": "conversation_interaction_loop"},
        ))
        decision = response.value.decision
        token_count = response.total_tokens or (
            (response.input_tokens or 0) + (response.output_tokens or 0)
        )
        return decision, token_count

    @staticmethod
    def _admit_final_verification(decision, *, inputs) -> DecisionFeedback | None:
        receipt = None
        for item in reversed(inputs):
            if (
                isinstance(item, ActionObservation)
                and item.capability_id == "verify_interaction_draft"
                and item.status == "succeeded"
            ):
                candidate = item.payload.get("data")
                if isinstance(candidate, dict):
                    receipt = candidate
                    break
        if receipt is None:
            return None
        verdict = receipt.get("verdict")
        if isinstance(decision, ContinueTurnProposal):
            repeats_verification = any(
                isinstance(action, ToolCallProposal)
                and action.tool_name == "verify_interaction_draft"
                for action in decision.actions
            )
            if verdict == "passed" and repeats_verification:
                return ConversationService._verification_completion_feedback(
                    receipt,
                    reason_code="verified_draft_ready",
                )
            return None
        if not isinstance(decision, FinalMessage) or decision.disposition != "answer":
            return None
        expected_digest = sha256(decision.message.strip().encode("utf-8")).hexdigest()
        if verdict == "passed" and receipt.get("draft_digest") == expected_digest:
            return None
        reason_code = (
            "verified_draft_mismatch" if verdict == "passed"
            else "verification_required"
        )
        return ConversationService._verification_completion_feedback(
            receipt,
            reason_code=reason_code,
        )

    @staticmethod
    def _verification_completion_feedback(receipt, *, reason_code) -> DecisionFeedback:
        return DecisionFeedback(
            action_id="interaction_turn",
            reason_code=reason_code,
            message=(
                "An answer must reuse the exact draft bound to the latest passed "
                "verify_interaction_draft receipt."
            ),
            repairable_fields=("actions",),
            immutable_fields=("messages", "inputs", "execution_order"),
            required_repair=(
                "Submit the exact revised final text to verify_interaction_draft using the original "
                "success criteria, wait for a passed receipt, then return verified_draft unchanged. "
                f"Latest verified_draft: {receipt.get('verified_draft', '')}"
            ),
        )

    def _effective_capabilities(self) -> EffectiveCapabilities:
        tools: list[EffectiveToolCapability] = []
        if self._knowledge_writer is not None:
            tools.append(EffectiveToolCapability(
                name=_KNOWLEDGE_SAVE_CAPABILITY,
                description=(
                    "Prepare an immutable, user-confirmed save of knowledge already present "
                    "in selected user messages. This action does not write knowledge."
                ),
                input_schema=KnowledgeSaveArguments.model_json_schema(),
                read_only=False,
                safely_retryable=False,
            ))
        if self._tool_port is not None:
            for candidate in self._tool_port.list_interaction_tools():
                tools.append(EffectiveToolCapability(
                    name=candidate.name,
                    description=candidate.description,
                    input_schema=candidate.input_schema,
                    read_only=candidate.read_only,
                    safely_retryable=candidate.safely_retryable,
                ))
        agents = tuple(
            EffectiveAgentCapability(
                agent_id=profile.agent_id,
                description=profile.description,
                task_types=profile.task_types,
                allowed_operations=profile.allowed_operations,
            )
            for profile in (self._agent_port.profiles() if self._agent_port else ())
        )
        canonical = json.dumps({
            "tools": [item.model_dump(mode="json") for item in tools],
            "agents": [item.model_dump(mode="json") for item in agents],
        }, sort_keys=True, default=str)
        return EffectiveCapabilities(
            revision=sha256(canonical.encode("utf-8")).hexdigest()[:16],
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
        security_scope,
        source_platform,
        usage,
        committed_action_ids,
        committed_inputs,
    ):
        admitted = [
            self._admit(
                action,
                committed_action_ids=committed_action_ids,
                committed_inputs=committed_inputs,
            )
            for action in proposal.actions
        ]
        accepted = [action for action, feedback in zip(proposal.actions, admitted, strict=True) if feedback is None]
        denied = [
            _ActionResult(action.action_id, feedback)
            for action, feedback in zip(proposal.actions, admitted, strict=True)
            if feedback is not None
        ]
        runnable: list[ToolCallProposal | AgentDelegationProposal] = []
        for action in accepted:
            if isinstance(action, ToolCallProposal) and usage.tool_calls >= self._budget_policy.max_tool_calls:
                denied.append(_ActionResult(action.action_id, self._budget_feedback(action.action_id, "tool")))
            elif isinstance(action, AgentDelegationProposal) and usage.agent_calls >= self._budget_policy.max_agent_calls:
                denied.append(_ActionResult(action.action_id, self._budget_feedback(action.action_id, "agent")))
            else:
                runnable.append(action)
        concurrent = len(runnable) > 1 and all(self._safe_for_concurrency(item) for item in runnable)
        context = (
            conversation_id,
            run_ref,
            principal,
            security_scope,
            source_platform,
        )
        if concurrent:
            with ThreadPoolExecutor(max_workers=min(len(runnable), self._budget_policy.max_concurrency)) as pool:
                futures = [pool.submit(self._execute_one, item, context) for item in runnable]
                executed = [future.result() for future in futures]
        else:
            executed = [self._execute_one(item, context) for item in runnable]
        usage = usage.model_copy(update={
            "tool_calls": usage.tool_calls + sum(isinstance(item, ToolCallProposal) for item in runnable),
            "agent_calls": usage.agent_calls + sum(isinstance(item, AgentDelegationProposal) for item in runnable),
        })
        by_id = {item.action_id: item for item in (*executed, *denied)}
        return [by_id[action.action_id] for action in proposal.actions], usage, concurrent

    def _admit(self, action, *, committed_action_ids, committed_inputs):
        if action.action_id in committed_action_ids:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="duplicate_action_id",
                message="The action_id is already bound to a committed interaction action.",
                repairable_fields=("action_id",),
                immutable_fields=("kind",),
                required_repair="Create a new proposal with a fresh action_id; do not replay the prior action.",
            )
        if isinstance(action, ToolCallProposal):
            if self._tool_port is None:
                return DecisionFeedback(
                    action_id=action.action_id, reason_code="capability_missing",
                    message=f"Tool {action.tool_name!r} is not currently available.",
                    repairable_fields=("tool_name", "arguments"), immutable_fields=("action_id",),
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
        profile = self._agent_port.profile(action.agent_id) if self._agent_port else None
        if profile is None:
            return DecisionFeedback(
                action_id=action.action_id, reason_code="capability_missing",
                message=f"Agent {action.agent_id!r} is not currently available.",
                repairable_fields=("agent_id", "bounded_sub_goal"), immutable_fields=("action_id",),
                required_repair="Choose an available agent or explain the capability limitation.",
            )
        observed_artifact_refs = {
            str(artifact_ref)
            for item in committed_inputs
            if isinstance(item, ActionObservation)
            and item.kind == "agent_artifact"
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
                repairable_fields=("agent_id", "bounded_sub_goal", "context_projection_refs"),
                immutable_fields=("action_id",),
                required_repair=(
                    "Assess the existing artifact and return the parent synthesis. If a distinct downstream "
                    "specialist is genuinely required, select a different available agent and cite the observed "
                    "artifact_ref as its context dependency."
                ),
            )
        if (
            observed_artifact_refs
            and observed_artifact_refs.isdisjoint(action.context_projection_refs)
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
            return bool(
                self._tool_port
                and self._tool_port.interaction_call_is_safe_for_concurrency(
                    action.tool_name
                )
            )
        profile = self._agent_port.profile(action.agent_id) if self._agent_port else None
        return bool(profile and set(profile.allowed_operations) <= {"delegate", "read"})

    def _execute_one(self, action, context):
        conversation_id, run_ref, principal, security_scope, source_platform = context
        execution_scope = ExecutionScope(
            security_scope=security_scope,
            principal_id=principal.principal_id,
            execution_id=run_ref,
            thread_id=conversation_id,
            task_id=action.action_id,
        )
        if isinstance(action, ToolCallProposal):
            result = self._tool_port.invoke_interaction(
                action.tool_name,
                action.arguments,
                execution_scope=execution_scope,
                tool_call_id=action.action_id,
                source_platform=source_platform,
            )
            return _ActionResult(action.action_id, ActionObservation(
                kind="tool_result", action_id=action.action_id, capability_id=action.tool_name,
                status="succeeded" if result.get("ok") else "failed", payload=result,
            ))
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
                    metadata={"expected_artifact_types": action.expected_artifact_types},
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
                run = self._agent_port.poll(run.definition.agent_run_id, gateway_context)
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
                    security_scope=security_scope,
                )
                payload["artifacts"].append({
                    "artifact_ref": item.artifact_ref.model_dump(mode="json"),
                    "kind": item.kind,
                    "content_excerpt": content[:6_000],
                    "content_length": len(content),
                    "content_sha256": sha256(content.encode("utf-8")).hexdigest(),
                })
            status = {
                "completed": "succeeded",
                "completed_degraded": "succeeded",
                "failed": "failed",
                "timed_out": "failed",
                "cancelled": "cancelled",
            }.get(run.projection.status, "running")
            return _ActionResult(action.action_id, ActionObservation(
                kind="agent_artifact" if payload["artifact_refs"] else "agent_status",
                action_id=action.action_id, capability_id=action.agent_id,
                status=status, payload=payload,
            ))
        except Exception as exc:
            return _ActionResult(action.action_id, ActionObservation(
                kind="agent_status", action_id=action.action_id, capability_id=action.agent_id,
                status="failed", payload={"error": str(exc)},
            ))

    @staticmethod
    def _delegation_grant(action, run_ref):
        digest = sha256(json.dumps(action.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        return DelegationGrant(
            request_id=run_ref, action_ref=action.action_id,
            authorization_digest=digest, execution_command_digest=digest,
            granted_resource_selector=ResourceSelector(),
            granted_operation_scope=OperationScope(operations=frozenset({"delegate"}), side_effect_class="external_network"),
            granted_data_egress="content", granted_credential_mode="provider_managed",
            retry_family_id=digest, dependency_set=GrantDependencySet(
                task_revision=1, goal_definition_fingerprint=digest,
                action_fingerprint=digest, capability_definition_revision=1,
                provider_binding_revision=1, authority_revision=1,
                policy_bundle_hash="interaction-loop-v1",
            ),
            agent_binding_ref=f"agent:{action.agent_id}", bounded_sub_goal=action.bounded_sub_goal,
            context_projection_refs=action.context_projection_refs,
            token_budget=action.token_budget, cost_budget=action.cost_budget,
            time_budget_seconds=action.time_budget_seconds,
            completion_contract="return typed status and artifact refs to parent",
        )

    def _system_prompt(self, capabilities, usage):
        remaining = {
            "model_turns": self._budget_policy.max_model_turns - usage.model_turns,
            "tool_calls": self._budget_policy.max_tool_calls - usage.tool_calls,
            "agent_calls": self._budget_policy.max_agent_calls - usage.agent_calls,
            "tokens": self._budget_policy.max_total_tokens - usage.total_tokens,
        }
        return (
            "You are the interaction runtime's semantic decision maker. Return one root JSON object with "
            "exactly the key decision: {\"decision\": <FinalMessage | ContinueTurnProposal>}. Put the "
            "lowercase schema kind inside decision and inside each action. Never place kind, type, "
            "actions, disposition, or message at the root, and never emit model class names. "
            "A final decision has exactly this shape: {\"decision\": {\"kind\": \"final_message\", "
            "\"disposition\": \"answer|clarification_required|limitation|failed\", \"message\": \"...\"}}. "
            "A continuing decision has this shape: {\"decision\": {\"kind\": \"continue_turn\", "
            "\"actions\": [<typed action>, ...]}}. "
            "The latest user message owns the current goal. If it only says to handle, continue, improve, or "
            "change something without identifying the target or desired result, you MUST return "
            "clarification_required and ask one concrete question. Repeating an earlier assistant answer is "
            "never a valid response to such a new underspecified request. "
            "When the user explicitly asks to save knowledge already present in one or more user messages, "
            "call the available prepare_conversation_knowledge_save capability as the only action, with "
            "arguments {\"selections\": [{\"source_message_index\": <zero-based index>, "
            "\"text_span\": \"<exact user-authored knowledge only>\"}]}. "
            "Copy each text_span exactly from its user message and exclude the request to save, confirmation "
            "instructions, and other control text. Never select assistant text or paraphrase the saved payload. "
            "This proposal only prepares immutable confirmation; it does not claim the save happened. "
            "Use only listed effective capabilities. Never claim a tool result "
            "before receiving its typed observation. Admission feedback must be repaired by a new proposal; "
            "do not assume rejected actions ran. A remote agent completion is evidence for you to assess, "
            "not automatic completion of the user's request. Ask/reading never implies Save/writing. "
            "After an agent_artifact Observation with nonempty artifact_refs, assess that Artifact and produce "
            "the parent synthesis. A child cancelled/failed status does not erase a returned Artifact, and the "
            "Artifact still does not prove parent completion. You MUST NOT call the same agent_id again in this "
            "interaction. A genuinely distinct "
            "dependent delegation must use a different available agent and cite the observed artifact_ref in "
            "context_projection_refs. AgentArtifact payloads already contain the parent-visible evidence "
            "excerpt. The inspect_artifact tool is only for application-owned uploaded ResourceRef values; "
            "never pass an AgentArtifact aart_* reference to it. "
            "Use an available deep-research agent for a user-requested comprehensive external research report "
            "that requires multi-source synthesis, comparison, or analysis. Use a read-only search tool for "
            "narrow lookups; do not replace a requested deep-research deliverable with a superficial lookup. "
            "When the user's goal requires multiple independent read-only results, propose the necessary "
            "independent calls together in one actions list and wait for every observation before answering; "
            "the user does not need to know or name internal capabilities. Lack of prior observations is not a "
            "capability limitation. When the user explicitly asks to review or revise a draft against stated "
            "success criteria, use an available semantic verifier before returning the reviewed text. After "
            "verifier feedback, "
            "revise unsupported or prohibited claims, and do not repeat a rejected claim verbatim in the final "
            "answer, including as a quotation or explanation. If a criterion prohibits asserting that an event "
            "occurred, remove every positive or presupposed occurrence claim; a minimal draft that makes no claim "
            "about that event is valid repair material. Submit the exact revised final text to the verifier "
            "again and, after a passed receipt, return verified_draft unchanged without another verifier call. "
            "Ask for clarification whenever required user input is missing. "
            + "Effective capabilities: " + capabilities.model_dump_json()
            + " Remaining budget: " + json.dumps(remaining)
        )

    @staticmethod
    def _budget_feedback(action_id, kind):
        return DecisionFeedback(
            action_id=action_id, reason_code="budget_exhausted",
            message=f"The committed {kind} call budget is exhausted.",
            immutable_fields=("action_id",), required_repair="Stop or request additional budget.",
            disposition="fail_closed",
        )

    def _budget_exhausted(self, conversation_id, run_ref, messages, capabilities, inputs, usage, execution_order, concurrent_batches):
        final = FinalMessage(
            disposition="limitation",
            message="本次交互已达到执行预算上限，未生成替代答案。可增加预算后基于已提交结果继续。",
        )
        self._commit(run_ref, messages, capabilities, inputs, usage, execution_order, concurrent_batches, final_message=final)
        return ConversationTurnView(
            interaction_run_ref=run_ref,
            conversation_id=conversation_id,
            disposition="limitation",
            message=ConversationMessage(
                role="assistant",
                content=final.message,
            ),
        )

    def _commit(
        self,
        run_ref,
        messages,
        capabilities,
        inputs,
        usage,
        execution_order,
        concurrent_batches,
        final_message=None,
        knowledge_save_operation=None,
    ):
        prior = self._journal.get(run_ref)
        self._journal.put(InteractionTrace(
            revision=(prior.revision + 1 if prior is not None else 1),
            interaction_run_ref=run_ref, capability_revision=capabilities.revision,
            messages=tuple(messages),
            inputs=tuple(inputs), usage=usage,
            execution_order=tuple(execution_order), concurrent_batches=tuple(concurrent_batches),
            final_message=final_message,
            knowledge_save_operation=knowledge_save_operation,
        ))


__all__ = [
    "ConversationOperationConflict", "ConversationOperationNotFound", "ConversationService",
    "ConversationUnavailable", "FileInteractionJournal",
    "InMemoryInteractionJournal",
]

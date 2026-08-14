"""Conversation-owned preparation and confirmation of explicit knowledge saves."""

from __future__ import annotations

from hashlib import sha256
import json
from threading import RLock

from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

from .errors import (
    ConversationOperationConflict,
    ConversationOperationNotFound,
    ConversationUnavailable,
)
from .journal import InMemoryInteractionJournal
from .models import (
    ConversationKnowledgeSaveCommand,
    ConversationKnowledgeSaveOperation,
    ConversationKnowledgeSaveReceipt,
    ConversationMessage,
    ConversationTurnView,
    DecisionFeedback,
    KnowledgeSaveArguments,
)
from .ports import ConversationKnowledgeWriter


class ConversationKnowledgeSaveUseCase:
    """Own the prepare-confirm-commit boundary for one explicit save request."""

    def __init__(
        self,
        *,
        writer: ConversationKnowledgeWriter | None,
        journal: InMemoryInteractionJournal,
    ) -> None:
        self._writer = writer
        self._journal = journal
        self._confirmation_lock = RLock()

    def decide(
        self,
        *,
        interaction_run_ref: str,
        principal: AuthenticatedPrincipal,
        decision: str,
        confirmation_ref: str,
    ) -> ConversationKnowledgeSaveOperation:
        if decision not in {"confirm", "reject"}:
            raise ValueError("decision must be confirm or reject")
        owner = principal
        with self._confirmation_lock:
            trace = self._journal.get(interaction_run_ref)
            if trace is None or trace.knowledge_save_operation is None:
                raise ConversationOperationNotFound(
                    "knowledge save operation not found"
                )
            operation = trace.knowledge_save_operation
            command = operation.command
            if (
                command.tenant_id != principal.tenant_id
                or command.user_id != principal.user_id
                or command.owner_id != owner.principal_id
            ):
                raise PermissionError("knowledge save operation scope mismatch")
            if operation.status == "executed":
                if decision != "confirm":
                    raise ConversationOperationConflict(
                        "executed operation cannot be rejected"
                    )
                return operation
            if operation.status == "rejected":
                if decision != "reject":
                    raise ConversationOperationConflict(
                        "rejected operation cannot be confirmed"
                    )
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
                if self._writer is None:
                    raise ConversationUnavailable(
                        "conversation knowledge writer is not configured"
                    )
                result = self._writer.solidify_conversation(
                    [message.model_dump(mode="json") for message in command.messages],
                    user_id=command.user_id,
                    owner_id=command.owner_id,
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
            self._journal.put(
                trace.model_copy(
                    update={
                        "revision": trace.revision + 1,
                        "knowledge_save_operation": updated,
                    }
                )
            )
            return updated

    def admit(self, action, *, all_actions, messages):
        if len(all_actions) != 1:
            return DecisionFeedback(
                action_id=action.action_id,
                reason_code="knowledge_save_requires_independent_confirmation",
                message="A knowledge save proposal must be the only action in its turn.",
                repairable_fields=("actions",),
                immutable_fields=("messages",),
                required_repair="Propose only the knowledge_save action so its exact payload can be confirmed.",
            ), None
        if self._writer is None:
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
            return self._source_feedback(action.action_id), None
        indexes = tuple(
            selection.source_message_index for selection in arguments.selections
        )
        if len(indexes) != len(set(indexes)):
            return self._source_feedback(action.action_id), None
        if any(
            index < 0 or index >= len(messages) or messages[index].role != "user"
            for index in indexes
        ):
            return self._source_feedback(action.action_id), None
        if any(
            not selection.text_span.strip()
            or selection.text_span.strip()
            not in messages[selection.source_message_index].content
            for selection in arguments.selections
        ):
            return self._source_feedback(action.action_id), None
        return None, arguments

    @staticmethod
    def _source_feedback(action_id):
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

    @staticmethod
    def prepare(
        action,
        *,
        arguments,
        run_ref,
        messages,
        principal,
        owner,
    ) -> ConversationKnowledgeSaveOperation:
        selected = tuple(
            ConversationMessage(role="user", content=selection.text_span.strip())
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
            "owner_id": owner.principal_id,
            "user_id": principal.user_id,
            "source_message_indexes": source_message_indexes,
            "messages": [message.model_dump(mode="json") for message in selected],
            "policy_revision": "conversation-knowledge-save-v1",
        }
        digest = sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return ConversationKnowledgeSaveOperation(
            command=ConversationKnowledgeSaveCommand(
                **canonical,
                command_digest=digest,
            ),
            status="awaiting_confirmation",
        )

    @staticmethod
    def turn_view(conversation_id, run_ref, operation):
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


__all__ = ["ConversationKnowledgeSaveUseCase"]

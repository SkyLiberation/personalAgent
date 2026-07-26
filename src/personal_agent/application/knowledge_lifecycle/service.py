from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal

from personal_agent.application.knowledge_lifecycle.models import (
    KnowledgeDeleteCommand,
    KnowledgeDeleteOperationView,
    KnowledgeRestoreCommand,
    KnowledgeRestoreOperationView,
)
from personal_agent.application.knowledge_lifecycle.store import KnowledgeLifecycleStore


class KnowledgeLifecycleService:
    POLICY_REVISION = "knowledge-delete-v1"
    RESTORE_POLICY_REVISION = "knowledge-restore-v1"

    def __init__(self, store: KnowledgeLifecycleStore) -> None:
        self._store = store

    def prepare_delete(
        self,
        *,
        workspace_id: str,
        user_id: str,
        target_note_id: str,
        reason: str,
        idempotency_key: str,
    ) -> KnowledgeDeleteOperationView:
        normalized_reason = reason.strip()
        normalized_key = idempotency_key.strip()
        if not normalized_key:
            raise ValueError("idempotency_key is required")
        command_id = "kdel_" + _digest({
            "user_id": user_id,
            "idempotency_key": normalized_key,
        })[:20]
        authorized = {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "target_note_id": target_note_id,
            "reason": normalized_reason,
            "policy_revision": self.POLICY_REVISION,
        }
        authorization_digest = _digest(authorized)
        execution_command_digest = _digest({
            "command_id": command_id,
            "authorization_digest": authorization_digest,
            "operation": "delete_knowledge_item",
        })
        return self._store.prepare_delete(KnowledgeDeleteCommand(
            command_id=command_id,
            idempotency_key=normalized_key,
            workspace_id=workspace_id,
            user_id=user_id,
            target_note_id=target_note_id,
            reason=normalized_reason,
            policy_revision=self.POLICY_REVISION,
            authorization_digest=authorization_digest,
            execution_command_digest=execution_command_digest,
        ))

    def decide_delete(
        self,
        *,
        command_id: str,
        user_id: str,
        decision: Literal["confirm", "reject"],
        authorization_digest: str,
        execution_command_digest: str,
        confirmation_ref: str,
    ) -> KnowledgeDeleteOperationView:
        if decision == "confirm" and not confirmation_ref.strip():
            raise ValueError("confirmation_ref is required when confirming")
        return self._store.decide_delete(
            command_id=command_id,
            user_id=user_id,
            decision=decision,
            authorization_digest=authorization_digest,
            execution_command_digest=execution_command_digest,
            confirmation_ref=confirmation_ref.strip(),
        )

    def get_delete(
        self,
        command_id: str,
        *,
        user_id: str,
    ) -> KnowledgeDeleteOperationView | None:
        return self._store.get_delete(command_id, user_id=user_id)

    def prepare_restore(
        self,
        *,
        workspace_id: str,
        user_id: str,
        delete_command_id: str,
        reason: str,
        idempotency_key: str,
    ) -> KnowledgeRestoreOperationView:
        normalized_reason = reason.strip()
        normalized_key = idempotency_key.strip()
        if not normalized_key:
            raise ValueError("idempotency_key is required")
        command_id = "krst_" + _digest({
            "user_id": user_id,
            "idempotency_key": normalized_key,
        })[:20]
        authorized = {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "delete_command_id": delete_command_id,
            "reason": normalized_reason,
            "policy_revision": self.RESTORE_POLICY_REVISION,
        }
        authorization_digest = _digest(authorized)
        execution_command_digest = _digest({
            "command_id": command_id,
            "authorization_digest": authorization_digest,
            "operation": "restore_knowledge_item",
        })
        return self._store.prepare_restore(KnowledgeRestoreCommand(
            command_id=command_id,
            idempotency_key=normalized_key,
            workspace_id=workspace_id,
            user_id=user_id,
            delete_command_id=delete_command_id,
            reason=normalized_reason,
            policy_revision=self.RESTORE_POLICY_REVISION,
            authorization_digest=authorization_digest,
            execution_command_digest=execution_command_digest,
        ))

    def decide_restore(
        self,
        *,
        command_id: str,
        user_id: str,
        decision: Literal["confirm", "reject"],
        authorization_digest: str,
        execution_command_digest: str,
        confirmation_ref: str,
    ) -> KnowledgeRestoreOperationView:
        if decision == "confirm" and not confirmation_ref.strip():
            raise ValueError("confirmation_ref is required when confirming")
        return self._store.decide_restore(
            command_id=command_id,
            user_id=user_id,
            decision=decision,
            authorization_digest=authorization_digest,
            execution_command_digest=execution_command_digest,
            confirmation_ref=confirmation_ref.strip(),
        )

    def get_restore(
        self,
        command_id: str,
        *,
        user_id: str,
    ) -> KnowledgeRestoreOperationView | None:
        return self._store.get_restore(command_id, user_id=user_id)


def _digest(payload: dict[str, str]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["KnowledgeLifecycleService"]

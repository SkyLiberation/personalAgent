from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.kernel.models import local_now


class KnowledgeDeleteCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    command_id: str
    idempotency_key: str
    workspace_id: str
    user_id: str
    target_note_id: str
    reason: str
    policy_revision: str = "knowledge-delete-v1"
    command_digest: str
    created_at: datetime = Field(default_factory=local_now)


class KnowledgeDeleteReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: str
    command_id: str
    command_digest: str
    confirmation_ref: str
    deleted_note_id: str
    affected_claim_ids: tuple[str, ...] = ()
    state_event_ids: tuple[str, ...] = ()
    previous_item_state: str
    previous_claim_states: dict[str, str] = Field(default_factory=dict)
    executed_at: datetime = Field(default_factory=local_now)


class KnowledgeDeleteOperationView(BaseModel):
    command: KnowledgeDeleteCommand
    status: Literal["awaiting_confirmation", "rejected", "executed"]
    receipt: KnowledgeDeleteReceipt | None = None


class KnowledgeRestoreCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    command_id: str
    idempotency_key: str
    workspace_id: str
    user_id: str
    delete_command_id: str
    reason: str
    policy_revision: str = "knowledge-restore-v1"
    command_digest: str
    created_at: datetime = Field(default_factory=local_now)


class KnowledgeRestoreReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: str
    command_id: str
    command_digest: str
    confirmation_ref: str
    restored_note_id: str
    affected_claim_ids: tuple[str, ...] = ()
    state_event_ids: tuple[str, ...] = ()
    restored_at: datetime = Field(default_factory=local_now)


class KnowledgeRestoreOperationView(BaseModel):
    command: KnowledgeRestoreCommand
    status: Literal["awaiting_confirmation", "rejected", "executed"]
    receipt: KnowledgeRestoreReceipt | None = None


__all__ = [
    "KnowledgeDeleteCommand",
    "KnowledgeDeleteOperationView",
    "KnowledgeDeleteReceipt",
    "KnowledgeRestoreCommand",
    "KnowledgeRestoreOperationView",
    "KnowledgeRestoreReceipt",
]

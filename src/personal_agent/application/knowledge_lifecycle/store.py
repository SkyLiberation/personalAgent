from __future__ import annotations

from typing import Literal, Protocol

from personal_agent.application.knowledge_lifecycle.models import (
    KnowledgeDeleteCommand,
    KnowledgeDeleteOperationView,
    KnowledgeRestoreCommand,
    KnowledgeRestoreOperationView,
)


class KnowledgeDeleteConflict(RuntimeError):
    pass


class KnowledgeDeleteNotFound(LookupError):
    pass


class KnowledgeLifecycleStore(Protocol):
    def prepare_delete(
        self,
        command: KnowledgeDeleteCommand,
    ) -> KnowledgeDeleteOperationView: ...

    def decide_delete(
        self,
        *,
        command_id: str,
        user_id: str,
        decision: Literal["confirm", "reject"],
        command_digest: str,
        confirmation_ref: str,
    ) -> KnowledgeDeleteOperationView: ...

    def get_delete(
        self,
        command_id: str,
        *,
        user_id: str,
    ) -> KnowledgeDeleteOperationView | None: ...

    def prepare_restore(
        self,
        command: KnowledgeRestoreCommand,
    ) -> KnowledgeRestoreOperationView: ...

    def decide_restore(
        self,
        *,
        command_id: str,
        user_id: str,
        decision: Literal["confirm", "reject"],
        command_digest: str,
        confirmation_ref: str,
    ) -> KnowledgeRestoreOperationView: ...

    def get_restore(
        self,
        command_id: str,
        *,
        user_id: str,
    ) -> KnowledgeRestoreOperationView | None: ...


__all__ = [
    "KnowledgeDeleteConflict",
    "KnowledgeDeleteNotFound",
    "KnowledgeLifecycleStore",
]

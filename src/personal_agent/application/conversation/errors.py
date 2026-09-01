"""Stable application errors exposed by Conversation use cases."""

from typing import Literal, TypeAlias

from personal_agent.capabilities.contracts.model import (
    ModelActionKind,
    ModelInvocationFailureCategory,
    StructuredOutputFailureCode,
)


ConversationUnavailableReason: TypeAlias = (
    ModelInvocationFailureCategory
    | StructuredOutputFailureCode
    | Literal[
        "model_not_configured",
        "final_action_required",
        "dependency_unavailable",
    ]
)
ConversationFailureStage = Literal[
    "application_configuration",
    "application_dependency",
    "provider_request",
    "provider_structured_decode",
    "provider_action_decode",
    "application_action_decode",
]


class ConversationUnavailable(RuntimeError):
    """Stable public failure plus typed, non-sensitive diagnostic facts."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: ConversationUnavailableReason = "dependency_unavailable",
        failure_stage: ConversationFailureStage = "application_dependency",
        operation: str | None = None,
        provider_host: str | None = None,
        provider_status_code: int | None = None,
        retryable: bool = False,
        action_name: str | None = None,
        action_kind: ModelActionKind | None = None,
        field_paths: tuple[str, ...] = (),
        error_types: tuple[str, ...] = (),
    ) -> None:
        if len(field_paths) != len(error_types):
            raise ValueError("conversation diagnostic fields must align")
        self.reason_code = reason_code
        self.failure_stage = failure_stage
        self.operation = operation
        self.provider_host = provider_host
        self.provider_status_code = provider_status_code
        self.retryable = retryable
        self.action_name = action_name
        self.action_kind = action_kind
        self.field_paths = field_paths
        self.error_types = error_types
        super().__init__(message)


class ConversationOperationNotFound(LookupError):
    pass


class ConversationOperationConflict(RuntimeError):
    pass


__all__ = [
    "ConversationOperationConflict",
    "ConversationOperationNotFound",
    "ConversationFailureStage",
    "ConversationUnavailable",
    "ConversationUnavailableReason",
]

"""Stable application errors exposed by Conversation use cases."""


class ConversationUnavailable(RuntimeError):
    pass


class ConversationOperationNotFound(LookupError):
    pass


class ConversationOperationConflict(RuntimeError):
    pass


__all__ = [
    "ConversationOperationConflict",
    "ConversationOperationNotFound",
    "ConversationUnavailable",
]

"""Deployment and persisted Session binding for Conversation Goal maintenance."""

from enum import StrEnum


class ConversationGoalMode(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"

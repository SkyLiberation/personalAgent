"""Admission gate for mutations that create or alter durable knowledge."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from personal_agent.runtime.contracts.task import TaskContract


class MutationAdmissionDecision(BaseModel):
    status: Literal["admitted", "denied", "requires_confirmation"]
    reason: str
    target_kind: str


_MEMORY_WRITE_TOOLS = frozenset({
    "capture_text", "update_note", "supersede_note",
    "mark_note_deprecated", "mark_notes_conflicted",
})


class MemoryAdmissionGate:
    """Require explicit task intent and confirmation before durable mutation."""

    def evaluate(
        self,
        task: TaskContract | None,
        *,
        tool_name: str | None,
    ) -> MutationAdmissionDecision:
        if tool_name not in _MEMORY_WRITE_TOOLS:
            return MutationAdmissionDecision(
                status="admitted",
                reason="tool does not mutate durable knowledge",
                target_kind="none",
            )
        if task is None or task.mutation_intent is None:
            return MutationAdmissionDecision(
                status="denied",
                reason="durable knowledge mutation requires an explicit TaskContract mutation intent",
                target_kind="knowledge",
            )
        if task.mutation_intent.requires_confirmation:
            return MutationAdmissionDecision(
                status="requires_confirmation",
                reason="user confirmation is required before durable knowledge mutation",
                target_kind="knowledge",
            )
        return MutationAdmissionDecision(
            status="admitted",
            reason="task mutation intent has been admitted",
            target_kind="knowledge",
        )


__all__ = ["MemoryAdmissionGate", "MutationAdmissionDecision"]

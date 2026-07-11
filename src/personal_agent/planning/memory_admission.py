"""Admission gate for mutations that create or alter durable knowledge."""

from __future__ import annotations

from personal_agent.kernel.contracts.agentic import MemoryAdmissionDecision, TaskSpec


_MEMORY_WRITE_TOOLS = frozenset({
    "capture_text", "delete_note", "update_note", "supersede_note",
    "mark_note_deprecated", "mark_notes_conflicted", "restore_note",
})


class MemoryAdmissionGate:
    """Require explicit task intent and confirmation before durable mutation."""

    def evaluate(self, task: TaskSpec | None, *, tool_name: str | None) -> MemoryAdmissionDecision:
        if tool_name not in _MEMORY_WRITE_TOOLS:
            return MemoryAdmissionDecision(
                status="admitted",
                reason="tool does not mutate durable knowledge",
                target_kind="none",
            )
        if task is None or task.mutation_intent is None:
            return MemoryAdmissionDecision(
                status="denied",
                reason="durable knowledge mutation requires an explicit TaskSpec mutation intent",
                target_kind="knowledge",
            )
        if task.mutation_intent.requires_confirmation:
            return MemoryAdmissionDecision(
                status="requires_confirmation",
                reason="user confirmation is required before durable knowledge mutation",
                target_kind="knowledge",
            )
        return MemoryAdmissionDecision(
            status="admitted",
            reason="task mutation intent has been admitted",
            target_kind="knowledge",
        )


__all__ = ["MemoryAdmissionGate"]

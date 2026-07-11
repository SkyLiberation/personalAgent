"""Append-only execution events and deterministic ledger projection."""

from __future__ import annotations

from personal_agent.kernel.contracts.agentic import (
    AttemptRef,
    ExecutionEvent,
    ExecutionLedger,
    ExecutionLedgerItem,
    PlanMacroRef,
)
from personal_agent.kernel.contracts.executive import LedgerPatch
from personal_agent.kernel.contracts.executive import VerificationReport


class LedgerTransitionError(ValueError):
    pass


_ALLOWED_TRANSITIONS = {
    "pending": {"active", "abandoned"},
    "active": {"blocked", "awaiting_input", "candidate_complete", "degraded", "abandoned"},
    "blocked": {"active", "degraded", "abandoned"},
    "awaiting_input": {"active", "abandoned"},
    "candidate_complete": {"verified", "active", "degraded"},
    "verified": set(),
    "degraded": set(),
    "abandoned": set(),
}


class LedgerPatchValidator:
    def validate(self, ledger: ExecutionLedger, patch: LedgerPatch) -> None:
        item_by_id = {item.goal_id: item for item in ledger.items}
        for operation in patch.operations:
            if operation.op == "add_goal":
                if not operation.goal_id or operation.goal_id in item_by_id:
                    raise LedgerTransitionError("add_goal requires a new goal_id")
                continue
            if operation.op == "apply_macro":
                if not operation.values.get("macro_id"):
                    raise LedgerTransitionError("apply_macro requires macro_id")
                continue
            item = item_by_id.get(operation.goal_id)
            if item is None:
                raise LedgerTransitionError(f"unknown goal_id: {operation.goal_id}")
            if operation.op == "abandon_goal":
                target = "abandoned"
            else:
                target = str(operation.values.get("status", item.status))
            if target != item.status and target not in _ALLOWED_TRANSITIONS[item.status]:
                raise LedgerTransitionError(f"illegal goal transition {item.status}->{target}")
            if item.status in {"verified", "degraded", "abandoned"} and operation.values:
                raise LedgerTransitionError("terminal goal facts cannot be rewritten")


class ExecutionLedgerProjector:
    def project(self, ledger: ExecutionLedger, events: tuple[ExecutionEvent, ...]) -> ExecutionLedger:
        current = ledger
        expected = current.last_event_sequence + 1
        for event in events:
            if event.task_id != current.task_id:
                raise LedgerTransitionError("event task_id does not match ledger")
            if event.sequence != expected:
                raise LedgerTransitionError(f"expected event sequence {expected}, got {event.sequence}")
            current = self._apply(current, event)
            expected += 1
        return current

    def _apply(self, ledger: ExecutionLedger, event: ExecutionEvent) -> ExecutionLedger:
        items = list(ledger.items)
        index = next((i for i, item in enumerate(items) if item.goal_id == event.goal_id), None)
        status_by_event = {
            "goal_activated": "active",
            "goal_blocked": "blocked",
            "goal_candidate_complete": "candidate_complete",
            "goal_verified": "verified",
            "goal_degraded": "degraded",
            "goal_abandoned": "abandoned",
        }
        if event.event_type == "goal_added":
            items.append(ExecutionLedgerItem.model_validate(event.payload["goal"]))
        elif event.event_type in status_by_event:
            if index is None:
                raise LedgerTransitionError(f"event references unknown goal {event.goal_id}")
            item = items[index]
            target = status_by_event[event.event_type]
            if target != item.status and target not in _ALLOWED_TRANSITIONS[item.status]:
                raise LedgerTransitionError(f"illegal goal transition {item.status}->{target}")
            update = {"status": target}
            if "evidence_gaps" in event.payload:
                update["evidence_gaps"] = tuple(event.payload["evidence_gaps"])
            if "verification" in event.payload:
                update["verification"] = VerificationReport.model_validate(event.payload["verification"])
            items[index] = item.model_copy(update=update)
        elif event.event_type == "attempt_recorded":
            if index is None:
                raise LedgerTransitionError(f"event references unknown goal {event.goal_id}")
            item = items[index]
            attempt = AttemptRef.model_validate(event.payload["attempt"])
            items[index] = item.model_copy(update={"attempts": (*item.attempts, attempt)})
        elif event.event_type == "coverage_recorded":
            if index is None:
                raise LedgerTransitionError(f"event references unknown goal {event.goal_id}")
            item = items[index]
            items[index] = item.model_copy(update={
                "coverage": tuple(event.payload.get("coverage", ())),
                "evidence_gaps": tuple(event.payload.get("evidence_gaps", item.evidence_gaps)),
            })
        elif event.event_type == "skill_activated":
            skill_id = str(event.payload["skill_id"])
            if skill_id not in ledger.active_skill_ids:
                ledger = ledger.model_copy(update={
                    "active_skill_ids": (*ledger.active_skill_ids, skill_id),
                })
        elif event.event_type == "macro_applied":
            ref = PlanMacroRef.model_validate(event.payload["macro"])
            if all(existing.macro_id != ref.macro_id for existing in ledger.applied_macros):
                ledger = ledger.model_copy(update={"applied_macros": (*ledger.applied_macros, ref)})

        active = tuple(item.goal_id for item in items if item.status in {
            "pending", "active", "blocked", "awaiting_input", "candidate_complete",
        })
        return ledger.model_copy(update={
            "items": tuple(items),
            "active_goal_ids": active,
            "revision": ledger.revision + 1,
            "last_event_sequence": event.sequence,
        })


def next_execution_event(
    ledger: ExecutionLedger,
    event_type: str,
    *,
    goal_id: str | None = None,
    payload: dict | None = None,
) -> ExecutionEvent:
    return ExecutionEvent(
        sequence=ledger.last_event_sequence + 1,
        task_id=ledger.task_id,
        event_type=event_type,
        goal_id=goal_id,
        payload=payload or {},
    )


__all__ = [
    "ExecutionLedgerProjector",
    "LedgerPatchValidator",
    "LedgerTransitionError",
    "next_execution_event",
]

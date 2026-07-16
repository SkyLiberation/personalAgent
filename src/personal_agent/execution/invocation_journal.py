"""CAS-style dispatch commit and recovery over InvocationJournalProjection."""

from __future__ import annotations

from datetime import UTC, datetime

from personal_agent.execution.contracts.journal import (
    DispatchCommit,
    InvocationJournalEntry,
    InvocationJournalProjection,
    InvocationOutboxEntry,
)


class InvocationJournalConflict(RuntimeError):
    pass


class InvocationJournal:
    def reserve(
        self,
        projection: InvocationJournalProjection,
        *,
        expected_revision: int,
        invocation_id: str,
        grant_ref: str,
        idempotency_key: str,
        provider_ref: str,
        payload_ref: str,
    ) -> tuple[InvocationJournalProjection, DispatchCommit]:
        if projection.revision != expected_revision:
            raise InvocationJournalConflict("invocation journal revision changed")
        existing = projection.entries.get(invocation_id)
        if existing is not None:
            if existing.grant_ref != grant_ref or existing.idempotency_key != idempotency_key:
                raise InvocationJournalConflict("invocation identity was rebound")
            return projection, DispatchCommit(
                invocation_id=invocation_id,
                expected_journal_revision=expected_revision,
                journal_revision=projection.revision,
                outbox_ref=invocation_id,
                dispatch_required=existing.status == "reserved",
                recovered_receipt_ref=existing.remote_receipt_ref,
            )
        entries = dict(projection.entries)
        outbox = dict(projection.outbox)
        entries[invocation_id] = InvocationJournalEntry(
            invocation_id=invocation_id,
            grant_ref=grant_ref,
            idempotency_key=idempotency_key,
            provider_ref=provider_ref,
            updated_at=datetime.now(UTC),
        )
        outbox[invocation_id] = InvocationOutboxEntry(
            invocation_id=invocation_id,
            grant_ref=grant_ref,
            provider_ref=provider_ref,
            idempotency_key=idempotency_key,
            payload_ref=payload_ref,
            prepared_at=datetime.now(UTC),
        )
        updated = projection.model_copy(update={
            "revision": projection.revision + 1,
            "entries": entries,
            "outbox": outbox,
        })
        return updated, DispatchCommit(
            invocation_id=invocation_id,
            expected_journal_revision=expected_revision,
            journal_revision=updated.revision,
            outbox_ref=invocation_id,
            dispatch_required=True,
        )

    def transition(
        self,
        projection: InvocationJournalProjection,
        invocation_id: str,
        status: str,
        *,
        remote_receipt_ref: str | None = None,
        observation_ref: str | None = None,
    ) -> InvocationJournalProjection:
        entry = projection.entries.get(invocation_id)
        if entry is None:
            raise InvocationJournalConflict("unknown invocation")
        allowed = {
            "reserved": {"dispatched", "cancelled"},
            "dispatched": {"acknowledged", "observed", "outcome_unknown"},
            "acknowledged": {"observed", "outcome_unknown"},
            "outcome_unknown": {"reconciled"},
            "observed": set(),
            "reconciled": set(),
            "cancelled": set(),
        }
        if status not in allowed[entry.status]:
            raise InvocationJournalConflict(f"illegal journal transition {entry.status}->{status}")
        entries = dict(projection.entries)
        outbox = dict(projection.outbox)
        entries[invocation_id] = entry.model_copy(update={
            "status": status,
            "remote_receipt_ref": remote_receipt_ref or entry.remote_receipt_ref,
            "observation_ref": observation_ref or entry.observation_ref,
            "reconciliation_required": status == "outcome_unknown",
            "updated_at": datetime.now(UTC),
        })
        if invocation_id in outbox and status in {"dispatched", "cancelled"}:
            outbox[invocation_id] = outbox[invocation_id].model_copy(update={"status": status})
        return projection.model_copy(update={
            "revision": projection.revision + 1,
            "entries": entries,
            "outbox": outbox,
        })


__all__ = ["InvocationJournal", "InvocationJournalConflict"]

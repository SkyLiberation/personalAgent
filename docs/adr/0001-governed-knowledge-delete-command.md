# ADR 0001: Governed Knowledge Delete Command

- Status: Accepted
- Date: 2026-07-24
- Removal review: 2027-07-24

## Context

Knowledge deletion and restoration previously entered through the generic Task/GoalGraph/LangGraph chain or directly mutated `KnowledgeItem.state` in the notes HTTP adapter. The former created redundant ordinary-request facts; the latter had no durable confirmation binding, immutable payload, claim restoration, or exactly-once receipt.

## Decision

`KnowledgeLifecycleService` is the sole application write entry for knowledge deletion. It creates an immutable `KnowledgeDeleteCommand`, records append-only `KnowledgeDeleteEvent` facts, and atomically writes `KnowledgeDeleteReceipt` with the `KnowledgeItem` and Claim state changes.

Authorization and execution digests freeze workspace, user, target, reason, policy revision, and operation. Confirmation must present both digests and an external `confirmation_ref`. Replaying an executed command returns the existing receipt. A rejected command cannot later execute.

Restore is a separate immutable `KnowledgeRestoreCommand` linked to one executed delete command. Its transaction reads the delete receipt as the sole source of the previous item and claim states, restores all affected canonical rows, and records its own events and receipt. The restore confirmation cannot reuse the delete confirmation.

The generic `delete_note` and `restore_note` tools are not exposed to the ordinary Conversation loop. The old direct `DELETE /api/notes/{note_id}` path and both snapshot-based restore paths are removed.

## Ownership

- Delete/restore command, event, and receipt facts: `KnowledgeLifecycleService` and `PostgresKnowledgeLifecycleStore`.
- Knowledge item and claim lifecycle facts: Workspace aggregate tables.
- Authorization digest: deterministic lifecycle policy.
- Confirmation fact: user input at the knowledge-delete decision endpoint.
- Execution fact: `KnowledgeDeleteReceipt` only.

## Risks

- The transaction updates several workspace projections; a schema mismatch must fail closed and roll back.
- Existing rows deleted through the removed path have no new receipt and cannot be adopted silently.
- A restore fails closed if the deleted item or any claim recorded by the delete receipt changed before confirmation.

## Verification

- API integration covers prepare without mutation, scope denial, digest mismatch, rejection, confirmed execution, and exactly-once replay.
- Release E04 restarts the production process after prepare and confirms the persisted command.
- Release E10 restarts between delete and restore, verifies item and claim restoration, replays the restore without duplicate events, and asserts the snapshot endpoint is unreachable.

## Exit Conditions

Remove these tables only after a superseding knowledge lifecycle aggregate has migrated every command, event, and receipt and equivalent E04/E10 E2E passes. The review date is not permission to retain an unused compatibility path.

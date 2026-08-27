# ADR 0004: Durable Agent Submission and Artifact Reference

- Status: Accepted, live A2A evidence pending
- Date: 2026-07-27
- Removal review: 2027-07-27

> 2026-08-26：AgentGateway 的 durable submission 与 ArtifactRef 结论仍有效；本文引用 Investigation Project 的恢复消费者只作历史记录，该产品循环已按 [ADR 0015](0015-withdraw-investigation-project.md) 删除。

## Context and Baseline

The old AgentGateway submitted a provider task before keeping the child run in process memory. A crash in
that window made retry ambiguous and could duplicate external work. Child records also carried provider
Artifact bodies, creating a second content owner beside `ArtifactService`.

## Decision

`PostgresAgentRunStore` is the production owner of child definition, stable submission binding and current
projection. Both synchronous invoke and asynchronous submit reserve
`submission_key + immutable definition_digest` before calling an adapter, then commit the provider binding
or result to the same row.

After an uncertain asynchronous submit, retry may only call the provider's
`lookup_submission(submission_key)`. If lookup is unsupported or returns no binding, Gateway raises typed
`AgentSubmissionOutcomeUnknown`; it never blindly resubmits. An uncertain synchronous invocation also
fails closed because retry could duplicate work.

Provider output is written through `ArtifactService.write_generated`. `AgentArtifact` and Project events
store only owner-scoped `ResourceRef`; consumers re-authorize reads through ArtifactService.

## Ownership

- Submission key, definition, provider task binding and child projection: AgentGateway/store.
- Authorization and execution digests: immutable child definition linked to the DelegationGrant.
- Artifact bytes and revision: ArtifactService.
- Project relation to a child: Project stores only child run/submission refs.

## Migration and Net Complexity

Added one PostgreSQL store and reservation/reconcile protocol. Removed the in-memory production store,
request-only child lifecycle and inline Artifact body. `InMemoryAgentRunStore` remains test/eval-only and
implements the same contract.

## Verification

Fault injection loses the first submit response, reconstructs Gateway/store, reconciles by stable key and
asserts provider submit count equals one. A synchronous idempotency test asserts a repeated committed key
does not call the adapter again. LT02 and LT10 exercise Project recovery linkage. Live A2A crash evidence
is still required for release.

## Alternatives and Exit

Provider-first submit plus later persistence and unconditional retry were rejected due to duplicate
side effects. An outbox cannot by itself solve a remote provider that lacks idempotency or lookup. Remove
this mechanism only if every provider offers a stronger atomic/idempotent contract and equivalent crash
E2E proves no duplicate submission.

# ADR 0002: Investigation Project Aggregate and Journal

- Status: Superseded and removed on 2026-08-26
- Date: 2026-07-27

> Historical record only. Baseline-first review found no evidence that an independent Project lifecycle was required, while formal samples delivered `0/20`; the implementation was removed. Current decision: [ADR 0015](0015-withdraw-investigation-project.md).

## Context and Baseline

Conversation ReAct can recover committed interaction inputs, and existing durable workflows can recover
fixed topologies. Neither owns dynamic SubGoal dependencies, requirement coverage, steering revisions or
a deliverable contract across process and approval boundaries.

The adoption-time design said LT09 would freeze Conversation as the simplest product baseline and LT12
would compare a fixed durable workflow with observation-driven revision. A later evidence audit found that
LT09 returned a constructed `conversation_coverage` value without executing the Conversation production
entry, while LT12 was mechanism evidence created with the design. They therefore do not qualify the
product demand for InvestigationProject. This ADR records the ownership and recovery boundaries of the
implemented public path; it must not be cited as proof that real users required the aggregate.

## Decision

Introduce one business-specific `InvestigationProject` aggregate. Its immutable definition and append-only
events are stored by `PostgresInvestigationProjectStore`; the aggregate projection is rebuilt from those
facts. `InvestigationProjectService` is the only Project write entry. Accepted Plan versions are production
inputs to ready-set calculation, dispatch, join, progress and coverage.

Creation persists the definition before enqueue and returns `202`. The investigation worker scans
non-terminal Projects after restart and re-enqueues them with stable keys. A paused Project is not
recovered automatically. User resume is legal only when the canonical pause reason is `user_paused`;
budget, capability, approval and repair pauses require their typed condition to change.

The implementation remains Project-specific. A generic DurableTask framework is prohibited until a second
business aggregate demonstrates the same invariants through its own E2E.

`cancelling` and `completing` are recoverable states, not transient method-local markers. Restart continues
child cancellation or final verification from journal facts. A committed final Artifact is read through
ArtifactService on recovery, so final synthesis is not repeated.

## Ownership

- Definition, Plan, SubGoal, waiting reason, budget and completion lifecycle: Project aggregate.
- Commands that change the aggregate: `InvestigationProjectService`.
- Persistence and optimistic sequence check: PostgreSQL Project store.
- Queue lease and retry facts: existing worker queue store.
- Open semantic proposals: structured-model ports; never the aggregate or worker.

## Net Complexity and Removed Path

Added one aggregate, one journal/store and one worker handler. The initial implementation removed the old
Conversation `WorkingPlanSnapshot`; a later, independently admitted change added a Conversation-owned
typed working plan without sharing Project facts or durable dispatch. No converter, feature flag or second
Project write path remains.

## Verification

Current diagnostic coverage excludes the invalid LT09 comparison. The remaining runtime-conformance and
lifecycle tests exercise production domain/application/store/queue code with scripted external ports and
assert user pause/resume, restart scanning, system-pause non-bypass, and crash recovery from `cancelling`
and `completing` without duplicate provider cancellation or final synthesis. These are regression and
mechanism claims, not product-demand evidence. Live model/provider release evidence remains mandatory for
the corresponding provider profile.

## Alternatives and Exit

A generic DAG engine remains rejected because it adds abstraction without a second business consumer.
No additional Project lifecycle, approval, planning or persistence mechanism may be added until a
traceable user/contract source and same-input failure baseline establish the missing result. The existing
HTTP/Conversation path is already a public behavior with persisted canonical facts, so removing or
collapsing it is also a product change: first identify real consumers and migration obligations, execute a
behavior/migration baseline, and preserve canonical facts before deletion. Architecture references alone
authorize neither expansion nor destructive removal.

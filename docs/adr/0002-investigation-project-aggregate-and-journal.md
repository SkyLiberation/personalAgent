# ADR 0002: Investigation Project Aggregate and Journal

- Status: Accepted, release evidence pending
- Date: 2026-07-27
- Removal review: 2027-07-27

## Context and Baseline

Conversation ReAct can recover committed interaction inputs, and existing durable workflows can recover
fixed topologies. Neither owns dynamic SubGoal dependencies, requirement coverage, steering revisions or
a deliverable contract across process and approval boundaries. LT09 freezes Conversation as the simplest
baseline; LT12 separately compares a fixed durable workflow with observation-driven revision.

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

Added one aggregate, one journal/store and one worker handler. Removed the Conversation
`WorkingPlanSnapshot` contract, recovery admission and trace projection. No converter, feature flag or
second Project write path remains.

## Verification

Diagnostic LT01–LT13 exercise production domain/application/store/queue code with scripted external ports.
Lifecycle integration additionally asserts user pause/resume, restart scanning and system-pause
non-bypass, plus crash recovery from `cancelling` and `completing` without duplicate provider cancellation
or final synthesis. Live model/provider release evidence remains mandatory.

## Alternatives and Exit

A longer Conversation loop was rejected because it has no durable deliverable owner. A generic DAG engine
was rejected because it adds abstraction without a second business consumer. Remove the Project main path
if LT09 does not prove recovery benefit or LT12 does not prove dynamic-plan benefit; migrate canonical
facts first and retain the simpler baseline.

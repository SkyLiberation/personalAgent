# ADR 0005: Investigation Command, Evidence and Completion Semantics

- Status: Accepted, semantic release evidence pending
- Date: 2026-07-27
- Removal review: 2027-07-27

## Context and Baseline

Tool success, child `completed`, an Artifact row or a model's statement cannot prove that an investigation
requirement is satisfied. External delegation additionally crosses approval, data-egress and restart
boundaries. Treating any one of those facts as completion would allow premature reports or unapproved
side effects.

## Decision

Separate the main path into:

1. immutable execution proposal and capability/policy admission;
2. governed external delegation Command, when approval or durable side effects require it;
3. execution fact/receipt;
4. Evidence Admission into the current Project revision;
5. semantic SubGoal verification;
6. deterministic Completion Gate over active requirement coverage;
7. final semantic report verification and generated Artifact commit.

Approval binds `AuthorizationDigest`; Grant, Command and receipt bind the same
`ExecutionCommandDigest`. Cancellation reconciles linked children and quarantines late ArtifactRefs.
Budget is reserved by category before model/provider calls and is charged or released through Project
events. A globally blocked required set pauses with typed waiting reasons and cannot be released by the
generic user resume endpoint.

## Ownership

- Proposal meaning and semantic assessment: model ports.
- Capability, scope, policy and approval admission: deterministic control plane.
- External execution fact: Tool/Agent Gateway.
- Evidence membership and Project outcomes: Project aggregate.
- Required coverage and evidence completeness: Completion Gate.
- Artifact content: ArtifactService.

## Net Complexity and Removed Path

Added one concrete external-delegation Command and Project-specific admission/completion records. Removed
all temporary branches where Tool/Agent success directly completed a Project. No generic Saga, Event Bus
or second ToolGateway was introduced.

## Verification

LT05 asserts no provider call before digest-bound approval and exactly one afterward. LT06 asserts
over-budget work is not dispatched and cannot complete. LT07 asserts late results remain quarantined.
LT01/LT04 assert join occurs only after verified outcomes and final coverage is complete. These are
diagnostic external-boundary tests; live verifier/provider E2E remains a release gate.

## Alternatives and Exit

Using receipts as completion or letting a Verifier override execution facts was rejected because each has
a different decision owner. Remove or simplify this chain only when a narrower business workflow can
prove identical authorization, recovery, evidence and completion outcomes through the same counterfactual
E2E.

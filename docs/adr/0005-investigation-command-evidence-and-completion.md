# ADR 0005: Investigation Command, Evidence and Completion Semantics

- Status: Superseded and removed on 2026-08-26
- Date: 2026-07-27

> Historical record only. Execution、Verification 与 Completion 分离的通用原则仍保留在 Conversation；本文的 Investigation Command、repair 和 Project Completion 已按 [ADR 0015](0015-withdraw-investigation-project.md) 删除。

## Context and Baseline

Tool success, child `completed`, an Artifact row or a model's statement cannot prove that an investigation
requirement is satisfied. External delegation additionally crosses approval, data-egress and restart
boundaries. Treating any one of those facts as completion would allow premature reports or unapproved
side effects.

B03 live baseline `20260728T123013.176272Z-42316-76b47a9c` further proved that an executed but
unsatisfied SubGoal could retain a verification wait while an accepted revision produced no runnable
repair work. A later IP01 run `20260728T125249.466459Z-45552-410f6188` proved equivalent admission
feedback was incorrectly keyed by event sequence and could consume model calls indefinitely.

## Candidate Decision

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

An executed SubGoal that fails semantic verification remains immutable. The current candidate lets a revision add independently
runnable repair work and remap required coverage away from the frozen unsatisfied execution. The old
verification wait is cleared only after that repair Plan is accepted. Plan rejection persists typed
`DecisionFeedback` in the next `ReplanRequest`; feedback equivalence excludes event sequence and is bounded
by `same_feedback_revision_limit`. Reaching the limit pauses rather than replaying execution or continuing
to call the model.

## Ownership

- Proposal meaning and semantic assessment: model ports.
- Capability, scope, policy and approval admission: deterministic control plane.
- External execution fact: Tool/Agent Gateway.
- Evidence membership and Project outcomes: Project aggregate.
- Required coverage and evidence completeness: Completion Gate.
- Artifact content: ArtifactService.

## Complexity Justification

The user-visible requirement is a verified report even when the first external evidence is insufficient;
the counterfactual is a false completion, repeated external execution, or an unbounded model loop. B03 proves
the first execution can leave a real semantic gap, but it does not prove this candidate repair shape improves
the result. Existing lifecycle tests inject semantic decisions and therefore provide conformance evidence only.

The target IP01 uses the same natural HTTP goal and now additionally requires an accepted revision, new repair
execution, no repeated `(logical_subgoal_id, subgoal_version)`, cleared waits and a readable verified report.
Until that executable target passes, no additional repair model, patch DTO, state, table or workflow is admitted.

## Net Complexity and Removed Path

Added one concrete external-delegation Command and Project-specific admission/completion records. Repair
uses the existing Plan, waiting reason and ReplanRequest facts; no Attempt, retry Event, second digest or
repair projection was added. Removed all temporary branches where Tool/Agent success directly completed a
Project. No generic Saga, Event Bus or second ToolGateway was introduced.

## Verification

LT05 asserts no provider call before digest-bound approval and exactly one afterward. LT06 asserts
over-budget work is not dispatched and cannot complete. LT07 asserts late results remain quarantined.
LT01/LT04 assert join occurs only after verified outcomes and final coverage is complete. These are
diagnostic external-boundary tests; live verifier/provider E2E remains a release gate.
Focused lifecycle conformance proves a frozen failed execution is dispatched once, an
accepted independent repair is dispatched once, required coverage can complete, and repeated equivalent
feedback pauses after the configured retry count. The bounded IP01 archive
`20260728T130808.632067Z-17988-0d9bfe10` confirms the infinite loop is gone while final live report delivery
remains unproven. The later `20260728T143217.175037Z-28784-bb0ed0e8` archive removes Provider/parse failure
as the cause but still ends `paused/verification_repair`; it is failing baseline evidence, not acceptance evidence.
The rerun `20260728T150928.484946Z-48884-5c941a61` is excluded because Tavily returned HTTP 432 before
verification; the E2E now classifies that quota response as an environment failure.
After the explicit Firecrawl switch and removal of the inactive Tavily credential, archive
`20260728T154127.518791Z-8584-3899be03` records three successful production searches with
`source=firecrawl`, no Tavily call and no environment failure. Plan v2 adds and dispatches one repair SubGoal
without replaying frozen execution. A later revision violates SubGoal version/supersession admission and no
report is delivered, so local repair progress is evidenced while end-to-end acceptance remains unproven.
The 2026-07-29 sequence then proved and removed several narrower defects: the governed Web Search timeout
did not cover search plus two captures; capability-missing rejection constructed typed feedback incorrectly;
the Execution Proposal schema did not constrain capability identity to the current deterministic match; and
the Replanner projection recognized a legacy `web_search_results` shape but not the canonical Tool artifact
`data.results`. Archive `20260729T075635.355657Z-17460-0a4c21f8` reaches four bounded revisions without
replaying an exact operation and exposes the official A2A Releases URL, but it also encounters Firecrawl
429/402 and does not deliver a report. The subsequent rerun is externally blocked: archive
`20260729T080725.690825Z-11020-b4ee8959` records Firecrawl `/v2/search` HTTP 402 and is correctly classified
as an environment failure. B03 therefore remains the baseline and IP01 remains an open release gate.
Firecrawl Web Search was then removed and the single production search binding migrated to SerpAPI, while
URL reading remained explicitly bound to the builtin reader. Live SerpAPI smoke and IP01 runs now reach
GitHub release evidence without a Provider environment failure. Archives
`20260729T084450.226963Z-52148-7d7045a6` and
`20260729T085601.806550Z-18988-2e0c1eba` verify MCP `2025-03-26` and `2025-06-18` release facts, but still
pause before report delivery: repair SubGoals do not retain a canonical link to the frozen gap whose
evidence they may consume, so an A2A repair can select an MCP locator and exhaust bounded revisions.
This is target-failure evidence, not a reason to add a Provider fallback or raise the revision budget.

ADR 0008 records the admitted minimal repair: immutable frozen-gap lineage, lineage-scoped evidence,
same-Plan local Execution Proposal retry, separate evidence-repair budget, and deterministic URL candidate
binding. The same IP01 target then passed in archive
`20260729T101501.732689Z-53628-6c5f02f2`: `completed/completion_gate_passed`, 3/3 semantically satisfied
outcomes, five admitted evidence records, a user-readable report, and no environment failure. This closes
the repair acceptance condition in this ADR; it does not close the broader live capability matrix.

## Alternatives and Exit

Using receipts as completion or letting a Verifier override execution facts was rejected because each has
a different decision owner. Remove or simplify this chain only when a narrower business workflow can
prove identical authorization, recovery, evidence and completion outcomes through the same counterfactual
E2E.

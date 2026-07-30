# ADR 0008: Investigation Repair Lineage and Local Proposal Retry

- Status: Accepted
- Date: 2026-07-29
- Review date: 2027-01-29

## Goal / Current Incorrect Behavior / Expected User-visible Result

The IP01 user asks the production HTTP/worker path to compare current MCP and A2A changes and deliver one
evidence-backed report. The previous implementation could inject every Project evidence candidate into any
repair SubGoal. A failed source choice was also converted into a global Plan revision. The observable result
was cross-topic source selection, repeated exact operations, exhausted Plan revisions, and no report.

The expected result is a completed report in which each repaired gap consumes only its own evidence lineage,
an invalid local execution proposal is repaired without replacing the accepted Plan, exact failed operations
are not replayed, and Completion remains gated by semantic verification.

Out of scope: a generic retry framework, hostname-based source policy, a new evidence store, Provider
fallback, a general-purpose Planner, or raising every semantic Plan revision limit.

## Simplest Baseline E2E / Executed Result / Root Cause

The release E2E command is:

```powershell
uv run pytest evals/e2e_quality/test_product_capability_outcomes.py::test_product_ip01_live_investigation_report --e2e-scope=release -q -s
```

The same natural user goal repeatedly failed through the formal HTTP/worker path. The most relevant archived
traces are:

- `20260729T084450.226963Z-52148-7d7045a6`: SerpAPI and the Verifier establish official MCP release facts,
  but no final report is delivered.
- `20260729T085601.806550Z-18988-2e0c1eba`: an A2A repair consumes MCP candidates and exhausts bounded
  revisions because the accepted repair has no canonical frozen-gap lineage.
- `20260729T095037.157604Z-42072-7b20540f` and
  `20260729T095841.038750Z-21136-d511733e`: repair-of-repair loses earlier same-topic candidates and repeats
  an exact failed capture/search operation.
- `20260729T100201.989353Z-22360-a991a957`: evidence repair consumes the global semantic Plan budget.
- `20260729T100908.589427Z-15840-6b5f3475`: the model chooses a semantically useful observed URL variant,
  but requiring it to reproduce an exact locator makes structured proposal parsing fail as
  `provider_unavailable`.

These are product-behavior failures, not SerpAPI failures. They prove four coupled root causes: missing
accepted repair lineage, Project-wide rather than lineage-scoped evidence materialization, local proposal
rejection incorrectly escalating to global Replan, and one shared budget for different decision scopes.

## Decision and Fact Ownership

1. `SubGoalDefinitionVersion.repairs_frozen_subgoals` is the canonical immutable fact connecting a repair to
   the exact frozen gap. It is proposed by the Replanner and written only with an accepted Plan.
2. Plan Admission deterministically validates one repair owner per frozen gap, stable repair identity,
   frozen target version, and requirement remapping through that lineage. It never invents or repairs the
   lineage.
3. Execution materialization may read admitted evidence only from the current SubGoal's dependency and
   recursive repair-lineage closure. Project-wide evidence injection is removed.
4. Source/query meaning remains a semantic model decision. For an observed URL candidate, the model selects
   an opaque candidate ID and deterministic code binds it back to the canonical URL. Code excludes an exact
   failed operation but does not decide which different source is semantically better.
5. `ExecutionProposalRejectedData` is the append-only execution fact for a rejected local proposal.
   `InvestigationProjectService` is its only write path. The next Execution Proposer call consumes that typed
   feedback against the same accepted Plan/SubGoal; repeated equivalent feedback pauses locally.
6. Semantic Plan revision count and evidence-repair revision count are separate aggregate projections.
   Verification gaps consume `max_evidence_repair_revisions`; steering, assumptions, coverage and capability
   changes consume `max_plan_revisions`.
7. The Verifier still owns semantic sufficiency and the Completion Gate still owns required-result evidence
   completeness. A successful Tool receipt cannot complete the Project.

## Canonical Models and Migration

The only new durable facts are `SubGoalVersionRef` on the accepted SubGoal definition and
`ExecutionProposalRejectedData` in the existing Project journal. No table, second evidence model, mutable
mirror, or alternate write entry was added.

Old accepted Plan events deserialize with an empty repair lineage. Their previous definition digest remains
valid because the digest binds lineage only when it is non-empty. New repair definitions bind the canonical
lineage in the digest. There is no dual write or runtime fallback. The old paths—Project-wide evidence
materialization and Execution Admission rejection to global `ReplanRequestedData`—are removed.

## Target E2E and Counterfactuals

The target E2E passed on 2026-07-29:

- archive: `data/e2e_traces/20260729T101501.732689Z-53628-6c5f02f2`;
- result: `1 passed in 86.42s`;
- final state/reason: `completed / completion_gate_passed`;
- accepted Plan version: 3;
- outcomes: 3 of 3 semantically satisfied;
- admitted evidence: 5;
- user-readable report: present, with no report or environment error.

The E2E and focused conformance tests assert the relevant counterfactuals: MCP evidence is not offered to an
A2A repair; recursive same-topic repair evidence remains visible; an exact failed URL/query is not replayed;
ordinary Execution Admission rejection does not replace Plan v1; equivalent local feedback pauses after the
configured bound; and verification repair can complete even when the semantic Plan revision budget is zero.

## Complexity Added, Removed and Rejected Alternatives

Added: one small version reference value object, one existing-journal event, two derived counters, scoped
lineage traversal, and candidate-ID binding. Removed: global evidence injection, ordinary
Execution-Admission-to-global-Replan, and model copying of canonical URLs.

No new Provider, repository, registry, factory, workflow, table, digest family, or compatibility layer was
introduced. Net complexity is constrained to the already-proven repair path and has production consumers in
Plan Admission, Execution Proposal materialization, retry, and budget enforcement.

Rejected alternatives:

- prompt-only source isolation, because it cannot mechanically prevent cross-topic candidate exposure;
- hostname/product-name rules, because officiality and source relevance are open-world semantic decisions;
- increasing `max_plan_revisions`, because it hides the ownership error and also expands unrelated semantic
  replanning;
- a second repair/evidence aggregate, because the accepted Plan and existing admitted evidence already own
  the required facts;
- Provider fallback, because all decisive failing traces had working SerpAPI execution.

## Verification and Remaining Risk

Executed after the target E2E:

```powershell
$env:LANGSMITH_TRACING='false'
$env:PERSONAL_AGENT_GITHUB_MCP_ENABLED='false'
$env:PERSONAL_AGENT_NOTION_MCP_ENABLED='false'
uv run pytest -q tests
```

Result: `705 passed, 4 warnings in 116.10s`.

An earlier unisolated full-suite run produced `704 passed` plus one setup error because the developer
environment had live Notion MCP enabled and its subprocess timed out during application construction. The
same test passed with external MCP disabled; MCP contract tests enable their own fixtures. This is recorded
as a test-environment isolation risk, not hidden as a product failure or fixed through investigation code.

The remaining product release work is the broader live GitHub/Notion/Web/A2A matrix and repeated-run variance,
not IP01 repair correctness. Reopen this ADR if repair lineage needs more than one frozen gap per repair, or
if a second production consumer requires a different lifecycle; do not generalize before such an E2E exists.

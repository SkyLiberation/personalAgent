# E2E Live Behavioral Diagnostics

This suite exercises ask, research, artifact/multimodal input, and broader
workflow behavior
through routed workflow branches in the real configured environment. It is a
live diagnostic / release-confidence gate, not a deterministic golden gate:
real LLM and real web providers can drift, so the baseline uses soft aggregate
floors plus a small set of strict critical cases.

- `ask` seeds the test knowledge store first, then runs the routed
  `execute_entry` ask workflow through the real router, retrieval planner,
  answer generation, verification, repair telemetry, and Evidence Engine. It
  covers evidence-grounded answers, no-local-evidence conservative answers, and
  bounded web fallback that stays in the ask branch.
- `research_once` runs the workflow-backed Research pipeline with the real
  configured `web_search`, `capture_url`, and `graph_search` tools. It covers
  source collection, verification queries, evidence gaps, URL canonicalization,
  event clustering, budget exhaustion, satisfaction stopping, digest generation,
  and traced tool failures.
- `analyze_artifact` runs text and image artifact inputs through the real
  `inspect_artifact -> artifact-compose` workflow. Text files are interpreted
  from uploaded bytes; images degrade to metadata-only context when no vision
  model is configured.
- `workflow` covers explicit non-ask workflows and complex intent
  understanding: direct answers, text/file capture, thread summaries,
  solidification, review digest, consolidation, knowledge gap inspection,
  workflow inspection, delete confirmation diagnostics, and compound
  capture-then-ask requests.

The goal is to catch behavioral regressions and environment drift across
routing, evidence selection, answer grounding, conservative no-evidence
behavior, artifact interpretation and degradation, Research source collection,
satisfaction stopping, digest generation, non-ask workflow routing, complex
intent decomposition, tool failure degradation, latency, and observability.
The core LLM and external tools are not stubbed.
`OPENAI_API_KEY` / `OPENAI_BASE_URL` and router-compatible config must be
present, otherwise the gate skips. Other provider failures or degradations must
be diagnosed by the run output rather than bypassed in the test.

Stable algorithmic behavior such as Research clustering, URL canonicalization,
and controlled failure degrade should be covered by fixture/replay quality gates
with `baseline=1.0`. This live suite keeps those cases visible, but evaluates
them with diagnostic floors because live web results may contain different
events on different days.

Run:

```powershell
uv run pytest evals/e2e_quality -v
```

Run selected cases:

```powershell
$env:E2E_QUALITY_CASES="E2E-ASK-002,E2E-ART-001"
uv run pytest evals/e2e_quality -v
Remove-Item Env:\E2E_QUALITY_CASES
```

Run selected branches:

```powershell
$env:E2E_QUALITY_BRANCHES="ask,artifact"
uv run pytest evals/e2e_quality -v
Remove-Item Env:\E2E_QUALITY_BRANCHES
```

When `E2E_QUALITY_CASES` or `E2E_QUALITY_BRANCHES` is set, the suite records
scores and baseline diagnostics but does not fail the pytest run on baseline by
default. This keeps local debugging cheap when intentionally running a single
known-drifting live case. Set `E2E_QUALITY_ENFORCE_BASELINE=true` to force the
same threshold assertion for a selected subset.

Trace output:

- `data/e2e_quality_traces/latest.jsonl` records the latest run as streaming
  JSONL, including `case.started`, `case.completed`, `case.failed`, and
  `suite.scored` events.
- If pytest times out, inspect the last `case.started` event to identify the
  active case, then use its diagnostic logs and LLM usage fields to locate the
  provider, router, artifact, or research degradation point.

# E2E Live Behavioral Diagnostics

This suite exercises open goals, governed protocols, artifact/multimodal input,
MCP tools, and A2A delegation in the real configured environment. It is a
live diagnostic / release-confidence gate, not a deterministic golden gate:
real LLM and real web providers can drift, so the baseline uses soft aggregate
floors plus a small set of strict critical cases.

- `ask` seeds the test knowledge store first, then runs
  `execute_entry -> TaskAnalyzer -> GoalGraph -> Executive`, including retrieval planning,
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
- `github_mcp` registers local read-only fake GitHub tools with governed names
  and MCP capability metadata, then drives the full
  `execute_entry -> TaskAnalyzer -> Executive -> capability_resolution ->
  ReAct -> ToolGateway -> audit trace` path. The
  deterministic mock is only the ReAct model decision, so the test still
  verifies resource binding, resolver participation, action scope,
  gateway call, and audit record.
- `notion_mcp` mirrors the same full-chain checks for read-only Notion MCP
  prompts. It registers local fake Notion tools with governed names and
  capability metadata, drives the full
  `execute_entry -> TaskAnalyzer -> Executive -> capability_resolution ->
  ReAct -> ToolGateway -> audit trace` path, and verifies Notion write
  requests stay outside the read-only action scope.
- `gpt_researcher_a2a` checks the AgentGateway external-agent delegation path
  for a deployed GPT Researcher A2A backend. It registers a local fake
  `gpt_researcher` Agent adapter, then drives the full
  `execute_entry -> TaskAnalyzer -> Executive delegate -> capability_resolution ->
  AgentGateway -> AgentRun / AgentArtifact`
  path. The e2e assertion verifies AgentRun creation and unverified artifact
  handling instead of tool audit.

The goal is to catch behavioral regressions and environment drift across
task analysis, GoalGraph compilation, Executive decisions, evidence selection, answer grounding, conservative no-evidence
behavior, artifact interpretation and degradation, Research source collection,
satisfaction stopping, digest generation, non-ask workflow routing, complex
intent decomposition, tool failure degradation, latency, and observability.
Except for the GitHub/Notion MCP branches' deterministic ReAct tool-choice
mocks and the GPT Researcher A2A branch's fake Agent adapter, the core
LLM and external tools are not stubbed.
`OPENAI_API_KEY` / `OPENAI_BASE_URL` and structured-model config must be
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

Run only GitHub MCP tool-call plumbing:

```powershell
$env:E2E_QUALITY_BRANCHES="github_mcp"
$env:E2E_QUALITY_ENFORCE_BASELINE="true"
uv run pytest evals/e2e_quality -v
Remove-Item Env:\E2E_QUALITY_BRANCHES
Remove-Item Env:\E2E_QUALITY_ENFORCE_BASELINE
```

Run only Notion MCP tool-call plumbing:

```powershell
$env:E2E_QUALITY_BRANCHES="notion_mcp"
$env:E2E_QUALITY_ENFORCE_BASELINE="true"
uv run pytest evals/e2e_quality -v
Remove-Item Env:\E2E_QUALITY_BRANCHES
Remove-Item Env:\E2E_QUALITY_ENFORCE_BASELINE
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
  provider, task-analysis, artifact, or research degradation point.

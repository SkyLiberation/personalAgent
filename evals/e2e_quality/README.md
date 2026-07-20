# Live Core User-Outcome E2E

This suite starts from raw user input and drives the production
`AgentService.execute_entry` / `resume_entry` boundary with the model and
provider configuration loaded by `Settings.from_env()`.

No E2E case may replace `_analyze_with_model`, inject `TaskAnalysis`, mock a
store, or supply a precomputed plan. The only isolation is infrastructure
namespacing: business persistence uses `personal_agent_test`, temporary files
use a per-test directory, and Graphiti receives a unique E2E group prefix.

The verified boundary is:

```text
raw EntryInput
  -> live Task Analysis
  -> TaskContract + TaskRuntimeProjection
  -> live planning / executive control
  -> Governance admission / confirmation
  -> capability grant and real gateway execution
  -> Observation
  -> per-Goal VerificationReport
  -> CompletionReport
  -> EntryResult + durable terminal checkpoint
```

The cases prove:

1. A low-risk response request is understood by the live analyzer, answered,
   verified, and completed without a fabricated capability grant.
2. A write-then-answer request is decomposed by the live analyzer, preserves
   the output dependency, pauses before mutation, resumes with the exact grant,
   writes real test data, answers from that result, and completes only after
   both Goals are verified.
3. A mutation request whose required input is absent never fabricates a side
   effect, verification report, or completed Task.

Every case prints `LIVE_E2E_TRACE=<json>` and writes the same evidence under
`data/e2e_traces/<archive-run-id>/` by default. The archive contains:

- `manifest.json`: Git commit/dirty state, runtime fingerprint, model and prompt version;
- `*.trace.json`: input, model calls, TaskAnalysis, TaskContract, TaskRuntime,
  AgentEvents, ExecutionEvents, verification, completion and output;
- `summary.json`: pytest outcome, phase duration and failure detail for every case;
- `checksums.sha256`: integrity hashes for every JSON evidence file.

Set `PERSONAL_AGENT_E2E_TRACE_DIR` to choose another local root. The archive
stays in the E2E layer and does not change production checkpoints or business
storage. CI uploads both the structured archive and the pytest stream.

Requirements:

- PostgreSQL on `127.0.0.1:5432`, user/password `postgres/postgres`.
- A real structured model configured through `STRUCTURED_*`, `ROUTER_*`, or
  `OPENAI_*` environment variables.
- Any provider required by the scenario under test.

Run against the configured environment:

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality -v -s
```

Without PostgreSQL or a structured model, an ordinary local run skips. When
`PERSONAL_AGENT_REQUIRE_LIVE_E2E=true`, missing infrastructure is a hard
failure; CI uses this mode so an unconfigured job cannot report a false pass.

"""Real end-to-end Orchestration Golden Test (needs router LLM + Postgres).

Runs each golden-set case through a fully real ``AgentService`` — real router
LLM, real planning, real step execution, no stubs — and scores against
``baseline_real.json``. Routing-dependent floors are loose (the live router is
non-deterministic), but the safety invariants stay strict: forbidden events
(clarify-before-planning) and terminal reachability (the production 卡住 bug)
are correctness, not model taste.

Skips cleanly when the router LLM / Postgres is unconfigured. Slow: live LLM
planning and (for capture/solidify) background graph ingestion.

    uv run pytest evals/orchestration_quality/test_orchestration_real_gate.py -v

Per-case divergences (routing / terminal) print on every run so regressions are
visible even when the aggregate clears the loose floor.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .dataset import OrchestrationRunOutput, default_cases_path, load_cases
from .real_runner import build_real_service, execute_case
from .scorer import score_all

_SERVICE = build_real_service()
_SKIP_REASON = "router LLM/Postgres not configured (set ROUTER_*/OPENAI_* + PERSONAL_AGENT_POSTGRES_URL)"


@pytest.fixture(scope="module")
def cases():
    return load_cases(default_cases_path())


@pytest.fixture(scope="module")
def runs(cases) -> dict[str, OrchestrationRunOutput]:
    if _SERVICE is None:
        pytest.skip(_SKIP_REASON)
    return {case.id: execute_case(_SERVICE, case) for case in cases}


@pytest.fixture(scope="module")
def baseline():
    path = Path(__file__).parent / "baseline_real.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


@pytest.mark.skipif(_SERVICE is None, reason=_SKIP_REASON)
class TestOrchestrationRealGate:
    def test_aggregate_meets_real_baseline(self, cases, runs, baseline):
        report = score_all(cases, runs)
        divergences = [
            f"  {c.id} [{c.text[:16]}]: gold={c.expected_outcome}/{c.expected_primary_intent} "
            f"got={runs[c.id].outcome}/{runs[c.id].primary_intent} "
            f"terminal={runs[c.id].reached_terminal}"
            for c in cases
            if runs[c.id].outcome != c.expected_outcome
            or (c.expected_primary_intent and runs[c.id].primary_intent != c.expected_primary_intent)
        ]
        report_text = report.summary() + "\ndivergences:\n" + "\n".join(divergences or ["  (none)"])
        print(report_text)
        failures = report.check_thresholds(baseline)
        assert not failures, f"real-orchestration regression:\n{report_text}\nfailures={failures}"

    def test_proceeding_runs_never_hang(self, cases, runs):
        """The production 卡住 invariant under the REAL pipeline: any run that
        ACTUALLY proceeded past planning (did not pause for clarification) must
        reach a terminal event. We gate on the run's real behavior, not the
        static gold annotation — under a live router a case may legitimately
        route to clarify (e.g. solidify with no prior dialogue), and a paused
        run is correctly exempt from termination."""
        for case in cases:
            run = runs[case.id]
            if run.paused_for_clarification:
                continue
            assert run.reached_terminal, (
                f"{case.id} [{case.text[:16]}]: real run proceeded but never "
                f"terminated (hang risk); events={run.event_types}"
            )

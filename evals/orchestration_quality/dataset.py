"""Dataset model + loader for the orchestration-quality golden set.

A case is a user entry input plus *annotations* about the whole-flow shape:
the expected routing outcome (the run pauses for clarification vs. proceeds),
the expected primary intent, and an ordered *subsequence* of orchestration
event types that must appear in order.

We annotate a required ORDERED SUBSEQUENCE rather than the exact event list on
purpose: the tail of a run is environment-dependent (e.g. without a live
extraction LLM a solidify run ends ``run_failed`` instead of ``run_completed``),
but the milestone ordering — entry_started → intent_classified → steps_projected
→ … — is a stable contract. Subsequence matching pins the contract without
making the gate brittle to ingestion outcomes.

``OrchestrationRunOutput`` is the thin scoreable projection of one run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class OrchestrationEvalCase:
    id: str
    text: str
    # "completed" path proceeds through steps; "clarify" pauses for HITL.
    expected_outcome: str  # "ready" | "clarify"
    # The primary intent (router's goals[-1]); empty for clarify cases.
    expected_primary_intent: str = ""
    # Event types that MUST appear, in this order (a subsequence of the trace).
    expected_event_subsequence: list[str] = field(default_factory=list)
    # Event types that must NOT appear at all (e.g. a clarify case must never
    # emit steps_projected — it should pause before planning).
    forbidden_events: list[str] = field(default_factory=list)
    # Whether this run must reach a terminal event (run_completed/run_failed).
    # True for any run that proceeds past planning — it must never hang with
    # neither. False for clarify cases (they pause mid-flight by design).
    must_reach_terminal: bool = False
    description: str = ""


@dataclass
class OrchestrationRunOutput:
    """Scoreable projection of one orchestration run."""

    outcome: str = "ready"  # "ready" | "clarify"
    primary_intent: str = ""
    event_types: list[str] = field(default_factory=list)
    paused_for_clarification: bool = False
    # True when the run ended on a terminal event (run_completed/run_failed).
    reached_terminal: bool = False
    latency_ms: float = 0.0
    llm_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


def load_cases(path: str | Path) -> list[OrchestrationEvalCase]:
    """Load cases from a JSON array file. Unknown keys are ignored so the
    dataset file can carry human-facing notes without breaking the loader."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    fields = OrchestrationEvalCase.__dataclass_fields__.keys()
    cases: list[OrchestrationEvalCase] = []
    for entry in raw:
        kwargs = {k: v for k, v in entry.items() if k in fields}
        cases.append(OrchestrationEvalCase(**kwargs))
    return cases


def default_cases_path() -> Path:
    return Path(__file__).parent / "cases.json"

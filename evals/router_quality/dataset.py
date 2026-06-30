"""Dataset model + loader for the router-quality golden set.

A case is an entry input (the user's raw text) plus *annotations*: the expected
routing outcome (ready / clarify), the expected intent sequence (ordered — the
router's ``primary_intent`` is ``goals[-1]`` and goals render as ``a → b``), and
the expected clarification fields when clarify is expected.

``RouterRunOutput`` is the thin, scoreable projection of one routing decision:
outcome, intent sequence, route type, coverage, capability match, and whether
clarification was raised. The scorer only ever sees a ``RouterRunOutput``, so
it stays decoupled from the live router and is trivially unit-testable with
hand-built fixtures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RouterEvalCase:
    id: str
    text: str
    # "ready" | "clarify"
    expected_outcome: str
    # Expected intent sequence, in order. Empty for clarify cases.
    expected_intents: list[str] = field(default_factory=list)
    expected_route_type: str = ""
    expected_coverage: str = ""
    expected_matched_capabilities: list[str] = field(default_factory=list)
    expected_missing_requirements: list[str] = field(default_factory=list)
    # Substrings expected to appear in the clarification's missing_information
    # (clarify cases only). Empty means "don't assert on the fields".
    expected_missing_info: list[str] = field(default_factory=list)
    source_type: str = "text"
    artifacts: list[dict] = field(default_factory=list)
    description: str = ""


@dataclass
class RouterRunOutput:
    """Scoreable projection of one routing decision."""

    outcome: str = "ready"
    intents: list[str] = field(default_factory=list)
    route_type: str = ""
    coverage: str = ""
    matched_capabilities: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    raised_clarification: bool = False
    missing_information: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    llm_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


def load_cases(path: str | Path) -> list[RouterEvalCase]:
    """Load cases from a JSON array file. Unknown keys are ignored so the
    dataset file can carry human-facing notes without breaking the loader."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    fields = RouterEvalCase.__dataclass_fields__.keys()
    cases: list[RouterEvalCase] = []
    for entry in raw:
        kwargs = {k: v for k, v in entry.items() if k in fields}
        case = RouterEvalCase(**kwargs)
        if not case.expected_route_type:
            object.__setattr__(case, "expected_route_type", _default_route_type(case))
        if not case.expected_coverage:
            object.__setattr__(case, "expected_coverage", _default_coverage(case))
        if not case.expected_matched_capabilities and case.expected_outcome == "ready":
            object.__setattr__(
                case,
                "expected_matched_capabilities",
                list(case.expected_intents),
            )
        cases.append(case)
    return cases


def default_cases_path() -> Path:
    return Path(__file__).parent / "cases.json"


def _default_route_type(case: RouterEvalCase) -> str:
    if case.expected_outcome == "clarify":
        return "clarify"
    if case.expected_outcome in {"unsupported", "rejected"}:
        return case.expected_outcome
    if case.expected_intents == ["direct_answer"]:
        return "direct_answer"
    if len(case.expected_intents) > 1:
        return "composite_workflow"
    return "single_workflow"


def _default_coverage(case: RouterEvalCase) -> str:
    if case.expected_outcome == "clarify":
        return "ambiguous"
    if case.expected_outcome == "unsupported":
        return "unsupported"
    if case.expected_outcome == "rejected":
        return "unsupported"
    return "full"

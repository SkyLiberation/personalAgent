"""Dataset model + loader for the router-quality golden set.

A case is an entry input (the user's raw text) plus *annotations*: the expected
routing outcome (ready / clarify), the expected intent sequence (ordered — the
router's ``primary_intent`` is ``goals[-1]`` and goals render as ``a → b``), and
the expected clarification fields when clarify is expected.

``RouterRunOutput`` is the thin, scoreable projection of one routing decision —
outcome, intent sequence, and whether clarification was raised. The scorer only
ever sees a ``RouterRunOutput``, so it stays decoupled from the live router and
is trivially unit-testable with hand-built fixtures.
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
    # Substrings expected to appear in the clarification's missing_information
    # (clarify cases only). Empty means "don't assert on the fields".
    expected_missing_info: list[str] = field(default_factory=list)
    source_type: str = "text"
    description: str = ""


@dataclass
class RouterRunOutput:
    """Scoreable projection of one routing decision."""

    outcome: str = "ready"
    intents: list[str] = field(default_factory=list)
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
        cases.append(RouterEvalCase(**kwargs))
    return cases


def default_cases_path() -> Path:
    return Path(__file__).parent / "cases.json"

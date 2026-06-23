"""Dataset and scoreable projections for multi-turn conversation evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TurnExpectation:
    kind: str  # "entry" | "resume"
    user_input: str = ""
    decision: str = "clarify"
    option_id: str = ""
    expected_outcome: str = "ready"  # "ready" | "clarify"
    expected_intents: list[str] = field(default_factory=list)
    expected_event_subsequence: list[str] = field(default_factory=list)
    expected_context_refs: list[int] = field(default_factory=list)
    expected_response_contains: list[str] = field(default_factory=list)
    must_reach_terminal: bool = False


@dataclass(frozen=True)
class ConversationEvalCase:
    id: str
    turns: list[TurnExpectation]
    description: str = ""
    expected_final_note_delta: int | None = None
    require_single_thread: bool = True


@dataclass
class ConversationTurnOutput:
    kind: str = "entry"
    outcome: str = "ready"
    intents: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    reply_text: str = ""
    run_id: str = ""
    thread_id: str = ""
    resumed_from_run_id: str = ""
    retained_context_refs: list[int] = field(default_factory=list)
    reached_terminal: bool = False


@dataclass
class ConversationRunOutput:
    turns: list[ConversationTurnOutput] = field(default_factory=list)
    initial_note_count: int = 0
    final_note_count: int = 0
    latency_ms: float = 0.0
    llm_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @property
    def final_note_delta(self) -> int:
        return self.final_note_count - self.initial_note_count


def _load_turn(raw: dict) -> TurnExpectation:
    fields = TurnExpectation.__dataclass_fields__.keys()
    return TurnExpectation(**{key: value for key, value in raw.items() if key in fields})


def load_cases(path: str | Path) -> list[ConversationEvalCase]:
    raw_cases = json.loads(Path(path).read_text(encoding="utf-8"))
    fields = ConversationEvalCase.__dataclass_fields__.keys()
    cases: list[ConversationEvalCase] = []
    for raw in raw_cases:
        kwargs = {key: value for key, value in raw.items() if key in fields and key != "turns"}
        kwargs["turns"] = [_load_turn(turn) for turn in raw.get("turns", [])]
        cases.append(ConversationEvalCase(**kwargs))
    return cases


def load_runs(path: str | Path) -> dict[str, ConversationRunOutput]:
    raw_runs = json.loads(Path(path).read_text(encoding="utf-8"))
    runs: dict[str, ConversationRunOutput] = {}
    for case_id, raw in raw_runs.items():
        if case_id.startswith("_"):
            continue
        turns = [ConversationTurnOutput(**turn) for turn in raw.get("turns", [])]
        runs[case_id] = ConversationRunOutput(
            turns=turns,
            initial_note_count=int(raw.get("initial_note_count", 0)),
            final_note_count=int(raw.get("final_note_count", 0)),
            latency_ms=float(raw.get("latency_ms", 0.0)),
            llm_call_count=int(raw.get("llm_call_count", 0)),
            input_tokens=int(raw.get("input_tokens", 0)),
            output_tokens=int(raw.get("output_tokens", 0)),
            total_tokens=int(raw.get("total_tokens", 0)),
        )
    return runs


def default_cases_path() -> Path:
    return Path(__file__).parent / "cases.json"


def default_reference_runs_path() -> Path:
    return Path(__file__).parent / "reference_runs.json"

"""Golden cases for semantic task analysis, before capability resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TaskAnalysisEvalCase:
    id: str
    text: str
    expected_outcome: str
    expected_result_contracts: list[str] = field(default_factory=list)
    expected_missing_info: list[str] = field(default_factory=list)
    source_type: str = "text"
    artifacts: list[dict] = field(default_factory=list)
    description: str = ""


@dataclass
class TaskAnalysisRunOutput:
    outcome: str = "ready"
    result_contracts: list[str] = field(default_factory=list)
    raised_clarification: bool = False
    missing_information: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    llm_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


def load_cases(path: str | Path) -> list[TaskAnalysisEvalCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    fields = TaskAnalysisEvalCase.__dataclass_fields__.keys()
    return [TaskAnalysisEvalCase(**{
        key: value for key, value in entry.items() if key in fields
    }) for entry in raw]


def default_cases_path() -> Path:
    return Path(__file__).parent / "cases.json"

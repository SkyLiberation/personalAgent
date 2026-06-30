"""Dataset and projections for Research request-understanding evals."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResearchUnderstandingEvalCase:
    id: str
    raw_request: str
    default_max_items: int = 5
    expected_topic_terms: list[str] = field(default_factory=list)
    forbidden_topic_terms: list[str] = field(default_factory=list)
    expected_instruction_terms: list[str] = field(default_factory=list)
    expected_max_items: int | None = None
    expected_research_type: str = ""
    acceptable_research_types: list[str] = field(default_factory=list)
    expected_evidence_requirement: str = ""
    acceptable_evidence_requirements: list[str] = field(default_factory=list)
    expected_query_intents: list[str] = field(default_factory=list)


@dataclass
class ResearchUnderstandingRunOutput:
    topic: str = ""
    instructions: str = ""
    max_items: int = 0
    research_type: str = ""
    evidence_requirement: str = ""
    query_intents: list[str] = field(default_factory=list)
    query_texts: list[str] = field(default_factory=list)
    llm_call_count: int = 0


def load_understanding_cases(path: str | Path | None = None) -> list[ResearchUnderstandingEvalCase]:
    raw = json.loads((Path(path) if path else default_understanding_cases_path()).read_text(encoding="utf-8"))
    return [
        ResearchUnderstandingEvalCase(
            id=str(item["id"]),
            raw_request=str(item["raw_request"]),
            default_max_items=int(item.get("default_max_items", 5)),
            expected_topic_terms=[str(term) for term in item.get("expected_topic_terms", [])],
            forbidden_topic_terms=[str(term) for term in item.get("forbidden_topic_terms", [])],
            expected_instruction_terms=[str(term) for term in item.get("expected_instruction_terms", [])],
            expected_max_items=(
                int(item["expected_max_items"])
                if "expected_max_items" in item else None
            ),
            expected_research_type=str(item.get("expected_research_type") or ""),
            acceptable_research_types=[
                str(value) for value in item.get("acceptable_research_types", [])
            ],
            expected_evidence_requirement=str(item.get("expected_evidence_requirement") or ""),
            acceptable_evidence_requirements=[
                str(value) for value in item.get("acceptable_evidence_requirements", [])
            ],
            expected_query_intents=[str(intent) for intent in item.get("expected_query_intents", [])],
        )
        for item in raw
    ]


def default_understanding_cases_path() -> Path:
    return Path(__file__).parent / "understanding_cases.json"


def run_output_from_state(state: Any) -> ResearchUnderstandingRunOutput:
    policy = getattr(state, "policy", None)
    query_plan = list(getattr(state, "query_plan", []) or [])
    return ResearchUnderstandingRunOutput(
        topic=str(getattr(state, "topic", "")),
        instructions=str(getattr(state, "instructions", "")),
        max_items=int(getattr(state, "max_items", 0)),
        research_type=str(getattr(policy, "research_type", "")),
        evidence_requirement=str(getattr(policy, "evidence_requirement", "")),
        query_intents=[str(getattr(query, "intent", "")) for query in query_plan],
        query_texts=[str(getattr(query, "query", "")) for query in query_plan],
    )

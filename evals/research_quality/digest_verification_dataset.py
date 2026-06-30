"""Dataset and projections for Research digest claim-verification evals."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DigestVerificationEvalCase:
    id: str
    description: str = ""
    event_status: str = "uncertain"
    event_title: str = ""
    event_summary: str = ""
    source: dict[str, Any] = field(default_factory=dict)
    input_claims: list[dict[str, str]] = field(default_factory=list)
    expected_item_count: int = 0
    expected_no_major_update: bool = False
    expected_run_status: str = ""
    expected_confidence_labels: list[str] = field(default_factory=list)
    expected_claim_support_levels: list[str] = field(default_factory=list)
    expected_absent_claim_terms: list[str] = field(default_factory=list)


@dataclass
class DigestVerificationRunOutput:
    item_count: int = 0
    no_major_update: bool = False
    run_status: str = ""
    confidence_labels: list[str] = field(default_factory=list)
    claim_support_levels: list[str] = field(default_factory=list)
    retained_claim_texts: list[str] = field(default_factory=list)


def load_digest_verification_cases(
    path: str | Path | None = None,
) -> list[DigestVerificationEvalCase]:
    raw = json.loads(
        (Path(path) if path else default_digest_verification_cases_path()).read_text(
            encoding="utf-8"
        )
    )
    return [
        DigestVerificationEvalCase(
            id=str(item["id"]),
            description=str(item.get("description", "")),
            event_status=str(item.get("event_status") or "uncertain"),
            event_title=str(item.get("event_title") or ""),
            event_summary=str(item.get("event_summary") or ""),
            source=dict(item.get("source") or {}),
            input_claims=[dict(claim) for claim in item.get("input_claims", [])],
            expected_item_count=int(item.get("expected_item_count", 0)),
            expected_no_major_update=bool(item.get("expected_no_major_update", False)),
            expected_run_status=str(item.get("expected_run_status") or ""),
            expected_confidence_labels=[
                str(label) for label in item.get("expected_confidence_labels", [])
            ],
            expected_claim_support_levels=[
                str(level) for level in item.get("expected_claim_support_levels", [])
            ],
            expected_absent_claim_terms=[
                str(term) for term in item.get("expected_absent_claim_terms", [])
            ],
        )
        for item in raw
    ]


def default_digest_verification_cases_path() -> Path:
    return Path(__file__).parent / "digest_verification_cases.json"

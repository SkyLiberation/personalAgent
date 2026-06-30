"""Deterministic gate for claim-level Research digest verification."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from personal_agent.application.research import ResearchService
from personal_agent.application.research.models import (
    DigestClaim,
    IntelligenceDigest,
    IntelligenceDigestItem,
    ResearchEvent,
    ResearchRun,
    ResearchSource,
)

from .digest_verification_dataset import (
    DigestVerificationRunOutput,
    load_digest_verification_cases,
)
from .digest_verification_scorer import score_digest_verification_all


class _Store:
    def __init__(self) -> None:
        self.runs: dict[str, ResearchRun] = {}
        self.events: dict[str, list[ResearchEvent]] = {}
        self.digests: dict[str, IntelligenceDigest] = {}

    def get_run(self, run_id: str) -> ResearchRun | None:
        return self.runs.get(run_id)

    def get_digest(self, digest_id: str) -> IntelligenceDigest | None:
        return self.digests.get(digest_id)

    def save_digest(self, digest: IntelligenceDigest) -> IntelligenceDigest:
        self.digests[digest.id] = digest
        return digest

    def update_run(self, run: ResearchRun) -> ResearchRun:
        self.runs[run.id] = run
        return run

    def list_run_events(self, run_id: str) -> list[ResearchEvent]:
        return list(self.events.get(run_id, []))


class _Tools:
    def __contains__(self, name: str) -> bool:
        return False

    def invoke_direct(self, name: str, **kwargs):
        return {"ok": False}


def test_research_digest_claim_verification_meets_baseline():
    cases = load_digest_verification_cases()
    outputs: dict[str, DigestVerificationRunOutput] = {}

    for case in cases:
        store = _Store()
        run, digest = _build_run_and_digest(case)
        store.runs[run.id] = run
        store.events[run.id] = [_build_event(case)]
        store.digests[digest.id] = digest

        service = ResearchService(store, _Tools())
        verified = service.verify_digest(run.id)
        updated_run = store.get_run(run.id)
        outputs[case.id] = _project_output(
            verified,
            updated_run.status if updated_run else "",
        )

    report = score_digest_verification_all(cases, outputs)
    baseline = json.loads(
        (Path(__file__).parent / "digest_verification_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    failures = report.check_thresholds(baseline)
    assert not failures, f"regression:\n{report.summary()}\nfailures={failures}"


def _build_run_and_digest(case):
    run = ResearchRun(
        id=f"{case.id}-run",
        user_id="digest-verification-eval",
        topic="AI Agent",
        window_start=datetime(2026, 6, 29, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 6, 29, 1, 0, tzinfo=UTC),
        digest_id=f"{case.id}-digest",
    )
    source = case.source
    item = IntelligenceDigestItem(
        short_id="N1",
        event_id=f"{case.id}-event",
        title=case.event_title,
        what_happened=case.event_summary,
        why_it_matters="",
        confidence_label="已验证",
        source_urls=[str(source.get("url") or "")],
        claims=[
            DigestClaim(
                text=str(claim.get("text") or ""),
                claim_importance=str(claim.get("claim_importance") or "core"),
            )
            for claim in case.input_claims
        ],
    )
    digest = IntelligenceDigest(
        id=run.digest_id or "",
        run_id=run.id,
        user_id=run.user_id,
        title="digest",
        executive_summary="summary",
        items=[item],
    )
    return run, digest


def _build_event(case) -> ResearchEvent:
    source = case.source
    url = str(source.get("url") or "")
    return ResearchEvent(
        id=f"{case.id}-event",
        canonical_key=f"{case.id}-event",
        title=case.event_title,
        summary=case.event_summary,
        sources=[
            ResearchSource(
                id=f"{case.id}-source",
                decision_id=f"{case.id}-decision",
                query="Agent Model official announcement",
                query_phase="verification",
                url=url,
                canonical_url=url,
                domain=str(source.get("domain") or ""),
                title=str(source.get("title") or case.event_title),
                snippet=str(source.get("content") or ""),
                content=str(source.get("content") or ""),
                source_type=str(source.get("source_type") or "unknown"),
            )
        ],
        status=case.event_status,
    )


def _project_output(
    digest: IntelligenceDigest | None,
    run_status: str,
) -> DigestVerificationRunOutput:
    items = list(getattr(digest, "items", []) or []) if digest else []
    claims = [
        claim
        for item in items
        for claim in (getattr(item, "claims", []) or [])
    ]
    return DigestVerificationRunOutput(
        item_count=len(items),
        no_major_update=bool(getattr(digest, "no_major_update", False)),
        run_status=run_status,
        confidence_labels=[
            str(getattr(item, "confidence_label", ""))
            for item in items
        ],
        claim_support_levels=[
            str(getattr(claim, "support_level", ""))
            for claim in claims
        ],
        retained_claim_texts=[
            str(getattr(claim, "text", ""))
            for claim in claims
        ],
    )

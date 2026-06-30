from __future__ import annotations

from datetime import UTC, datetime

from personal_agent.application.research import ResearchService
from personal_agent.application.research.models import (
    DigestClaim,
    IntelligenceDigest,
    IntelligenceDigestItem,
    ResearchEvent,
    ResearchRun,
    ResearchSource,
)


class _Store:
    def __init__(self):
        self.runs = {}
        self.events = {}
        self.digests = {}

    def get_run(self, run_id):
        return self.runs.get(run_id)

    def get_digest(self, digest_id):
        return self.digests.get(digest_id)

    def save_digest(self, digest):
        self.digests[digest.id] = digest
        return digest

    def update_run(self, run):
        self.runs[run.id] = run
        return run

    def list_run_events(self, run_id):
        return self.events.get(run_id, [])


class _Tools:
    def __contains__(self, name: str) -> bool:
        return False

    def invoke_direct(self, name: str, **kwargs):
        return {"ok": False}


def _run_with_digest(event: ResearchEvent, item: IntelligenceDigestItem):
    store = _Store()
    run = ResearchRun(
        id="run-1",
        user_id="alice",
        topic="AI Agent",
        window_start=datetime(2026, 6, 29, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 6, 29, 1, 0, tzinfo=UTC),
        digest_id="digest-1",
    )
    digest = IntelligenceDigest(
        id="digest-1",
        run_id=run.id,
        user_id=run.user_id,
        title="digest",
        executive_summary="summary",
        items=[item],
    )
    store.runs[run.id] = run
    store.events[run.id] = [event]
    store.digests[digest.id] = digest
    return ResearchService(store, _Tools()), run


def _source() -> ResearchSource:
    return ResearchSource(
        id="source-1",
        decision_id="decision-1",
        query="Agent Model official announcement",
        query_phase="verification",
        url="https://openai.com/news/agent",
        canonical_url="https://openai.com/news/agent",
        domain="openai.com",
        title="OpenAI releases Agent Model",
        snippet="OpenAI released a new agent model for tool use.",
        content="OpenAI released a new agent model for tool use.",
        source_type="official",
    )


def test_verify_digest_marks_unsupported_claim_without_trusting_url():
    source = _source()
    event = ResearchEvent(
        id="event-1",
        canonical_key="agent-model",
        title="OpenAI releases Agent Model",
        summary="OpenAI released a new agent model for tool use.",
        sources=[source],
        status="verified",
    )
    item = IntelligenceDigestItem(
        short_id="N1",
        event_id=event.id,
        title=event.title,
        what_happened=event.summary,
        why_it_matters="",
        confidence_label="已验证",
        source_urls=[source.url],
        claims=[
            DigestClaim(text="OpenAI releases Agent Model"),
            DigestClaim(
                text="The model guarantees a 10x latency improvement",
                claim_importance="supporting",
            ),
        ],
    )
    service, run = _run_with_digest(event, item)

    digest = service.verify_digest(run.id)

    assert digest is not None
    assert len(digest.items) == 1
    assert [claim.support_level for claim in digest.items[0].claims] == [
        "supported",
    ]
    assert digest.items[0].claims[0].decision_ids == ["decision-1"]
    assert digest.items[0].confidence_label == "信息不足"
    assert service.store.get_run(run.id).status == "completed_with_limitations"


def test_verify_digest_removes_contradicted_item():
    source = _source()
    event = ResearchEvent(
        id="event-1",
        canonical_key="agent-model",
        title="OpenAI releases Agent Model",
        summary="OpenAI released a new agent model for tool use.",
        sources=[source],
        status="verified",
    )
    item = IntelligenceDigestItem(
        short_id="N1",
        event_id=event.id,
        title=event.title,
        what_happened=event.summary,
        why_it_matters="",
        confidence_label="已验证",
        source_urls=[source.url],
        claims=[DigestClaim(text="OpenAI does not release Agent Model")],
    )
    service, run = _run_with_digest(event, item)

    digest = service.verify_digest(run.id)

    assert digest is not None
    assert digest.items == []
    assert digest.no_major_update is True
    assert service.store.get_run(run.id).status == "partial_no_supported_claims"


def test_verify_digest_does_not_upgrade_reported_to_verified():
    source = _source()
    event = ResearchEvent(
        id="event-1",
        canonical_key="agent-model",
        title="OpenAI releases Agent Model",
        summary="OpenAI released a new agent model for tool use.",
        sources=[source],
        status="reported",
    )
    item = IntelligenceDigestItem(
        short_id="N1",
        event_id=event.id,
        title=event.title,
        what_happened=event.summary,
        why_it_matters="",
        confidence_label="已验证",
        source_urls=[source.url],
        claims=[DigestClaim(text="OpenAI releases Agent Model")],
    )
    service, run = _run_with_digest(event, item)

    digest = service.verify_digest(run.id)

    assert digest is not None
    assert digest.items[0].claims[0].support_level == "supported"
    assert digest.items[0].confidence_label == "多方报道"
    assert service.store.get_run(run.id).status == "completed_with_limitations"

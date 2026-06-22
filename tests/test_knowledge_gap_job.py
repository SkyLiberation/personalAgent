from __future__ import annotations

from personal_agent.insight.analyzer import KnowledgeGap
from personal_agent.insight.job import KnowledgeGapJob, KnowledgeGapScheduler
from personal_agent.insight.service import KnowledgeGapReport, format_knowledge_gaps
from personal_agent.review.models import (
    DeliveryMessage,
    DeliveryResult,
    DeliveryTarget,
    DigestSubscription,
)
from personal_agent.review.delivery import DeliveryRouter


class StubUseCase:
    def __init__(self, gaps) -> None:
        self._gaps = gaps

    def inspect(self, user_id):
        gaps = list(self._gaps)
        return KnowledgeGapReport(
            user_id=user_id,
            gaps=[{
                "gap_type": gap.gap_type,
                "key": gap.key,
                "question": gap.question,
                "entities": gap.entities,
                "note_ids": gap.note_ids,
            } for gap in gaps],
            text=format_knowledge_gaps(gaps),
        )


class RecordingProvider:
    def __init__(self) -> None:
        self.calls = []

    def send(self, target: DeliveryTarget, message: DeliveryMessage) -> DeliveryResult:
        self.calls.append((target, message))
        return DeliveryResult(ok=True, provider_message_id="m1")


def _subscription(**overrides):
    base = dict(id="sub-1", user_id="alice", channel="feishu", target_type="chat_id", target_id="chat-1")
    base.update(overrides)
    return DigestSubscription(**base)


def test_job_delivers_question_when_gaps_exist():
    provider = RecordingProvider()
    gap = KnowledgeGap(gap_type="isolated_entity", key="isolated:n1", question="补充一下 X 吧？", entities=["X"])
    job = KnowledgeGapJob(StubUseCase([gap]), DeliveryRouter({"feishu": provider}))

    result = job.run(_subscription())

    assert result.delivered is True
    assert result.gaps_found == 1
    assert len(provider.calls) == 1
    _, message = provider.calls[0]
    assert "补充一下 X 吧？" in message.text
    assert message.metadata["kind"] == "knowledge_gap"


def test_job_skips_delivery_when_no_gaps():
    provider = RecordingProvider()
    job = KnowledgeGapJob(StubUseCase([]), DeliveryRouter({"feishu": provider}))

    result = job.run(_subscription())

    assert result.skipped is True
    assert result.delivered is False
    assert provider.calls == []


def test_job_skips_disabled_subscription():
    provider = RecordingProvider()
    gap = KnowledgeGap(gap_type="isolated_entity", key="k", question="q")
    job = KnowledgeGapJob(StubUseCase([gap]), DeliveryRouter({"feishu": provider}))

    result = job.run(_subscription(enabled=False))

    assert result.skipped is True
    assert provider.calls == []


def test_job_delivers_at_most_once_per_day():
    provider = RecordingProvider()
    gap = KnowledgeGap(gap_type="isolated_entity", key="k", question="q")
    job = KnowledgeGapJob(StubUseCase([gap]), DeliveryRouter({"feishu": provider}))
    subscription = _subscription()

    first = job.run(subscription)
    second = job.run(subscription)

    assert first.delivered is True
    assert second.skipped is True
    # Only one delivery despite two runs in the same day (tick-loop guard).
    assert len(provider.calls) == 1


class FakeGapLedger:
    """Durable claim store shared across job instances (simulates restart)."""

    def __init__(self) -> None:
        self.claimed: set[str] = set()

    def claim_gap_delivery(self, subscription_id: str, gap_date: str) -> bool:
        key = f"{subscription_id}:{gap_date}"
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True


def test_ledger_blocks_redelivery_across_restart():
    provider = RecordingProvider()
    gap = KnowledgeGap(gap_type="isolated_entity", key="k", question="q")
    ledger = FakeGapLedger()
    subscription = _subscription()

    job1 = KnowledgeGapJob(StubUseCase([gap]), DeliveryRouter({"feishu": provider}), ledger=ledger)
    first = job1.run(subscription)

    # New job instance = process restart; in-memory guard would be empty, but
    # the durable ledger still blocks a second delivery.
    job2 = KnowledgeGapJob(StubUseCase([gap]), DeliveryRouter({"feishu": provider}), ledger=ledger)
    second = job2.run(subscription)

    assert first.delivered is True
    assert second.skipped is True
    assert len(provider.calls) == 1


def test_gap_free_run_does_not_burn_daily_claim():
    provider = RecordingProvider()
    ledger = FakeGapLedger()
    subscription = _subscription()

    # Morning run finds nothing -> must not claim the day's slot.
    empty_job = KnowledgeGapJob(StubUseCase([]), DeliveryRouter({"feishu": provider}), ledger=ledger)
    empty_job.run(subscription)
    assert ledger.claimed == set()

    # Later run finds a gap -> should still be able to deliver.
    gap = KnowledgeGap(gap_type="isolated_entity", key="k", question="q")
    real_job = KnowledgeGapJob(StubUseCase([gap]), DeliveryRouter({"feishu": provider}), ledger=ledger)
    result = real_job.run(subscription)

    assert result.delivered is True
    assert len(provider.calls) == 1


def test_scheduler_runs_due_subscriptions():
    provider = RecordingProvider()
    gap = KnowledgeGap(gap_type="isolated_entity", key="k", question="q")
    job = KnowledgeGapJob(StubUseCase([gap]), DeliveryRouter({"feishu": provider}))

    class Store:
        def list_subscriptions(self, *, enabled_only=True):
            # schedule_time in the past so it is always due
            return [_subscription(schedule_time="00:00")]

    results = KnowledgeGapScheduler(Store(), job).run_due()

    assert len(results) == 1
    assert results[0].delivered is True

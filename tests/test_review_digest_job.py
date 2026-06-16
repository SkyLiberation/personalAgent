from __future__ import annotations

from datetime import timedelta

from personal_agent.core.config import ReviewDigestConfig, Settings
from personal_agent.core.models import ReviewCard, local_now
from personal_agent.review import (
    DeliveryMessage,
    DeliveryResult,
    DeliveryTarget,
    DigestSubscription,
    ReviewDigestJob,
    ReviewDigestUseCase,
    subscriptions_from_settings,
)
from personal_agent.review.delivery import DeliveryRouter
from tests.note_factory import make_note


class FakeMemory:
    def __init__(self) -> None:
        self.note = make_note(
            title="复习触达",
            content="Digest 应主动推送到飞书。",
            summary="Digest 主动推送",
            user_id="alice",
        )
        self.review = ReviewCard(
            note_id=self.note.id,
            prompt="请回忆 Digest 的主触达入口",
            answer_hint="飞书",
            due_at=local_now() - timedelta(minutes=1),
        )

    def list_recent_notes(self, user_id: str, *, limit: int = 5, include_chunks: bool = True):
        return [self.note] if user_id == "alice" else []

    def due_reviews(self, user_id: str):
        return [self.review] if user_id == "alice" else []


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[DeliveryTarget, DeliveryMessage]] = []

    def send(self, target: DeliveryTarget, message: DeliveryMessage) -> DeliveryResult:
        self.calls.append((target, message))
        return DeliveryResult(ok=True, provider_message_id="msg-1")


def test_subscriptions_from_settings_uses_review_digest_config(temp_dir):
    settings = Settings(
        data_dir=temp_dir,
        review_digest=ReviewDigestConfig(
            enabled=True,
            user_id="alice",
            feishu_chat_ids=("chat-1", "chat-2"),
            schedule_time="08:30",
            timezone="Asia/Shanghai",
        ),
    )

    subscriptions = subscriptions_from_settings(settings)

    assert [s.target_id for s in subscriptions] == ["chat-1", "chat-2"]
    assert {s.user_id for s in subscriptions} == {"alice"}
    assert {s.schedule_time for s in subscriptions} == {"08:30"}


def test_subscriptions_from_settings_returns_empty_when_disabled(temp_dir):
    settings = Settings(
        data_dir=temp_dir,
        review_digest=ReviewDigestConfig(
            enabled=False,
            user_id="alice",
            feishu_chat_ids=("chat-1",),
        ),
    )

    assert subscriptions_from_settings(settings) == []


def test_review_digest_job_generates_and_delivers_digest():
    provider = RecordingProvider()
    job = ReviewDigestJob(
        ReviewDigestUseCase(FakeMemory()),
        DeliveryRouter({"feishu": provider}),
    )
    subscription = DigestSubscription(
        id="sub-1",
        user_id="alice",
        channel="feishu",
        target_type="chat_id",
        target_id="chat-1",
    )

    result = job.run(subscription)

    assert result.delivered is True
    assert result.error is None
    assert len(provider.calls) == 1
    target, message = provider.calls[0]
    assert target.target_id == "chat-1"
    assert "今日知识简报" in message.text
    assert "请回忆 Digest 的主触达入口" in message.text


def test_review_digest_job_skips_disabled_subscription():
    provider = RecordingProvider()
    job = ReviewDigestJob(
        ReviewDigestUseCase(FakeMemory()),
        DeliveryRouter({"feishu": provider}),
    )

    result = job.run(DigestSubscription(
        id="sub-disabled",
        user_id="alice",
        target_id="chat-1",
        enabled=False,
    ))

    assert result.skipped is True
    assert result.delivered is False
    assert provider.calls == []


def test_review_digest_job_uses_delivery_ledger_for_idempotency():
    class MemoryLedger:
        def __init__(self) -> None:
            self.reserved: dict[str, str] = {}
            self.completed: list[tuple[str, str]] = []
            self.items: list[tuple[str, list[str]]] = []

        def reserve_delivery(self, subscription: DigestSubscription, digest_date: str):
            key = f"digest:{subscription.id}:{digest_date}"
            if key in self.reserved:
                return False, self.reserved[key], key
            self.reserved[key] = "delivery-1"
            return True, "delivery-1", key

        def complete_delivery(self, delivery_id: str, *, status: str, provider_message_id=None, error=None):
            self.completed.append((delivery_id, status))

        def add_delivery_items(self, delivery_id: str, digest):
            self.items.append((delivery_id, [card.id for card in digest.due_cards]))

    memory = FakeMemory()
    provider = RecordingProvider()
    ledger = MemoryLedger()
    job = ReviewDigestJob(
        ReviewDigestUseCase(memory),
        DeliveryRouter({"feishu": provider}),
        ledger=ledger,
    )
    subscription = DigestSubscription(
        id="sub-1",
        user_id="alice",
        target_id="chat-1",
    )

    first = job.run(subscription)
    second = job.run(subscription)

    assert first.delivered is True
    assert second.skipped is True
    assert len(provider.calls) == 1
    assert ledger.completed == [("delivery-1", "sent")]
    assert ledger.items == [("delivery-1", [memory.review.id])]

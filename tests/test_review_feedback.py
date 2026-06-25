from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from personal_agent.kernel.models import ReviewCard, local_now
from personal_agent.memory.facade import MemoryFacade
from personal_agent.governance.policy import PolicyEngine
from personal_agent.application.review import DigestSubscription, ReviewDigest
from personal_agent.application.review.service import ReviewFeedbackUseCase
from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
from personal_agent.infra.storage.postgres_review_digest_store import PostgresReviewDigestStore
from tests.conftest import POSTGRES_URL
from tests.note_factory import make_note


pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


def test_review_feedback_updates_card_from_delivery_short_id(temp_dir: Path):
    memory = MemoryFacade(PostgresMemoryStore(temp_dir, POSTGRES_URL), policy_engine=PolicyEngine())
    digest_store = PostgresReviewDigestStore(POSTGRES_URL)
    note = make_note(id="note-1", user_id="alice", title="Digest", content="Digest 通过飞书触达")
    card = ReviewCard(
        id="card-1",
        note_id=note.id,
        prompt="Digest 的主触达入口是什么？",
        answer_hint="飞书",
        interval_days=2,
        due_at=local_now() - timedelta(minutes=5),
    )
    memory.add_note(note, user_id="alice")
    memory.add_review(card)

    subscription = DigestSubscription(id="sub-1", user_id="alice", target_id="chat-1")
    reserved, delivery_id, _key = digest_store.reserve_delivery(subscription, "2026-06-16")
    assert reserved is True
    digest_store.add_delivery_items(delivery_id, ReviewDigest(user_id="alice", due_cards=[card]))
    digest_store.complete_delivery(delivery_id, status="sent")

    result = ReviewFeedbackUseCase(memory, digest_store).apply_from_delivery_short_id(
        user_id="alice",
        target_id="chat-1",
        short_id="R1",
        outcome="remembered",
        source_channel="feishu",
        source_message_id="msg-1",
    )

    assert result.ok is True
    updated = memory.get_review(card.id, "alice")
    assert updated is not None
    assert updated.interval_days == 4
    assert updated.last_reviewed_at is not None
    assert updated.due_at > local_now() + timedelta(days=3)
    events = digest_store.list_feedback_events(user_id="alice")
    assert events[0]["review_card_id"] == card.id
    assert events[0]["delivery_id"] == delivery_id

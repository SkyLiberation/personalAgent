from __future__ import annotations

import pytest

from personal_agent.kernel.models import ReviewCard
from personal_agent.application.review import DigestSubscription, ReviewDigest
from personal_agent.infra.storage.postgres_review_digest_store import PostgresReviewDigestStore
from tests.conftest import POSTGRES_URL


pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


def test_claim_gap_delivery_is_idempotent_per_day():
    store = PostgresReviewDigestStore(POSTGRES_URL)

    first = store.claim_gap_delivery("sub-1", "2026-06-20")
    second = store.claim_gap_delivery("sub-1", "2026-06-20")
    next_day = store.claim_gap_delivery("sub-1", "2026-06-21")
    other_sub = store.claim_gap_delivery("sub-2", "2026-06-20")

    assert first is True       # first claim wins
    assert second is False     # same (sub, day) blocked
    assert next_day is True    # new day is a fresh slot
    assert other_sub is True   # different subscription is independent


def test_review_digest_store_upserts_and_lists_subscriptions():
    store = PostgresReviewDigestStore(POSTGRES_URL)
    subscription = DigestSubscription(
        id="sub-1",
        user_id="alice",
        channel="feishu",
        target_type="chat_id",
        target_id="chat-1",
        schedule_time="08:30",
    )

    store.upsert_subscription(subscription)
    listed = store.list_subscriptions()

    assert [item.id for item in listed] == ["sub-1"]
    assert listed[0].target_id == "chat-1"


def test_review_digest_store_filters_disabled_subscriptions():
    store = PostgresReviewDigestStore(POSTGRES_URL)
    store.upsert_subscription(DigestSubscription(
        id="enabled",
        user_id="alice",
        target_id="chat-1",
        enabled=True,
    ))
    store.upsert_subscription(DigestSubscription(
        id="disabled",
        user_id="alice",
        target_id="chat-2",
        enabled=False,
    ))

    assert [item.id for item in store.list_subscriptions()] == ["enabled"]
    assert {item.id for item in store.list_subscriptions(enabled_only=False)} == {"enabled", "disabled"}


def test_review_digest_store_reserves_delivery_idempotently():
    store = PostgresReviewDigestStore(POSTGRES_URL)
    subscription = DigestSubscription(
        id="sub-1",
        user_id="alice",
        target_id="chat-1",
    )

    first = store.reserve_delivery(subscription, "2026-06-16")
    second = store.reserve_delivery(subscription, "2026-06-16")

    assert first[0] is True
    assert second[0] is False
    assert first[1] == second[1]
    assert first[2] == second[2]


def test_review_digest_store_completes_delivery():
    store = PostgresReviewDigestStore(POSTGRES_URL)
    subscription = DigestSubscription(
        id="sub-1",
        user_id="alice",
        target_id="chat-1",
    )
    reserved, delivery_id, _key = store.reserve_delivery(subscription, "2026-06-16")
    assert reserved is True

    store.complete_delivery(delivery_id, status="sent", provider_message_id="msg-1")
    deliveries = store.list_deliveries()

    assert deliveries[0]["id"] == delivery_id
    assert deliveries[0]["status"] == "sent"
    assert deliveries[0]["provider_message_id"] == "msg-1"
    assert deliveries[0]["sent_at"] is not None


def test_review_digest_store_records_delivery_items_and_feedback():
    store = PostgresReviewDigestStore(POSTGRES_URL)
    subscription = DigestSubscription(
        id="sub-1",
        user_id="alice",
        target_id="chat-1",
    )
    reserved, delivery_id, _key = store.reserve_delivery(subscription, "2026-06-16")
    assert reserved is True
    card = ReviewCard(note_id="note-1", prompt="复习什么？", answer_hint="Digest")
    digest = ReviewDigest(user_id="alice", due_cards=[card])

    store.add_delivery_items(delivery_id, digest)
    store.complete_delivery(delivery_id, status="sent")

    items = store.list_delivery_items(delivery_id)
    assert items[0]["short_id"] == "R1"
    assert items[0]["review_card_id"] == card.id

    latest = store.find_latest_delivery_item(user_id="alice", target_id="chat-1", short_id="r1")
    assert latest is not None
    assert latest["delivery_id"] == delivery_id

    event_id = store.record_feedback_event(
        review_card_id=card.id,
        user_id="alice",
        delivery_id=delivery_id,
        outcome="remembered",
        source_channel="feishu",
        source_message_id="msg-1",
    )
    events = store.list_feedback_events(user_id="alice")
    assert events[0]["id"] == event_id
    assert events[0]["outcome"] == "remembered"

from __future__ import annotations

import pytest

from personal_agent.review import DigestSubscription
from personal_agent.storage.postgres_review_digest_store import PostgresReviewDigestStore
from tests.conftest import POSTGRES_URL


pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


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

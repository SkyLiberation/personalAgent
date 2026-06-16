from __future__ import annotations

from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..core.models import local_now
from ..review import DigestSubscription
from .postgres_common import PostgresStoreBase


class PostgresReviewDigestStore(PostgresStoreBase):
    """Persistent subscriptions and delivery ledger for Review Digest."""

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS digest_subscriptions (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        target_type TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        schedule_time TEXT NOT NULL,
                        timezone TEXT NOT NULL,
                        enabled BOOLEAN NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS digest_subscriptions_lookup_idx
                    ON digest_subscriptions (enabled, channel, user_id)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS digest_deliveries (
                        id TEXT PRIMARY KEY,
                        subscription_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        digest_date TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL,
                        provider_message_id TEXT,
                        error TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        sent_at TIMESTAMPTZ
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS digest_deliveries_lookup_idx
                    ON digest_deliveries (subscription_id, digest_date, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS digest_delivery_items (
                        id TEXT PRIMARY KEY,
                        delivery_id TEXT NOT NULL,
                        short_id TEXT NOT NULL,
                        review_card_id TEXT,
                        note_id TEXT,
                        prompt_snapshot TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS review_feedback_events (
                        id TEXT PRIMARY KEY,
                        review_card_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        delivery_id TEXT,
                        outcome TEXT NOT NULL,
                        source_channel TEXT NOT NULL,
                        source_message_id TEXT,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            conn.commit()
        self._initialized = True

    def upsert_subscription(self, subscription: DigestSubscription) -> DigestSubscription:
        self.ensure_schema()
        now = local_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO digest_subscriptions (
                        id, user_id, channel, target_type, target_id, schedule_time,
                        timezone, enabled, payload, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        channel = EXCLUDED.channel,
                        target_type = EXCLUDED.target_type,
                        target_id = EXCLUDED.target_id,
                        schedule_time = EXCLUDED.schedule_time,
                        timezone = EXCLUDED.timezone,
                        enabled = EXCLUDED.enabled,
                        payload = EXCLUDED.payload,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        subscription.id,
                        subscription.user_id,
                        subscription.channel,
                        subscription.target_type,
                        subscription.target_id,
                        subscription.schedule_time,
                        subscription.timezone,
                        subscription.enabled,
                        Jsonb(subscription.model_dump(mode="json")),
                        now,
                        now,
                    ),
                )
            conn.commit()
        return subscription

    def list_subscriptions(self, *, enabled_only: bool = True) -> list[DigestSubscription]:
        self.ensure_schema()
        where = "WHERE enabled = TRUE" if enabled_only else ""
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload
                    FROM digest_subscriptions
                    {where}
                    ORDER BY created_at ASC
                    """
                )
                rows = cur.fetchall()
        return [DigestSubscription.model_validate(row["payload"]) for row in rows]

    def get_subscription(self, subscription_id: str) -> DigestSubscription | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload
                    FROM digest_subscriptions
                    WHERE id = %s
                    """,
                    (subscription_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return DigestSubscription.model_validate(row["payload"])

    def reserve_delivery(self, subscription: DigestSubscription, digest_date: str) -> tuple[bool, str, str]:
        self.ensure_schema()
        delivery_id = uuid4().hex
        idempotency_key = f"digest:{subscription.id}:{digest_date}"
        now = local_now()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO digest_deliveries (
                        id, subscription_id, user_id, channel, target_id, digest_date,
                        idempotency_key, status, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING id
                    """,
                    (
                        delivery_id,
                        subscription.id,
                        subscription.user_id,
                        subscription.channel,
                        subscription.target_id,
                        digest_date,
                        idempotency_key,
                        now,
                    ),
                )
                inserted = cur.fetchone()
                if inserted:
                    conn.commit()
                    return True, str(inserted["id"]), idempotency_key
                cur.execute(
                    """
                    SELECT id
                    FROM digest_deliveries
                    WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                )
                existing = cur.fetchone()
            conn.commit()
        return False, str(existing["id"] if existing else ""), idempotency_key

    def complete_delivery(
        self,
        delivery_id: str,
        *,
        status: str,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        self.ensure_schema()
        sent_at = local_now() if status == "sent" else None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE digest_deliveries
                    SET status = %s,
                        provider_message_id = %s,
                        error = %s,
                        sent_at = %s
                    WHERE id = %s
                    """,
                    (status, provider_message_id, error, sent_at, delivery_id),
                )
            conn.commit()

    def list_deliveries(
        self,
        *,
        subscription_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        self.ensure_schema()
        clauses: list[str] = []
        params: list[object] = []
        if subscription_id:
            clauses.append("subscription_id = %s")
            params.append(subscription_id)
        if user_id:
            clauses.append("user_id = %s")
            params.append(user_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(limit, 200)))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM digest_deliveries
                    {where}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                return [dict(row) for row in cur.fetchall()]

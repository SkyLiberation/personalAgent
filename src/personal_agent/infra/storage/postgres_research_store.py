from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.kernel.contracts.research import (
    IntelligenceDigest,
    ResearchEvent,
    ResearchFeedback,
    ResearchRun,
    ResearchSource,
    ResearchSubscription,
    utc_now,
)
from personal_agent.infra.storage.postgres_common import PostgresStoreBase


class PostgresResearchStore(PostgresStoreBase):
    def __init__(self, postgres_url: str, *, worker_queue=None) -> None:
        super().__init__(postgres_url)
        self.worker_queue = worker_queue

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(773041)")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_subscriptions (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        enabled BOOLEAN NOT NULL,
                        next_lookup_at TIMESTAMPTZ,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS research_subscriptions_lookup_idx
                    ON research_subscriptions (enabled, user_id, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS research_runs (
                        id TEXT PRIMARY KEY,
                        subscription_id TEXT,
                        user_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        trigger_type TEXT NOT NULL,
                        window_start TIMESTAMPTZ NOT NULL,
                        window_end TIMESTAMPTZ NOT NULL,
                        digest_id TEXT,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        completed_at TIMESTAMPTZ,
                        UNIQUE (subscription_id, window_start, window_end)
                    );
                    CREATE INDEX IF NOT EXISTS research_runs_lookup_idx
                    ON research_runs (user_id, status, created_at DESC);

                    CREATE TABLE IF NOT EXISTS research_sources (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        canonical_url TEXT NOT NULL,
                        domain TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE (run_id, canonical_url)
                    );

                    CREATE TABLE IF NOT EXISTS research_events (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        canonical_key TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE (run_id, canonical_key)
                    );
                    CREATE INDEX IF NOT EXISTS research_events_recent_idx
                    ON research_events (user_id, canonical_key, created_at DESC);

                    CREATE TABLE IF NOT EXISTS intelligence_digests (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL UNIQUE,
                        user_id TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS research_deliveries (
                        id TEXT PRIMARY KEY,
                        digest_id TEXT NOT NULL,
                        subscription_id TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL,
                        provider_message_id TEXT,
                        error TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        sent_at TIMESTAMPTZ
                    );

                    CREATE TABLE IF NOT EXISTS research_feedback_events (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        subscription_id TEXT,
                        run_id TEXT NOT NULL,
                        event_id TEXT,
                        action TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS research_feedback_lookup_idx
                    ON research_feedback_events (user_id, subscription_id, created_at DESC);
                    """
                )
            conn.commit()
        self._initialized = True

    def upsert_subscription(self, subscription: ResearchSubscription) -> ResearchSubscription:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO research_subscriptions (
                        id, user_id, enabled, payload, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        enabled = EXCLUDED.enabled,
                        payload = EXCLUDED.payload,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        subscription.id,
                        subscription.user_id,
                        subscription.enabled,
                        Jsonb(subscription.model_dump(mode="json")),
                        subscription.created_at,
                        subscription.updated_at,
                    ),
                )
            conn.commit()
        return subscription

    def get_subscription(self, subscription_id: str | None) -> ResearchSubscription | None:
        if not subscription_id:
            return None
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM research_subscriptions WHERE id = %s", (subscription_id,))
                row = cur.fetchone()
        return ResearchSubscription.model_validate(row["payload"]) if row else None

    def list_subscriptions(
        self, *, user_id: str | None = None, enabled_only: bool = False
    ) -> list[ResearchSubscription]:
        self.ensure_schema()
        clauses: list[str] = []
        params: list[Any] = []
        if user_id:
            clauses.append("user_id = %s")
            params.append(user_id)
        if enabled_only:
            clauses.append("enabled = TRUE")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT payload FROM research_subscriptions {where} ORDER BY created_at",
                    params,
                )
                rows = cur.fetchall()
        return [ResearchSubscription.model_validate(row["payload"]) for row in rows]

    def delete_subscription(self, subscription_id: str, *, user_id: str) -> bool:
        subscription = self.get_subscription(subscription_id)
        if subscription is None or subscription.user_id != user_id:
            return False
        self.upsert_subscription(subscription.model_copy(update={"enabled": False, "updated_at": utc_now()}))
        return True

    def create_run(self, run: ResearchRun) -> ResearchRun:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO research_runs (
                        id, subscription_id, user_id, status, trigger_type,
                        window_start, window_end, digest_id, payload, created_at, completed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (subscription_id, window_start, window_end)
                    DO UPDATE SET payload = research_runs.payload
                    RETURNING payload
                    """,
                    (
                        run.id, run.subscription_id, run.user_id, run.status, run.trigger_type,
                        run.window_start, run.window_end, run.digest_id,
                        Jsonb(run.model_dump(mode="json")), run.created_at, run.completed_at,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return ResearchRun.model_validate(row["payload"])

    def update_run(self, run: ResearchRun) -> ResearchRun:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE research_runs SET
                        status = %s, digest_id = %s, payload = %s, completed_at = %s
                    WHERE id = %s
                    """,
                    (
                        run.status, run.digest_id, Jsonb(run.model_dump(mode="json")),
                        run.completed_at, run.id,
                    ),
                )
            conn.commit()
        return run

    def get_run(self, run_id: str) -> ResearchRun | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM research_runs WHERE id = %s", (run_id,))
                row = cur.fetchone()
        return ResearchRun.model_validate(row["payload"]) if row else None

    def list_runs(self, *, user_id: str, limit: int = 50) -> list[ResearchRun]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM research_runs
                    WHERE user_id = %s ORDER BY created_at DESC LIMIT %s
                    """,
                    (user_id, max(1, limit)),
                )
                rows = cur.fetchall()
        return [ResearchRun.model_validate(row["payload"]) for row in rows]

    def enqueue_run(self, run: ResearchRun) -> None:
        if self.worker_queue is None:
            raise RuntimeError("Research store has no worker queue.")
        self.worker_queue.enqueue(
            queue="research",
            task_type="research_run",
            payload={"run_id": run.id, "user_id": run.user_id},
            idempotency_key=f"research_run:{run.id}",
            max_attempts=3,
        )

    def enqueue_delivery(self, run: ResearchRun) -> None:
        if self.worker_queue is None:
            raise RuntimeError("Research store has no worker queue.")
        self.worker_queue.enqueue(
            queue="research",
            task_type="research_delivery",
            payload={"run_id": run.id, "user_id": run.user_id},
            idempotency_key=f"research_delivery:{run.id}",
            max_attempts=5,
        )

    def replace_run_sources(self, run_id: str, sources: list[ResearchSource]) -> None:
        self.ensure_schema()
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM research_sources WHERE run_id = %s", (run_id,))
                for source in sources:
                    cur.execute(
                        """
                        INSERT INTO research_sources
                        (id, run_id, canonical_url, domain, payload, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            source.id, run_id, source.canonical_url, source.domain,
                            Jsonb(source.model_dump(mode="json")), now,
                        ),
                    )
            conn.commit()

    def list_run_sources(self, run_id: str) -> list[ResearchSource]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload
                    FROM research_sources
                    WHERE run_id = %s
                    ORDER BY created_at ASC
                    """,
                    (run_id,),
                )
                rows = cur.fetchall()
        return [ResearchSource.model_validate(row["payload"]) for row in rows]

    def replace_run_events(self, run_id: str, events: list[ResearchEvent]) -> None:
        self.ensure_schema()
        run = self.get_run(run_id)
        if run is None:
            return
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM research_events WHERE run_id = %s", (run_id,))
                for event in events:
                    cur.execute(
                        """
                        INSERT INTO research_events
                        (id, run_id, user_id, canonical_key, payload, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            event.id, run_id, run.user_id, event.canonical_key,
                            Jsonb(event.model_dump(mode="json")), now,
                        ),
                    )
            conn.commit()

    def list_run_events(self, run_id: str) -> list[ResearchEvent]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload
                    FROM research_events
                    WHERE run_id = %s
                    ORDER BY created_at ASC
                    """,
                    (run_id,),
                )
                rows = cur.fetchall()
        return [ResearchEvent.model_validate(row["payload"]) for row in rows]

    def list_recent_event_keys(self, user_id: str, since: datetime) -> set[str]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT canonical_key FROM research_events
                    WHERE user_id = %s AND created_at < %s
                    """,
                    (user_id, since),
                )
                rows = cur.fetchall()
        return {str(row["canonical_key"]) for row in rows}

    def get_event(self, event_id: str, *, user_id: str) -> ResearchEvent | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM research_events WHERE id = %s AND user_id = %s",
                    (event_id, user_id),
                )
                row = cur.fetchone()
        return ResearchEvent.model_validate(row["payload"]) if row else None

    def save_digest(self, digest: IntelligenceDigest) -> IntelligenceDigest:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO intelligence_digests
                    (id, run_id, user_id, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE SET payload = EXCLUDED.payload
                    """,
                    (
                        digest.id, digest.run_id, digest.user_id,
                        Jsonb(digest.model_dump(mode="json")), digest.generated_at,
                    ),
                )
            conn.commit()
        return digest

    def get_digest(self, digest_id: str) -> IntelligenceDigest | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM intelligence_digests WHERE id = %s", (digest_id,))
                row = cur.fetchone()
        return IntelligenceDigest.model_validate(row["payload"]) if row else None

    def reserve_delivery(
        self, digest: IntelligenceDigest, subscription: ResearchSubscription
    ) -> tuple[bool, str]:
        self.ensure_schema()
        delivery_id = uuid4().hex
        key = f"research:{subscription.id}:{digest.run_id}:{subscription.delivery.target_id}"
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO research_deliveries (
                        id, digest_id, subscription_id, channel, target_id,
                        idempotency_key, status, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'sending', %s)
                    ON CONFLICT (idempotency_key) DO UPDATE SET
                        status = 'sending',
                        error = NULL
                    WHERE research_deliveries.status = 'failed'
                    RETURNING id
                    """,
                    (
                        delivery_id, digest.id, subscription.id,
                        subscription.delivery.channel, subscription.delivery.target_id,
                        key, utc_now(),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return (row is not None, str(row["id"]) if row else "")

    def complete_delivery(
        self,
        delivery_id: str,
        *,
        status: str,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE research_deliveries SET
                        status = %s, provider_message_id = %s, error = %s,
                        sent_at = CASE WHEN %s = 'sent' THEN %s ELSE sent_at END
                    WHERE id = %s
                    """,
                    (status, provider_message_id, error, status, utc_now(), delivery_id),
                )
            conn.commit()

    def add_feedback(self, feedback: ResearchFeedback) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO research_feedback_events (
                        id, user_id, subscription_id, run_id, event_id,
                        action, payload, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        feedback.id, feedback.user_id, feedback.subscription_id,
                        feedback.run_id, feedback.event_id, feedback.action,
                        Jsonb(feedback.model_dump(mode="json")), feedback.created_at,
                    ),
                )
            conn.commit()

    def find_latest_delivered_item(
        self, *, user_id: str, target_id: str, short_id: str
    ) -> tuple[IntelligenceDigest, ResearchRun, ResearchEvent] | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.payload AS digest_payload, r.payload AS run_payload
                    FROM research_deliveries rd
                    JOIN intelligence_digests d ON d.id = rd.digest_id
                    JOIN research_runs r ON r.id = d.run_id
                    WHERE d.user_id = %s
                      AND rd.target_id = %s
                      AND rd.status = 'sent'
                    ORDER BY rd.sent_at DESC NULLS LAST, rd.created_at DESC
                    LIMIT 20
                    """,
                    (user_id, target_id),
                )
                rows = cur.fetchall()
        normalized = short_id.strip().upper()
        for row in rows:
            digest = IntelligenceDigest.model_validate(row["digest_payload"])
            item = next(
                (candidate for candidate in digest.items if candidate.short_id.upper() == normalized),
                None,
            )
            if item is None:
                continue
            run = ResearchRun.model_validate(row["run_payload"])
            event = self.get_event(item.event_id, user_id=user_id)
            if event is not None:
                return digest, run, event
        return None

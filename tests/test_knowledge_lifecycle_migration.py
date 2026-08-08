from __future__ import annotations

from datetime import datetime, timezone

import psycopg
import pytest
from psycopg.types.json import Jsonb

from personal_agent.infra.storage.postgres_knowledge_lifecycle_store import (
    PostgresKnowledgeLifecycleStore,
)
from tests.conftest import POSTGRES_URL

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


def test_legacy_six_tables_migrate_to_two_without_changing_receipt() -> None:
    created_at = datetime.now(timezone.utc)
    command_payload = {
        "command_id": "legacy-delete-command",
        "idempotency_key": "legacy-delete-key",
        "owner_id": "alice",
        "user_id": "alice",
        "target_note_id": "legacy-note",
        "reason": "legacy cleanup",
        "policy_revision": "knowledge-delete-v1",
        "authorization_digest": "a" * 64,
        "execution_command_digest": "e" * 64,
        "created_at": created_at.isoformat(),
    }
    receipt_payload = {
        "receipt_id": "legacy-delete-receipt",
        "command_id": "legacy-delete-command",
        "execution_command_digest": "e" * 64,
        "confirmation_ref": "legacy-confirmation",
        "deleted_note_id": "legacy-note",
        "affected_claim_ids": [],
        "state_event_ids": [],
        "previous_item_state": "active",
        "previous_claim_states": {},
        "executed_at": created_at.isoformat(),
    }
    with psycopg.connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE knowledge_delete_commands (
                    command_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    target_note_id TEXT NOT NULL,
                    authorization_digest TEXT NOT NULL,
                    execution_command_digest TEXT NOT NULL UNIQUE,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    UNIQUE (user_id, idempotency_key)
                );
                CREATE TABLE knowledge_delete_events (
                    event_id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    UNIQUE (command_id, event_type)
                );
                CREATE TABLE knowledge_delete_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL UNIQUE,
                    execution_command_digest TEXT NOT NULL UNIQUE,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE knowledge_restore_commands (
                    command_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    delete_command_id TEXT NOT NULL,
                    authorization_digest TEXT NOT NULL,
                    execution_command_digest TEXT NOT NULL UNIQUE,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    UNIQUE (user_id, idempotency_key)
                );
                CREATE TABLE knowledge_restore_events (
                    event_id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    UNIQUE (command_id, event_type)
                );
                CREATE TABLE knowledge_restore_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL UNIQUE,
                    execution_command_digest TEXT NOT NULL UNIQUE,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cur.execute(
                """
                INSERT INTO knowledge_delete_commands (
                    command_id, idempotency_key, owner_id, user_id,
                    target_note_id, authorization_digest,
                    execution_command_digest, payload, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    "legacy-delete-command",
                    "legacy-delete-key",
                    "alice",
                    "alice",
                    "legacy-note",
                    "a" * 64,
                    "e" * 64,
                    Jsonb(command_payload),
                    created_at,
                ),
            )
            cur.execute(
                """
                INSERT INTO knowledge_delete_receipts (
                    receipt_id, command_id, execution_command_digest,
                    payload, created_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    "legacy-delete-receipt",
                    "legacy-delete-command",
                    "e" * 64,
                    Jsonb(receipt_payload),
                    created_at,
                ),
            )

    store = PostgresKnowledgeLifecycleStore(POSTGRES_URL)
    store.ensure_schema()
    migrated = store.get_delete("legacy-delete-command", user_id="alice")

    assert migrated is not None
    assert migrated.status == "executed"
    assert migrated.command.command_digest == "e" * 64
    assert migrated.receipt is not None
    assert migrated.receipt.receipt_id == "legacy-delete-receipt"
    assert migrated.receipt.command_digest == "e" * 64

    with psycopg.connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            for table in (
                "knowledge_delete_commands",
                "knowledge_delete_events",
                "knowledge_delete_receipts",
                "knowledge_restore_commands",
                "knowledge_restore_events",
                "knowledge_restore_receipts",
            ):
                cur.execute("SELECT to_regclass(%s)", (table,))
                assert cur.fetchone()[0] is None

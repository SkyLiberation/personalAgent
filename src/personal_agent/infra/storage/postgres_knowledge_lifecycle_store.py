from __future__ import annotations

from hashlib import sha256
from typing import Literal

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.application.knowledge_lifecycle import (
    KnowledgeDeleteCommand,
    KnowledgeDeleteConflict,
    KnowledgeDeleteEvent,
    KnowledgeDeleteNotFound,
    KnowledgeDeleteOperationView,
    KnowledgeDeleteReceipt,
    KnowledgeRestoreCommand,
    KnowledgeRestoreEvent,
    KnowledgeRestoreOperationView,
    KnowledgeRestoreReceipt,
)
from personal_agent.application.workspace.models import Claim, KnowledgeItem, KnowledgeStateEvent
from personal_agent.infra.storage.postgres_common import PostgresStoreBase
from personal_agent.kernel.models import local_now


class PostgresKnowledgeLifecycleStore(PostgresStoreBase):
    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS knowledge_delete_commands (
                        command_id TEXT PRIMARY KEY,
                        idempotency_key TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        target_note_id TEXT NOT NULL,
                        authorization_digest TEXT NOT NULL,
                        execution_command_digest TEXT NOT NULL UNIQUE,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE (user_id, idempotency_key)
                    );
                    CREATE TABLE IF NOT EXISTS knowledge_delete_events (
                        event_id TEXT PRIMARY KEY,
                        command_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE (command_id, event_type)
                    );
                    CREATE TABLE IF NOT EXISTS knowledge_delete_receipts (
                        receipt_id TEXT PRIMARY KEY,
                        command_id TEXT NOT NULL UNIQUE,
                        execution_command_digest TEXT NOT NULL UNIQUE,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS knowledge_restore_commands (
                        command_id TEXT PRIMARY KEY,
                        idempotency_key TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        delete_command_id TEXT NOT NULL,
                        authorization_digest TEXT NOT NULL,
                        execution_command_digest TEXT NOT NULL UNIQUE,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE (user_id, idempotency_key)
                    );
                    CREATE TABLE IF NOT EXISTS knowledge_restore_events (
                        event_id TEXT PRIMARY KEY,
                        command_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE (command_id, event_type)
                    );
                    CREATE TABLE IF NOT EXISTS knowledge_restore_receipts (
                        receipt_id TEXT PRIMARY KEY,
                        command_id TEXT NOT NULL UNIQUE,
                        execution_command_digest TEXT NOT NULL UNIQUE,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    """
                )
            conn.commit()
        self._initialized = True

    def prepare_delete(
        self,
        command: KnowledgeDeleteCommand,
    ) -> KnowledgeDeleteOperationView:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload, state FROM workspace_knowledge_items
                    WHERE knowledge_item_id = %s AND workspace_id = %s AND user_id = %s
                    FOR SHARE
                    """,
                    (command.target_note_id, command.workspace_id, command.user_id),
                )
                target = cur.fetchone()
                if target is None:
                    raise KnowledgeDeleteNotFound("knowledge item not found in caller scope")
                if target["state"] == "deleted":
                    raise KnowledgeDeleteConflict("knowledge item is already deleted")

                cur.execute(
                    """
                    INSERT INTO knowledge_delete_commands (
                        command_id, idempotency_key, workspace_id, user_id,
                        target_note_id, authorization_digest,
                        execution_command_digest, payload, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        command.command_id,
                        command.idempotency_key,
                        command.workspace_id,
                        command.user_id,
                        command.target_note_id,
                        command.authorization_digest,
                        command.execution_command_digest,
                        Jsonb(command.model_dump(mode="json")),
                        command.created_at,
                    ),
                )
                cur.execute(
                    """
                    SELECT payload FROM knowledge_delete_commands
                    WHERE user_id = %s AND idempotency_key = %s
                    FOR UPDATE
                    """,
                    (command.user_id, command.idempotency_key),
                )
                row = cur.fetchone()
                if row is None:
                    raise KnowledgeDeleteConflict("delete command could not be persisted")
                persisted = KnowledgeDeleteCommand.model_validate(row["payload"])
                if not _same_command(persisted, command):
                    raise KnowledgeDeleteConflict(
                        "idempotency key is already bound to a different immutable command"
                    )
                self._insert_event(cur, KnowledgeDeleteEvent(
                    event_id=_stable_id("kdev", persisted.command_id, "prepared"),
                    command_id=persisted.command_id,
                    event_type="prepared",
                    actor_user_id=persisted.user_id,
                ))
                view = self._delete_view(cur, persisted)
            conn.commit()
        return view

    def decide_delete(
        self,
        *,
        command_id: str,
        user_id: str,
        decision: Literal["confirm", "reject"],
        authorization_digest: str,
        execution_command_digest: str,
        confirmation_ref: str,
    ) -> KnowledgeDeleteOperationView:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                command = self._locked_delete_command(cur, command_id, user_id=user_id)
                if command is None:
                    raise KnowledgeDeleteNotFound("delete command not found in caller scope")
                if command.authorization_digest != authorization_digest:
                    raise KnowledgeDeleteConflict("authorization digest does not match command")
                if command.execution_command_digest != execution_command_digest:
                    raise KnowledgeDeleteConflict("execution command digest does not match command")

                current = self._delete_view(cur, command)
                if current.status == "executed":
                    return current
                if current.status == "rejected":
                    if decision == "reject":
                        return current
                    raise KnowledgeDeleteConflict("rejected command cannot be executed")
                if decision == "reject":
                    self._insert_event(cur, KnowledgeDeleteEvent(
                        event_id=_stable_id("kdev", command.command_id, "rejected"),
                        command_id=command.command_id,
                        event_type="rejected",
                        actor_user_id=user_id,
                    ))
                    view = self._delete_view(cur, command)
                    conn.commit()
                    return view

                cur.execute(
                    """
                    SELECT payload FROM workspace_knowledge_items
                    WHERE knowledge_item_id = %s AND workspace_id = %s AND user_id = %s
                    FOR UPDATE
                    """,
                    (command.target_note_id, command.workspace_id, command.user_id),
                )
                item_row = cur.fetchone()
                if item_row is None:
                    raise KnowledgeDeleteNotFound("knowledge item not found in command scope")
                item = KnowledgeItem.model_validate(item_row["payload"])
                if item.state == "deleted":
                    raise KnowledgeDeleteConflict(
                        "knowledge item is deleted without this command receipt"
                    )

                executed_at = local_now()
                previous_item_state = item.state
                item = item.model_copy(update={"state": "deleted", "updated_at": executed_at})
                cur.execute(
                    """
                    UPDATE workspace_knowledge_items
                    SET state = %s, payload = %s, updated_at = %s
                    WHERE knowledge_item_id = %s
                    """,
                    (item.state, Jsonb(item.model_dump(mode="json")), item.updated_at, item.knowledge_item_id),
                )

                affected_claim_ids: list[str] = []
                previous_claim_states: dict[str, str] = {}
                state_event_ids: list[str] = []
                targets: list[tuple[str, str, str, tuple[str, ...]]] = [
                    (
                        "knowledge_item",
                        item.knowledge_item_id,
                        previous_item_state,
                        tuple(item.evidence_span_ids),
                    )
                ]
                for claim_id in item.claim_ids:
                    cur.execute(
                        """
                        SELECT payload FROM workspace_claims
                        WHERE claim_id = %s AND workspace_id = %s AND user_id = %s
                        FOR UPDATE
                        """,
                        (claim_id, command.workspace_id, command.user_id),
                    )
                    claim_row = cur.fetchone()
                    if claim_row is None:
                        continue
                    claim = Claim.model_validate(claim_row["payload"])
                    previous_claim_states[claim.claim_id] = claim.state
                    claim = claim.model_copy(update={"state": "deleted", "updated_at": executed_at})
                    cur.execute(
                        """
                        UPDATE workspace_claims
                        SET state = %s, payload = %s, updated_at = %s
                        WHERE claim_id = %s
                        """,
                        (claim.state, Jsonb(claim.model_dump(mode="json")), claim.updated_at, claim.claim_id),
                    )
                    affected_claim_ids.append(claim.claim_id)
                    targets.append((
                        "claim",
                        claim.claim_id,
                        previous_claim_states[claim.claim_id],
                        tuple(claim.evidence_span_ids),
                    ))

                for target_type, target_id, previous_state, evidence_span_ids in targets:
                    state_event = KnowledgeStateEvent(
                        event_id=_stable_id("ksev", command.command_id, target_id),
                        workspace_id=command.workspace_id,
                        target_type=target_type,
                        target_id=target_id,
                        from_state=previous_state,
                        to_state="deleted",
                        reason=command.reason or "confirmed knowledge deletion",
                        actor="user",
                        evidence_span_ids=list(evidence_span_ids),
                        policy_result="confirmed_delete_command",
                    )
                    cur.execute(
                        """
                        INSERT INTO workspace_knowledge_state_events
                            (event_id, target_id, workspace_id, to_state, payload, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (event_id) DO NOTHING
                        """,
                        (
                            state_event.event_id,
                            state_event.target_id,
                            state_event.workspace_id,
                            state_event.to_state,
                            Jsonb(state_event.model_dump(mode="json")),
                            state_event.created_at,
                        ),
                    )
                    state_event_ids.append(state_event.event_id)

                self._insert_event(cur, KnowledgeDeleteEvent(
                    event_id=_stable_id("kdev", command.command_id, "confirmed"),
                    command_id=command.command_id,
                    event_type="confirmed",
                    actor_user_id=user_id,
                    confirmation_ref=confirmation_ref,
                ))
                receipt = KnowledgeDeleteReceipt(
                    receipt_id=_stable_id("krec", command.execution_command_digest),
                    command_id=command.command_id,
                    execution_command_digest=command.execution_command_digest,
                    confirmation_ref=confirmation_ref,
                    deleted_note_id=command.target_note_id,
                    affected_claim_ids=tuple(affected_claim_ids),
                    state_event_ids=tuple(state_event_ids),
                    previous_item_state=previous_item_state,
                    previous_claim_states=previous_claim_states,
                    executed_at=executed_at,
                )
                cur.execute(
                    """
                    INSERT INTO knowledge_delete_receipts
                        (receipt_id, command_id, execution_command_digest, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (command_id) DO NOTHING
                    """,
                    (
                        receipt.receipt_id,
                        receipt.command_id,
                        receipt.execution_command_digest,
                        Jsonb(receipt.model_dump(mode="json")),
                        receipt.executed_at,
                    ),
                )
                self._insert_event(cur, KnowledgeDeleteEvent(
                    event_id=_stable_id("kdev", command.command_id, "executed"),
                    command_id=command.command_id,
                    event_type="executed",
                    actor_user_id=user_id,
                    confirmation_ref=confirmation_ref,
                ))
                view = self._delete_view(cur, command)
            conn.commit()
        return view

    def get_delete(
        self,
        command_id: str,
        *,
        user_id: str,
    ) -> KnowledgeDeleteOperationView | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                command = self._locked_delete_command(cur, command_id, user_id=user_id, lock=False)
                return self._delete_view(cur, command) if command is not None else None

    def prepare_restore(
        self,
        command: KnowledgeRestoreCommand,
    ) -> KnowledgeRestoreOperationView:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                delete_command = self._locked_delete_command(
                    cur,
                    command.delete_command_id,
                    user_id=command.user_id,
                )
                if delete_command is None or delete_command.workspace_id != command.workspace_id:
                    raise KnowledgeDeleteNotFound("delete command not found in caller scope")
                cur.execute(
                    "SELECT payload FROM knowledge_delete_receipts WHERE command_id = %s",
                    (delete_command.command_id,),
                )
                if cur.fetchone() is None:
                    raise KnowledgeDeleteConflict("only an executed delete command can be restored")
                cur.execute(
                    """
                    SELECT state FROM workspace_knowledge_items
                    WHERE knowledge_item_id = %s AND workspace_id = %s AND user_id = %s
                    FOR SHARE
                    """,
                    (
                        delete_command.target_note_id,
                        command.workspace_id,
                        command.user_id,
                    ),
                )
                target = cur.fetchone()
                if target is None:
                    raise KnowledgeDeleteNotFound("knowledge item not found in caller scope")
                if target["state"] != "deleted":
                    raise KnowledgeDeleteConflict("knowledge item is not deleted")

                cur.execute(
                    """
                    INSERT INTO knowledge_restore_commands (
                        command_id, idempotency_key, workspace_id, user_id,
                        delete_command_id, authorization_digest,
                        execution_command_digest, payload, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        command.command_id,
                        command.idempotency_key,
                        command.workspace_id,
                        command.user_id,
                        command.delete_command_id,
                        command.authorization_digest,
                        command.execution_command_digest,
                        Jsonb(command.model_dump(mode="json")),
                        command.created_at,
                    ),
                )
                cur.execute(
                    """
                    SELECT payload FROM knowledge_restore_commands
                    WHERE user_id = %s AND idempotency_key = %s
                    FOR UPDATE
                    """,
                    (command.user_id, command.idempotency_key),
                )
                row = cur.fetchone()
                if row is None:
                    raise KnowledgeDeleteConflict("restore command could not be persisted")
                persisted = KnowledgeRestoreCommand.model_validate(row["payload"])
                if not _same_command(persisted, command):
                    raise KnowledgeDeleteConflict(
                        "idempotency key is already bound to a different immutable command"
                    )
                self._insert_restore_event(cur, KnowledgeRestoreEvent(
                    event_id=_stable_id("krev", persisted.command_id, "prepared"),
                    command_id=persisted.command_id,
                    event_type="prepared",
                    actor_user_id=persisted.user_id,
                ))
                view = self._restore_view(cur, persisted)
            conn.commit()
        return view

    def decide_restore(
        self,
        *,
        command_id: str,
        user_id: str,
        decision: Literal["confirm", "reject"],
        authorization_digest: str,
        execution_command_digest: str,
        confirmation_ref: str,
    ) -> KnowledgeRestoreOperationView:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                command = self._locked_restore_command(cur, command_id, user_id=user_id)
                if command is None:
                    raise KnowledgeDeleteNotFound("restore command not found in caller scope")
                if command.authorization_digest != authorization_digest:
                    raise KnowledgeDeleteConflict("authorization digest does not match command")
                if command.execution_command_digest != execution_command_digest:
                    raise KnowledgeDeleteConflict("execution command digest does not match command")

                current = self._restore_view(cur, command)
                if current.status == "executed":
                    return current
                if current.status == "rejected":
                    if decision == "reject":
                        return current
                    raise KnowledgeDeleteConflict("rejected command cannot be executed")
                if decision == "reject":
                    self._insert_restore_event(cur, KnowledgeRestoreEvent(
                        event_id=_stable_id("krev", command.command_id, "rejected"),
                        command_id=command.command_id,
                        event_type="rejected",
                        actor_user_id=user_id,
                    ))
                    view = self._restore_view(cur, command)
                    conn.commit()
                    return view

                delete_command = self._locked_delete_command(
                    cur,
                    command.delete_command_id,
                    user_id=user_id,
                )
                if delete_command is None or delete_command.workspace_id != command.workspace_id:
                    raise KnowledgeDeleteNotFound("delete command not found in restore scope")
                cur.execute(
                    "SELECT payload FROM knowledge_delete_receipts WHERE command_id = %s FOR UPDATE",
                    (delete_command.command_id,),
                )
                delete_receipt_row = cur.fetchone()
                if delete_receipt_row is None:
                    raise KnowledgeDeleteConflict("delete receipt is required for restore")
                delete_receipt = KnowledgeDeleteReceipt.model_validate(delete_receipt_row["payload"])

                cur.execute(
                    """
                    SELECT payload FROM workspace_knowledge_items
                    WHERE knowledge_item_id = %s AND workspace_id = %s AND user_id = %s
                    FOR UPDATE
                    """,
                    (
                        delete_receipt.deleted_note_id,
                        command.workspace_id,
                        command.user_id,
                    ),
                )
                item_row = cur.fetchone()
                if item_row is None:
                    raise KnowledgeDeleteNotFound("knowledge item not found in restore scope")
                item = KnowledgeItem.model_validate(item_row["payload"])
                if item.state != "deleted":
                    raise KnowledgeDeleteConflict("knowledge item state changed after deletion")

                restored_at = local_now()
                previous_item_state = item.state
                item = item.model_copy(update={
                    "state": delete_receipt.previous_item_state,
                    "updated_at": restored_at,
                })
                cur.execute(
                    """
                    UPDATE workspace_knowledge_items
                    SET state = %s, payload = %s, updated_at = %s
                    WHERE knowledge_item_id = %s
                    """,
                    (
                        item.state,
                        Jsonb(item.model_dump(mode="json")),
                        item.updated_at,
                        item.knowledge_item_id,
                    ),
                )

                restored_claim_ids: list[str] = []
                state_event_ids: list[str] = []
                targets: list[tuple[str, str, str, str, tuple[str, ...]]] = [(
                    "knowledge_item",
                    item.knowledge_item_id,
                    previous_item_state,
                    delete_receipt.previous_item_state,
                    tuple(item.evidence_span_ids),
                )]
                for claim_id in delete_receipt.affected_claim_ids:
                    cur.execute(
                        """
                        SELECT payload FROM workspace_claims
                        WHERE claim_id = %s AND workspace_id = %s AND user_id = %s
                        FOR UPDATE
                        """,
                        (claim_id, command.workspace_id, command.user_id),
                    )
                    claim_row = cur.fetchone()
                    if claim_row is None:
                        raise KnowledgeDeleteConflict("deleted claim is missing during restore")
                    claim = Claim.model_validate(claim_row["payload"])
                    if claim.state != "deleted":
                        raise KnowledgeDeleteConflict("claim state changed after deletion")
                    restored_state = delete_receipt.previous_claim_states.get(claim.claim_id)
                    if not restored_state:
                        raise KnowledgeDeleteConflict("delete receipt lacks the previous claim state")
                    claim = claim.model_copy(update={"state": restored_state, "updated_at": restored_at})
                    cur.execute(
                        """
                        UPDATE workspace_claims
                        SET state = %s, payload = %s, updated_at = %s
                        WHERE claim_id = %s
                        """,
                        (
                            claim.state,
                            Jsonb(claim.model_dump(mode="json")),
                            claim.updated_at,
                            claim.claim_id,
                        ),
                    )
                    restored_claim_ids.append(claim.claim_id)
                    targets.append((
                        "claim",
                        claim.claim_id,
                        "deleted",
                        restored_state,
                        tuple(claim.evidence_span_ids),
                    ))

                for target_type, target_id, from_state, to_state, evidence_span_ids in targets:
                    state_event = KnowledgeStateEvent(
                        event_id=_stable_id("ksev", command.command_id, target_id),
                        workspace_id=command.workspace_id,
                        target_type=target_type,
                        target_id=target_id,
                        from_state=from_state,
                        to_state=to_state,
                        reason=command.reason or "confirmed knowledge restoration",
                        actor="user",
                        evidence_span_ids=list(evidence_span_ids),
                        policy_result="confirmed_restore_command",
                    )
                    cur.execute(
                        """
                        INSERT INTO workspace_knowledge_state_events
                            (event_id, target_id, workspace_id, to_state, payload, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (event_id) DO NOTHING
                        """,
                        (
                            state_event.event_id,
                            state_event.target_id,
                            state_event.workspace_id,
                            state_event.to_state,
                            Jsonb(state_event.model_dump(mode="json")),
                            state_event.created_at,
                        ),
                    )
                    state_event_ids.append(state_event.event_id)

                self._insert_restore_event(cur, KnowledgeRestoreEvent(
                    event_id=_stable_id("krev", command.command_id, "confirmed"),
                    command_id=command.command_id,
                    event_type="confirmed",
                    actor_user_id=user_id,
                    confirmation_ref=confirmation_ref,
                ))
                receipt = KnowledgeRestoreReceipt(
                    receipt_id=_stable_id("krer", command.execution_command_digest),
                    command_id=command.command_id,
                    execution_command_digest=command.execution_command_digest,
                    confirmation_ref=confirmation_ref,
                    restored_note_id=item.knowledge_item_id,
                    affected_claim_ids=tuple(restored_claim_ids),
                    state_event_ids=tuple(state_event_ids),
                    restored_at=restored_at,
                )
                cur.execute(
                    """
                    INSERT INTO knowledge_restore_receipts
                        (receipt_id, command_id, execution_command_digest, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (command_id) DO NOTHING
                    """,
                    (
                        receipt.receipt_id,
                        receipt.command_id,
                        receipt.execution_command_digest,
                        Jsonb(receipt.model_dump(mode="json")),
                        receipt.restored_at,
                    ),
                )
                self._insert_restore_event(cur, KnowledgeRestoreEvent(
                    event_id=_stable_id("krev", command.command_id, "executed"),
                    command_id=command.command_id,
                    event_type="executed",
                    actor_user_id=user_id,
                    confirmation_ref=confirmation_ref,
                ))
                view = self._restore_view(cur, command)
            conn.commit()
        return view

    def get_restore(
        self,
        command_id: str,
        *,
        user_id: str,
    ) -> KnowledgeRestoreOperationView | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                command = self._locked_restore_command(
                    cur,
                    command_id,
                    user_id=user_id,
                    lock=False,
                )
                return self._restore_view(cur, command) if command is not None else None

    @staticmethod
    def _insert_event(cur, event: KnowledgeDeleteEvent) -> None:
        cur.execute(
            """
            INSERT INTO knowledge_delete_events
                (event_id, command_id, event_type, payload, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (command_id, event_type) DO NOTHING
            """,
            (
                event.event_id,
                event.command_id,
                event.event_type,
                Jsonb(event.model_dump(mode="json")),
                event.created_at,
            ),
        )

    @staticmethod
    def _locked_delete_command(cur, command_id: str, *, user_id: str, lock: bool = True):
        suffix = " FOR UPDATE" if lock else ""
        cur.execute(
            "SELECT payload FROM knowledge_delete_commands "
            "WHERE command_id = %s AND user_id = %s" + suffix,
            (command_id, user_id),
        )
        row = cur.fetchone()
        return KnowledgeDeleteCommand.model_validate(row["payload"]) if row else None

    @staticmethod
    def _delete_view(cur, command: KnowledgeDeleteCommand) -> KnowledgeDeleteOperationView:
        cur.execute(
            """
            SELECT payload FROM knowledge_delete_events
            WHERE command_id = %s ORDER BY created_at, event_id
            """,
            (command.command_id,),
        )
        events = tuple(
            KnowledgeDeleteEvent.model_validate(row["payload"])
            for row in cur.fetchall()
        )
        cur.execute(
            "SELECT payload FROM knowledge_delete_receipts WHERE command_id = %s",
            (command.command_id,),
        )
        receipt_row = cur.fetchone()
        receipt = (
            KnowledgeDeleteReceipt.model_validate(receipt_row["payload"])
            if receipt_row else None
        )
        event_types = {event.event_type for event in events}
        status = "executed" if receipt else "rejected" if "rejected" in event_types else "awaiting_confirmation"
        return KnowledgeDeleteOperationView(
            command=command,
            status=status,
            events=events,
            receipt=receipt,
        )

    @staticmethod
    def _insert_restore_event(cur, event: KnowledgeRestoreEvent) -> None:
        cur.execute(
            """
            INSERT INTO knowledge_restore_events
                (event_id, command_id, event_type, payload, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (command_id, event_type) DO NOTHING
            """,
            (
                event.event_id,
                event.command_id,
                event.event_type,
                Jsonb(event.model_dump(mode="json")),
                event.created_at,
            ),
        )

    @staticmethod
    def _locked_restore_command(cur, command_id: str, *, user_id: str, lock: bool = True):
        suffix = " FOR UPDATE" if lock else ""
        cur.execute(
            "SELECT payload FROM knowledge_restore_commands "
            "WHERE command_id = %s AND user_id = %s" + suffix,
            (command_id, user_id),
        )
        row = cur.fetchone()
        return KnowledgeRestoreCommand.model_validate(row["payload"]) if row else None

    @staticmethod
    def _restore_view(cur, command: KnowledgeRestoreCommand) -> KnowledgeRestoreOperationView:
        cur.execute(
            """
            SELECT payload FROM knowledge_restore_events
            WHERE command_id = %s ORDER BY created_at, event_id
            """,
            (command.command_id,),
        )
        events = tuple(
            KnowledgeRestoreEvent.model_validate(row["payload"])
            for row in cur.fetchall()
        )
        cur.execute(
            "SELECT payload FROM knowledge_restore_receipts WHERE command_id = %s",
            (command.command_id,),
        )
        receipt_row = cur.fetchone()
        receipt = (
            KnowledgeRestoreReceipt.model_validate(receipt_row["payload"])
            if receipt_row else None
        )
        event_types = {event.event_type for event in events}
        status = "executed" if receipt else "rejected" if "rejected" in event_types else "awaiting_confirmation"
        return KnowledgeRestoreOperationView(
            command=command,
            status=status,
            events=events,
            receipt=receipt,
        )


def _stable_id(prefix: str, *parts: str) -> str:
    value = ":".join(parts)
    return f"{prefix}_{sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _same_command(left: KnowledgeDeleteCommand, right: KnowledgeDeleteCommand) -> bool:
    excluded = {"created_at"}
    return left.model_dump(exclude=excluded) == right.model_dump(exclude=excluded)


__all__ = ["PostgresKnowledgeLifecycleStore"]

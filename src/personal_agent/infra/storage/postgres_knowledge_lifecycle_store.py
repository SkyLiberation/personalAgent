from __future__ import annotations

from hashlib import sha256
from typing import Literal

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.application.knowledge_lifecycle import (
    KnowledgeDeleteCommand,
    KnowledgeDeleteConflict,
    KnowledgeDeleteNotFound,
    KnowledgeDeleteOperationView,
    KnowledgeDeleteReceipt,
    KnowledgeRestoreCommand,
    KnowledgeRestoreOperationView,
    KnowledgeRestoreReceipt,
)
from personal_agent.application.knowledge.models import (
    Claim,
    KnowledgeItem,
    KnowledgeStateEvent,
)
from personal_agent.infra.storage.postgres_common import PostgresStoreBase
from personal_agent.kernel.models import local_now

_Status = Literal["awaiting_confirmation", "rejected", "executed"]


class PostgresKnowledgeLifecycleStore(PostgresStoreBase):
    """Durable owner of pending knowledge operations and execution receipts."""

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS personal_knowledge_lifecycle_operations (
                        command_id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL CHECK (kind IN ('delete', 'restore')),
                        idempotency_key TEXT NOT NULL,
                        owner_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        target_ref TEXT NOT NULL,
                        command_digest TEXT NOT NULL UNIQUE,
                        payload JSONB NOT NULL,
                        status TEXT NOT NULL
                            CHECK (status IN ('awaiting_confirmation', 'rejected', 'executed')),
                        confirmation_ref TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL,
                        decided_at TIMESTAMPTZ,
                        UNIQUE (user_id, kind, idempotency_key)
                    );
                    CREATE INDEX IF NOT EXISTS knowledge_lifecycle_target_idx
                    ON personal_knowledge_lifecycle_operations
                        (owner_id, user_id, kind, target_ref, created_at DESC);

                    CREATE TABLE IF NOT EXISTS personal_knowledge_lifecycle_receipts (
                        receipt_id TEXT PRIMARY KEY,
                        command_id TEXT NOT NULL UNIQUE,
                        kind TEXT NOT NULL CHECK (kind IN ('delete', 'restore')),
                        command_digest TEXT NOT NULL UNIQUE,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    """
                )
                self._migrate_legacy_tables(cur)
            conn.commit()
        self._initialized = True

    def prepare_delete(
        self,
        command: KnowledgeDeleteCommand,
    ) -> KnowledgeDeleteOperationView:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                existing = self._operation_by_idempotency(
                    cur,
                    kind="delete",
                    user_id=command.user_id,
                    idempotency_key=command.idempotency_key,
                )
                if existing is not None:
                    persisted = KnowledgeDeleteCommand.model_validate(existing["payload"])
                    self._require_same_command(persisted, command)
                    return self._delete_view(cur, existing, persisted)

                cur.execute(
                    """
                    SELECT state FROM knowledge_items
                    WHERE knowledge_item_id = %s AND owner_id = %s AND user_id = %s
                    FOR SHARE
                    """,
                    (command.target_note_id, command.owner_id, command.user_id),
                )
                target = cur.fetchone()
                if target is None:
                    raise KnowledgeDeleteNotFound(
                        "knowledge item not found in caller scope"
                    )
                if target["state"] == "deleted":
                    raise KnowledgeDeleteConflict("knowledge item is already deleted")

                self._insert_operation(
                    cur,
                    kind="delete",
                    target_ref=command.target_note_id,
                    command=command,
                )
                row = self._operation_by_idempotency(
                    cur,
                    kind="delete",
                    user_id=command.user_id,
                    idempotency_key=command.idempotency_key,
                )
                if row is None:
                    raise KnowledgeDeleteConflict(
                        "delete command could not be persisted"
                    )
                persisted = KnowledgeDeleteCommand.model_validate(row["payload"])
                self._require_same_command(persisted, command)
                view = self._delete_view(cur, row, persisted)
            conn.commit()
        return view

    def decide_delete(
        self,
        *,
        command_id: str,
        user_id: str,
        decision: Literal["confirm", "reject"],
        confirmation_ref: str,
    ) -> KnowledgeDeleteOperationView:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                row = self._locked_operation(
                    cur, command_id, kind="delete", user_id=user_id
                )
                if row is None:
                    raise KnowledgeDeleteNotFound(
                        "delete command not found in caller scope"
                    )
                command = KnowledgeDeleteCommand.model_validate(row["payload"])

                terminal = self._terminal_delete_view(cur, row, command, decision)
                if terminal is not None:
                    return terminal
                if decision == "reject":
                    self._reject_operation(cur, command.command_id)
                    view = self._delete_view(
                        cur,
                        self._locked_operation(
                            cur,
                            command.command_id,
                            kind="delete",
                            user_id=user_id,
                        ),
                        command,
                    )
                    conn.commit()
                    return view

                receipt = self._execute_delete(cur, command, confirmation_ref)
                self._record_receipt(cur, "delete", receipt)
                self._complete_operation(
                    cur, command.command_id, confirmation_ref, receipt.executed_at
                )
                row = self._locked_operation(
                    cur, command.command_id, kind="delete", user_id=user_id
                )
                view = self._delete_view(cur, row, command)
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
                row = self._locked_operation(
                    cur,
                    command_id,
                    kind="delete",
                    user_id=user_id,
                    lock=False,
                )
                if row is None:
                    return None
                command = KnowledgeDeleteCommand.model_validate(row["payload"])
                return self._delete_view(cur, row, command)

    def prepare_restore(
        self,
        command: KnowledgeRestoreCommand,
    ) -> KnowledgeRestoreOperationView:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                existing = self._operation_by_idempotency(
                    cur,
                    kind="restore",
                    user_id=command.user_id,
                    idempotency_key=command.idempotency_key,
                )
                if existing is not None:
                    persisted = KnowledgeRestoreCommand.model_validate(
                        existing["payload"]
                    )
                    self._require_same_command(persisted, command)
                    return self._restore_view(cur, existing, persisted)

                delete_row = self._locked_operation(
                    cur,
                    command.delete_command_id,
                    kind="delete",
                    user_id=command.user_id,
                )
                if (
                    delete_row is None
                    or delete_row["owner_id"] != command.owner_id
                ):
                    raise KnowledgeDeleteNotFound(
                        "delete command not found in caller scope"
                    )
                if self._receipt_row(cur, command.delete_command_id, "delete") is None:
                    raise KnowledgeDeleteConflict(
                        "only an executed delete command can be restored"
                    )

                delete_command = KnowledgeDeleteCommand.model_validate(
                    delete_row["payload"]
                )
                cur.execute(
                    """
                    SELECT state FROM knowledge_items
                    WHERE knowledge_item_id = %s AND owner_id = %s AND user_id = %s
                    FOR SHARE
                    """,
                    (
                        delete_command.target_note_id,
                        command.owner_id,
                        command.user_id,
                    ),
                )
                target = cur.fetchone()
                if target is None:
                    raise KnowledgeDeleteNotFound(
                        "knowledge item not found in caller scope"
                    )
                if target["state"] != "deleted":
                    raise KnowledgeDeleteConflict("knowledge item is not deleted")

                self._insert_operation(
                    cur,
                    kind="restore",
                    target_ref=command.delete_command_id,
                    command=command,
                )
                row = self._operation_by_idempotency(
                    cur,
                    kind="restore",
                    user_id=command.user_id,
                    idempotency_key=command.idempotency_key,
                )
                if row is None:
                    raise KnowledgeDeleteConflict(
                        "restore command could not be persisted"
                    )
                persisted = KnowledgeRestoreCommand.model_validate(row["payload"])
                self._require_same_command(persisted, command)
                view = self._restore_view(cur, row, persisted)
            conn.commit()
        return view

    def decide_restore(
        self,
        *,
        command_id: str,
        user_id: str,
        decision: Literal["confirm", "reject"],
        confirmation_ref: str,
    ) -> KnowledgeRestoreOperationView:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                row = self._locked_operation(
                    cur, command_id, kind="restore", user_id=user_id
                )
                if row is None:
                    raise KnowledgeDeleteNotFound(
                        "restore command not found in caller scope"
                    )
                command = KnowledgeRestoreCommand.model_validate(row["payload"])
                terminal = self._terminal_restore_view(cur, row, command, decision)
                if terminal is not None:
                    return terminal
                if decision == "reject":
                    self._reject_operation(cur, command.command_id)
                    view = self._restore_view(
                        cur,
                        self._locked_operation(
                            cur,
                            command.command_id,
                            kind="restore",
                            user_id=user_id,
                        ),
                        command,
                    )
                    conn.commit()
                    return view

                receipt = self._execute_restore(cur, command, confirmation_ref)
                self._record_receipt(cur, "restore", receipt)
                self._complete_operation(
                    cur, command.command_id, confirmation_ref, receipt.restored_at
                )
                row = self._locked_operation(
                    cur, command.command_id, kind="restore", user_id=user_id
                )
                view = self._restore_view(cur, row, command)
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
                row = self._locked_operation(
                    cur,
                    command_id,
                    kind="restore",
                    user_id=user_id,
                    lock=False,
                )
                if row is None:
                    return None
                command = KnowledgeRestoreCommand.model_validate(row["payload"])
                return self._restore_view(cur, row, command)

    def _execute_delete(
        self,
        cur,
        command: KnowledgeDeleteCommand,
        confirmation_ref: str,
    ) -> KnowledgeDeleteReceipt:
        cur.execute(
            """
            SELECT payload FROM knowledge_items
            WHERE knowledge_item_id = %s AND owner_id = %s AND user_id = %s
            FOR UPDATE
            """,
            (command.target_note_id, command.owner_id, command.user_id),
        )
        item_row = cur.fetchone()
        if item_row is None:
            raise KnowledgeDeleteNotFound(
                "knowledge item not found in command scope"
            )
        item = KnowledgeItem.model_validate(item_row["payload"])
        if item.state == "deleted":
            raise KnowledgeDeleteConflict(
                "knowledge item is deleted without this command receipt"
            )

        executed_at = local_now()
        previous_item_state = item.state
        item = item.model_copy(update={"state": "deleted", "updated_at": executed_at})
        self._update_item(cur, item)

        affected_claim_ids: list[str] = []
        previous_claim_states: dict[str, str] = {}
        state_event_ids: list[str] = []
        targets: list[tuple[str, str, str, tuple[str, ...]]] = [(
            "knowledge_item",
            item.knowledge_item_id,
            previous_item_state,
            tuple(item.evidence_span_ids),
        )]
        for claim_id in item.claim_ids:
            cur.execute(
                """
                SELECT payload FROM knowledge_claims
                WHERE claim_id = %s AND owner_id = %s AND user_id = %s
                FOR UPDATE
                """,
                (claim_id, command.owner_id, command.user_id),
            )
            claim_row = cur.fetchone()
            if claim_row is None:
                continue
            claim = Claim.model_validate(claim_row["payload"])
            previous_claim_states[claim.claim_id] = claim.state
            claim = claim.model_copy(
                update={"state": "deleted", "updated_at": executed_at}
            )
            self._update_claim(cur, claim)
            affected_claim_ids.append(claim.claim_id)
            targets.append((
                "claim",
                claim.claim_id,
                previous_claim_states[claim.claim_id],
                tuple(claim.evidence_span_ids),
            ))

        for target_type, target_id, previous_state, evidence_span_ids in targets:
            state_event_ids.append(self._record_state_event(
                cur,
                command_id=command.command_id,
                owner_id=command.owner_id,
                target_type=target_type,
                target_id=target_id,
                from_state=previous_state,
                to_state="deleted",
                reason=command.reason or "confirmed knowledge deletion",
                evidence_span_ids=evidence_span_ids,
                policy_result="confirmed_delete_command",
            ))

        return KnowledgeDeleteReceipt(
            receipt_id=_stable_id("krec", command.command_digest),
            command_id=command.command_id,
            command_digest=command.command_digest,
            confirmation_ref=confirmation_ref,
            deleted_note_id=command.target_note_id,
            affected_claim_ids=tuple(affected_claim_ids),
            state_event_ids=tuple(state_event_ids),
            previous_item_state=previous_item_state,
            previous_claim_states=previous_claim_states,
            executed_at=executed_at,
        )

    def _execute_restore(
        self,
        cur,
        command: KnowledgeRestoreCommand,
        confirmation_ref: str,
    ) -> KnowledgeRestoreReceipt:
        delete_row = self._locked_operation(
            cur,
            command.delete_command_id,
            kind="delete",
            user_id=command.user_id,
        )
        if delete_row is None or delete_row["owner_id"] != command.owner_id:
            raise KnowledgeDeleteNotFound(
                "delete command not found in restore scope"
            )
        receipt_row = self._receipt_row(cur, command.delete_command_id, "delete")
        if receipt_row is None:
            raise KnowledgeDeleteConflict("delete receipt is required for restore")
        delete_receipt = KnowledgeDeleteReceipt.model_validate(receipt_row["payload"])

        cur.execute(
            """
            SELECT payload FROM knowledge_items
            WHERE knowledge_item_id = %s AND owner_id = %s AND user_id = %s
            FOR UPDATE
            """,
            (
                delete_receipt.deleted_note_id,
                command.owner_id,
                command.user_id,
            ),
        )
        item_row = cur.fetchone()
        if item_row is None:
            raise KnowledgeDeleteNotFound(
                "knowledge item not found in restore scope"
            )
        item = KnowledgeItem.model_validate(item_row["payload"])
        if item.state != "deleted":
            raise KnowledgeDeleteConflict(
                "knowledge item state changed after deletion"
            )

        restored_at = local_now()
        previous_item_state = item.state
        item = item.model_copy(update={
            "state": delete_receipt.previous_item_state,
            "updated_at": restored_at,
        })
        self._update_item(cur, item)

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
                SELECT payload FROM knowledge_claims
                WHERE claim_id = %s AND owner_id = %s AND user_id = %s
                FOR UPDATE
                """,
                (claim_id, command.owner_id, command.user_id),
            )
            claim_row = cur.fetchone()
            if claim_row is None:
                raise KnowledgeDeleteConflict(
                    "deleted claim is missing during restore"
                )
            claim = Claim.model_validate(claim_row["payload"])
            if claim.state != "deleted":
                raise KnowledgeDeleteConflict(
                    "claim state changed after deletion"
                )
            restored_state = delete_receipt.previous_claim_states.get(claim.claim_id)
            if not restored_state:
                raise KnowledgeDeleteConflict(
                    "delete receipt lacks the previous claim state"
                )
            claim = claim.model_copy(
                update={"state": restored_state, "updated_at": restored_at}
            )
            self._update_claim(cur, claim)
            restored_claim_ids.append(claim.claim_id)
            targets.append((
                "claim",
                claim.claim_id,
                "deleted",
                restored_state,
                tuple(claim.evidence_span_ids),
            ))

        for target_type, target_id, from_state, to_state, evidence_span_ids in targets:
            state_event_ids.append(self._record_state_event(
                cur,
                command_id=command.command_id,
                owner_id=command.owner_id,
                target_type=target_type,
                target_id=target_id,
                from_state=from_state,
                to_state=to_state,
                reason=command.reason or "confirmed knowledge restoration",
                evidence_span_ids=evidence_span_ids,
                policy_result="confirmed_restore_command",
            ))

        return KnowledgeRestoreReceipt(
            receipt_id=_stable_id("krer", command.command_digest),
            command_id=command.command_id,
            command_digest=command.command_digest,
            confirmation_ref=confirmation_ref,
            restored_note_id=item.knowledge_item_id,
            affected_claim_ids=tuple(restored_claim_ids),
            state_event_ids=tuple(state_event_ids),
            restored_at=restored_at,
        )

    @staticmethod
    def _insert_operation(cur, *, kind: str, target_ref: str, command) -> None:
        cur.execute(
            """
            INSERT INTO personal_knowledge_lifecycle_operations (
                command_id, kind, idempotency_key, owner_id, user_id,
                target_ref, command_digest, payload, status, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'awaiting_confirmation', %s)
            ON CONFLICT DO NOTHING
            """,
            (
                command.command_id,
                kind,
                command.idempotency_key,
                command.owner_id,
                command.user_id,
                target_ref,
                command.command_digest,
                Jsonb(command.model_dump(mode="json")),
                command.created_at,
            ),
        )

    @staticmethod
    def _operation_by_idempotency(
        cur,
        *,
        kind: str,
        user_id: str,
        idempotency_key: str,
    ):
        cur.execute(
            """
            SELECT * FROM personal_knowledge_lifecycle_operations
            WHERE user_id = %s AND kind = %s AND idempotency_key = %s
            FOR UPDATE
            """,
            (user_id, kind, idempotency_key),
        )
        return cur.fetchone()

    @staticmethod
    def _locked_operation(
        cur,
        command_id: str,
        *,
        kind: str,
        user_id: str,
        lock: bool = True,
    ):
        suffix = " FOR UPDATE" if lock else ""
        cur.execute(
            "SELECT * FROM personal_knowledge_lifecycle_operations "
            "WHERE command_id = %s AND kind = %s AND user_id = %s" + suffix,
            (command_id, kind, user_id),
        )
        return cur.fetchone()

    @staticmethod
    def _reject_operation(cur, command_id: str) -> None:
        cur.execute(
            """
            UPDATE personal_knowledge_lifecycle_operations
            SET status = 'rejected', decided_at = %s
            WHERE command_id = %s AND status = 'awaiting_confirmation'
            """,
            (local_now(), command_id),
        )

    @staticmethod
    def _complete_operation(
        cur,
        command_id: str,
        confirmation_ref: str,
        decided_at,
    ) -> None:
        cur.execute(
            """
            UPDATE personal_knowledge_lifecycle_operations
            SET status = 'executed', confirmation_ref = %s, decided_at = %s
            WHERE command_id = %s AND status = 'awaiting_confirmation'
            """,
            (confirmation_ref, decided_at, command_id),
        )

    @staticmethod
    def _record_receipt(cur, kind: str, receipt) -> None:
        created_at = getattr(receipt, "executed_at", None) or receipt.restored_at
        cur.execute(
            """
            INSERT INTO personal_knowledge_lifecycle_receipts (
                receipt_id, command_id, kind, command_digest, payload, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                receipt.receipt_id,
                receipt.command_id,
                kind,
                receipt.command_digest,
                Jsonb(receipt.model_dump(mode="json")),
                created_at,
            ),
        )

    @staticmethod
    def _receipt_row(cur, command_id: str, kind: str):
        cur.execute(
            """
            SELECT payload FROM personal_knowledge_lifecycle_receipts
            WHERE command_id = %s AND kind = %s
            """,
            (command_id, kind),
        )
        return cur.fetchone()

    def _delete_view(
        self,
        cur,
        row,
        command: KnowledgeDeleteCommand,
    ) -> KnowledgeDeleteOperationView:
        receipt_row = self._receipt_row(cur, command.command_id, "delete")
        receipt = (
            KnowledgeDeleteReceipt.model_validate(receipt_row["payload"])
            if receipt_row
            else None
        )
        return KnowledgeDeleteOperationView(
            command=command,
            status=row["status"],
            receipt=receipt,
        )

    def _restore_view(
        self,
        cur,
        row,
        command: KnowledgeRestoreCommand,
    ) -> KnowledgeRestoreOperationView:
        receipt_row = self._receipt_row(cur, command.command_id, "restore")
        receipt = (
            KnowledgeRestoreReceipt.model_validate(receipt_row["payload"])
            if receipt_row
            else None
        )
        return KnowledgeRestoreOperationView(
            command=command,
            status=row["status"],
            receipt=receipt,
        )

    def _terminal_delete_view(self, cur, row, command, decision):
        if row["status"] == "executed":
            return self._delete_view(cur, row, command)
        if row["status"] == "rejected":
            if decision == "reject":
                return self._delete_view(cur, row, command)
            raise KnowledgeDeleteConflict("rejected command cannot be executed")
        return None

    def _terminal_restore_view(self, cur, row, command, decision):
        if row["status"] == "executed":
            return self._restore_view(cur, row, command)
        if row["status"] == "rejected":
            if decision == "reject":
                return self._restore_view(cur, row, command)
            raise KnowledgeDeleteConflict("rejected command cannot be executed")
        return None

    @staticmethod
    def _require_same_command(left, right) -> None:
        excluded = {"created_at"}
        if left.model_dump(exclude=excluded) != right.model_dump(exclude=excluded):
            raise KnowledgeDeleteConflict(
                "idempotency key is already bound to a different immutable command"
            )

    @staticmethod
    def _update_item(cur, item: KnowledgeItem) -> None:
        cur.execute(
            """
            UPDATE knowledge_items
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

    @staticmethod
    def _update_claim(cur, claim: Claim) -> None:
        cur.execute(
            """
            UPDATE knowledge_claims
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

    @staticmethod
    def _record_state_event(
        cur,
        *,
        command_id: str,
        owner_id: str,
        target_type: str,
        target_id: str,
        from_state: str,
        to_state: str,
        reason: str,
        evidence_span_ids: tuple[str, ...],
        policy_result: str,
    ) -> str:
        event = KnowledgeStateEvent(
            event_id=_stable_id("ksev", command_id, target_id),
            owner_id=owner_id,
            target_type=target_type,
            target_id=target_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            actor="user",
            evidence_span_ids=list(evidence_span_ids),
            policy_result=policy_result,
        )
        cur.execute(
            """
            INSERT INTO knowledge_state_events
                (event_id, target_id, owner_id, to_state, payload, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event.event_id,
                event.target_id,
                event.owner_id,
                event.to_state,
                Jsonb(event.model_dump(mode="json")),
                event.created_at,
            ),
        )
        return event.event_id

    def _migrate_legacy_tables(self, cur) -> None:
        self._migrate_legacy_kind(
            cur,
            kind="delete",
            command_table="knowledge_delete_commands",
            event_table="knowledge_delete_events",
            receipt_table="knowledge_delete_receipts",
            target_column="target_note_id",
        )
        self._migrate_legacy_kind(
            cur,
            kind="restore",
            command_table="knowledge_restore_commands",
            event_table="knowledge_restore_events",
            receipt_table="knowledge_restore_receipts",
            target_column="delete_command_id",
        )

    def _migrate_legacy_kind(
        self,
        cur,
        *,
        kind: str,
        command_table: str,
        event_table: str,
        receipt_table: str,
        target_column: str,
    ) -> None:
        if not self._table_exists(cur, command_table):
            return
        cur.execute(
            f"""
            INSERT INTO personal_knowledge_lifecycle_operations (
                command_id, kind, idempotency_key, owner_id, user_id,
                target_ref, command_digest, payload, status, confirmation_ref,
                created_at, decided_at
            )
            SELECT command_id, %s, idempotency_key, owner_id, user_id,
                   {target_column}, execution_command_digest,
                   (payload - 'authorization_digest' - 'execution_command_digest')
                       || jsonb_build_object(
                           'command_digest', execution_command_digest
                       ),
                   'awaiting_confirmation', '', created_at, NULL
            FROM {command_table}
            ON CONFLICT (command_id) DO NOTHING
            """,
            (kind,),
        )
        if self._table_exists(cur, receipt_table):
            cur.execute(
                f"""
                INSERT INTO personal_knowledge_lifecycle_receipts (
                    receipt_id, command_id, kind, command_digest, payload, created_at
                )
                SELECT receipt_id, command_id, %s, execution_command_digest,
                       (payload - 'execution_command_digest')
                           || jsonb_build_object(
                               'command_digest', execution_command_digest
                           ),
                       created_at
                FROM {receipt_table}
                ON CONFLICT (command_id) DO NOTHING
                """,
                (kind,),
            )
            cur.execute(
                """
                UPDATE personal_knowledge_lifecycle_operations operation
                SET status = 'executed',
                    confirmation_ref = COALESCE(
                        receipt.payload->>'confirmation_ref', ''
                    ),
                    decided_at = receipt.created_at
                FROM personal_knowledge_lifecycle_receipts receipt
                WHERE operation.command_id = receipt.command_id
                  AND operation.kind = %s
                  AND receipt.kind = %s
                """,
                (kind, kind),
            )
        if self._table_exists(cur, event_table):
            cur.execute(
                f"""
                UPDATE personal_knowledge_lifecycle_operations operation
                SET status = 'rejected', decided_at = rejected.created_at
                FROM (
                    SELECT command_id, MAX(created_at) AS created_at
                    FROM {event_table}
                    WHERE event_type = 'rejected'
                    GROUP BY command_id
                ) rejected
                WHERE operation.command_id = rejected.command_id
                  AND operation.kind = %s
                  AND operation.status <> 'executed'
                """,
                (kind,),
            )

        cur.execute(f"SELECT COUNT(*) AS count FROM {command_table}")
        legacy_count = int(cur.fetchone()["count"])
        cur.execute(
            """
            SELECT COUNT(*) AS count FROM personal_knowledge_lifecycle_operations
            WHERE kind = %s
            """,
            (kind,),
        )
        if int(cur.fetchone()["count"]) < legacy_count:
            raise RuntimeError(f"failed to migrate every legacy {kind} command")

        for table in (event_table, receipt_table, command_table):
            if self._table_exists(cur, table):
                cur.execute(f"DROP TABLE {table}")

    @staticmethod
    def _table_exists(cur, table_name: str) -> bool:
        cur.execute("SELECT to_regclass(%s) AS relation", (table_name,))
        return cur.fetchone()["relation"] is not None


def _stable_id(prefix: str, *parts: str) -> str:
    value = ":".join(parts)
    return f"{prefix}_{sha256(value.encode('utf-8')).hexdigest()[:24]}"


__all__ = ["PostgresKnowledgeLifecycleStore"]

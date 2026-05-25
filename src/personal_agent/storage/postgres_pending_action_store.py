from __future__ import annotations

import logging
from datetime import datetime

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..core.models import AuditEvent, PendingAction
from .postgres_common import PostgresStoreBase

logger = logging.getLogger(__name__)


class PostgresPendingActionStore(PostgresStoreBase):
    """Database-backed HITL pending actions and their audit trail."""

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pending_actions (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        action_type TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS pending_actions_user_status_idx
                    ON pending_actions (user_id, status, created_at DESC)
                    """
                )
            conn.commit()
        self._initialized = True

    def create(self, action: PendingAction) -> PendingAction:
        action.audit_log.append(
            AuditEvent(event="created", detail=f"Pending {action.action_type} for {action.target_id}")
        )
        self._save(action)
        return action

    def list_by_user(self, user_id: str, status: str | None = None) -> list[PendingAction]:
        actions = self._list(user_id)
        for action in actions:
            self._expire_if_needed(action)
        actions = self._list(user_id)
        if status:
            actions = [action for action in actions if action.status == status]
        return actions

    def get(self, action_id: str, user_id: str | None = None) -> PendingAction | None:
        action = self._get(action_id, user_id)
        if action is not None:
            self._expire_if_needed(action)
            action = self._get(action_id, user_id)
        return action

    def confirm(self, action_id: str, token: str, user_id: str) -> PendingAction | None:
        action = self.get(action_id, user_id)
        if action is None or action.status != "pending" or action.token != token:
            return None
        action.status = "confirmed"
        action.resolved_at = datetime.utcnow()
        action.audit_log.append(AuditEvent(event="confirmed", detail=f"Confirmed by {user_id}"))
        self._save(action)
        return action

    def reject(self, action_id: str, user_id: str, reason: str = "") -> PendingAction | None:
        action = self.get(action_id, user_id)
        if action is None or action.status != "pending":
            return None
        action.status = "rejected"
        action.resolved_at = datetime.utcnow()
        action.audit_log.append(AuditEvent(event="rejected", detail=reason or f"Rejected by {user_id}"))
        self._save(action)
        return action

    def mark_executed(self, action_id: str, user_id: str) -> PendingAction | None:
        action = self.get(action_id, user_id)
        if action is None or action.status != "confirmed":
            return None
        action.status = "executed"
        action.audit_log.append(AuditEvent(event="executed", detail=f"Action executed for {action.target_id}"))
        self._save(action)
        return action

    def delete(self, action_id: str, user_id: str) -> bool:
        return self._delete("WHERE id = %s AND user_id = %s", (action_id, user_id)) > 0

    def clear_user(self, user_id: str) -> int:
        return self._delete("WHERE user_id = %s", (user_id,))

    def _expire_if_needed(self, action: PendingAction) -> None:
        if action.status == "pending" and datetime.utcnow() >= action.expires_at:
            action.status = "expired"
            action.resolved_at = datetime.utcnow()
            action.audit_log.append(AuditEvent(event="expired", detail="Auto-expired by expiry check"))
            self._save(action)

    def _save(self, action: PendingAction) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pending_actions
                        (id, user_id, status, action_type, expires_at, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        expires_at = EXCLUDED.expires_at,
                        payload = EXCLUDED.payload
                    """,
                    (
                        action.id, action.user_id, action.status, action.action_type,
                        action.expires_at, Jsonb(action.model_dump(mode="json")), action.created_at,
                    ),
                )
            conn.commit()

    def _list(self, user_id: str) -> list[PendingAction]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM pending_actions WHERE user_id = %s ORDER BY created_at DESC",
                    (user_id,),
                )
                return [PendingAction.model_validate(row["payload"]) for row in cur.fetchall()]

    def _get(self, action_id: str, user_id: str | None) -> PendingAction | None:
        self.ensure_schema()
        params: tuple[str, ...] = (action_id,) if user_id is None else (action_id, user_id)
        suffix = "" if user_id is None else " AND user_id = %s"
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT payload FROM pending_actions WHERE id = %s{suffix}", params)
                row = cur.fetchone()
        return PendingAction.model_validate(row["payload"]) if row else None

    def _delete(self, where: str, params: tuple[str, ...]) -> int:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM pending_actions {where}", params)
                removed = cur.rowcount or 0
            conn.commit()
        return int(removed)

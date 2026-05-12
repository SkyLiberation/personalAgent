from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..core.models import AuditEvent, PendingAction

logger = logging.getLogger(__name__)


class PendingActionStore:
    """JSON-file store for HITL pending actions with expiry support."""

    def __init__(self, data_dir: Path) -> None:
        self._file = data_dir / "pending_actions.json"
        data_dir.mkdir(parents=True, exist_ok=True)
        if not self._file.exists():
            self._file.write_text("[]", encoding="utf-8")

    def _load(self) -> list[PendingAction]:
        raw = json.loads(self._file.read_text(encoding="utf-8"))
        return [PendingAction.model_validate(item) for item in raw]

    def _save(self, actions: list[PendingAction]) -> None:
        payload = [a.model_dump(mode="json") for a in actions]
        self._file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _append_audit(self, action: PendingAction, event: str, detail: str = "") -> None:
        action.audit_log.append(AuditEvent(event=event, detail=detail))

    def create(self, action: PendingAction) -> PendingAction:
        self._append_audit(action, "created", f"Pending {action.action_type} for {action.target_id}")
        actions = self._load()
        actions.append(action)
        self._save(actions)
        logger.info(
            "Pending action created id=%s type=%s target=%s user=%s token=%s expires=%s",
            action.id, action.action_type, action.target_id, action.user_id,
            action.token, action.expires_at.isoformat(),
        )
        return action

    def list_by_user(self, user_id: str, status: str | None = None) -> list[PendingAction]:
        actions = self._load()
        # Auto-expire overdue pending actions first, before filtering
        now = datetime.utcnow()
        dirty = False
        for a in actions:
            if a.user_id == user_id and a.status == "pending" and now >= a.expires_at:
                a.status = "expired"
                a.resolved_at = now
                self._append_audit(a, "expired", "Auto-expired by expiry check")
                dirty = True
        if dirty:
            self._save(actions)
        result = [a for a in actions if a.user_id == user_id]
        if status:
            result = [a for a in result if a.status == status]
        result.sort(key=lambda a: a.created_at, reverse=True)
        return result

    def get(self, action_id: str, user_id: str | None = None) -> PendingAction | None:
        actions = self._load()
        for a in actions:
            if a.id == action_id and (user_id is None or a.user_id == user_id):
                if a.status == "pending" and datetime.utcnow() >= a.expires_at:
                    a.status = "expired"
                    a.resolved_at = datetime.utcnow()
                    self._append_audit(a, "expired", "Auto-expired on retrieval")
                    self._save(actions)
                return a
        return None

    def confirm(self, action_id: str, token: str, user_id: str) -> PendingAction | None:
        actions = self._load()
        for a in actions:
            if a.id == action_id and a.user_id == user_id:
                if a.status != "pending":
                    logger.warning("Confirm attempt on non-pending action id=%s status=%s", action_id, a.status)
                    return None
                if a.token != token:
                    logger.warning("Confirm token mismatch for action id=%s", action_id)
                    return None
                if datetime.utcnow() >= a.expires_at:
                    a.status = "expired"
                    a.resolved_at = datetime.utcnow()
                    self._append_audit(a, "expired", "Expired during confirmation")
                    self._save(actions)
                    return None
                a.status = "confirmed"
                a.resolved_at = datetime.utcnow()
                self._append_audit(a, "confirmed", f"Confirmed by {user_id}")
                self._save(actions)
                logger.info("Pending action confirmed id=%s type=%s target=%s", action_id, a.action_type, a.target_id)
                return a
        return None

    def reject(self, action_id: str, user_id: str, reason: str = "") -> PendingAction | None:
        actions = self._load()
        for a in actions:
            if a.id == action_id and a.user_id == user_id:
                if a.status != "pending":
                    logger.warning("Reject attempt on non-pending action id=%s status=%s", action_id, a.status)
                    return None
                if datetime.utcnow() >= a.expires_at:
                    a.status = "expired"
                    a.resolved_at = datetime.utcnow()
                    self._append_audit(a, "expired", "Expired during rejection")
                    self._save(actions)
                    return None
                a.status = "rejected"
                a.resolved_at = datetime.utcnow()
                self._append_audit(a, "rejected", reason or f"Rejected by {user_id}")
                self._save(actions)
                logger.info("Pending action rejected id=%s type=%s target=%s reason=%s", action_id, a.action_type, a.target_id, reason)
                return a
        return None

    def mark_executed(self, action_id: str, user_id: str) -> PendingAction | None:
        actions = self._load()
        for a in actions:
            if a.id == action_id and a.user_id == user_id:
                if a.status != "confirmed":
                    return None
                a.status = "executed"
                self._append_audit(a, "executed", f"Action executed for {a.target_id}")
                self._save(actions)
                return a
        return None

    def delete(self, action_id: str, user_id: str) -> bool:
        actions = self._load()
        original_len = len(actions)
        filtered = [a for a in actions if not (a.id == action_id and a.user_id == user_id)]
        if len(filtered) == original_len:
            return False
        self._save(filtered)
        return True

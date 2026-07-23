"""Durable run state machine with pluggable optimistic repositories."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Literal, Protocol
from uuid import uuid4


RunStatus = Literal[
    "created", "queued", "running", "waiting", "blocked_approval",
    "cancel_requested", "cancelling", "completed", "completed_degraded",
    "cancelled", "failed", "timed_out",
]
ExecutionMode = Literal["foreground", "background"]

_TERMINAL = frozenset({"completed", "completed_degraded", "cancelled", "failed", "timed_out"})
_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"queued", "cancelled"}),
    "queued": frozenset({"running", "cancelled", "timed_out"}),
    "running": frozenset({"waiting", "blocked_approval", "cancel_requested", "completed", "completed_degraded", "failed", "timed_out"}),
    "waiting": frozenset({"running", "cancel_requested", "completed", "failed", "timed_out"}),
    "blocked_approval": frozenset({"running", "cancel_requested", "cancelled", "timed_out"}),
    "cancel_requested": frozenset({"cancelling", "cancelled"}),
    "cancelling": frozenset({"cancelled"}),
    "completed": frozenset(),
    "completed_degraded": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
    "timed_out": frozenset(),
}


@dataclass(frozen=True, slots=True)
class RunLease:
    lease_id: str
    fencing_token: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DurableRun:
    run_id: str
    status: RunStatus = "created"
    execution_mode: ExecutionMode = "foreground"
    fencing_token: int = 0
    revision: int = 0
    orphan_artifact_refs: tuple[str, ...] = ()


class RunStateError(RuntimeError):
    pass


class DurableRunRepository(Protocol):
    def create(self, run: DurableRun) -> DurableRun: ...

    def get(self, run_id: str) -> DurableRun | None: ...

    def compare_and_set(self, run: DurableRun, *, expected_revision: int) -> DurableRun: ...

    def bind_submission(self, idempotency_key: str, run_id: str) -> str: ...

    def get_submission(self, idempotency_key: str) -> str | None: ...

    def put_lease(self, run_id: str, lease: RunLease) -> None: ...

    def get_lease(self, run_id: str) -> RunLease | None: ...

    def renew_lease(self, run_id: str, lease: RunLease) -> bool: ...


class InMemoryDurableRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, DurableRun] = {}
        self._leases: dict[str, RunLease] = {}
        self._submissions: dict[str, str] = {}
        self._lock = RLock()

    def create(self, run: DurableRun) -> DurableRun:
        with self._lock:
            if run.run_id in self._runs:
                raise RunStateError(f"run already exists: {run.run_id}")
            self._runs[run.run_id] = run
            return run

    def get(self, run_id: str) -> DurableRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def compare_and_set(self, run: DurableRun, *, expected_revision: int) -> DurableRun:
        with self._lock:
            current = self._runs.get(run.run_id)
            if current is None:
                raise RunStateError(f"unknown run: {run.run_id}")
            if current.revision != expected_revision:
                raise RunStateError("concurrent run update")
            self._runs[run.run_id] = run
            return run

    def bind_submission(self, idempotency_key: str, run_id: str) -> str:
        with self._lock:
            bound = self._submissions.setdefault(idempotency_key, run_id)
            return bound

    def get_submission(self, idempotency_key: str) -> str | None:
        with self._lock:
            return self._submissions.get(idempotency_key)

    def put_lease(self, run_id: str, lease: RunLease) -> None:
        with self._lock:
            self._leases[run_id] = lease

    def get_lease(self, run_id: str) -> RunLease | None:
        with self._lock:
            return self._leases.get(run_id)

    def renew_lease(self, run_id: str, lease: RunLease) -> bool:
        with self._lock:
            current = self._leases.get(run_id)
            if current is None or (
                current.lease_id != lease.lease_id
                or current.fencing_token != lease.fencing_token
            ):
                return False
            self._leases[run_id] = lease
            return True


class DurableRunManager:
    def __init__(self, repository: DurableRunRepository | None = None) -> None:
        self._repository = repository or InMemoryDurableRunRepository()
        self._lock = RLock()

    def submit(
        self,
        run_id: str,
        *,
        idempotency_key: str,
        execution_mode: ExecutionMode = "foreground",
    ) -> DurableRun:
        with self._lock:
            existing_run_id = self._repository.get_submission(idempotency_key)
            if existing_run_id is not None:
                if existing_run_id != run_id:
                    raise RunStateError("idempotency key is bound to another run")
                return self.get(existing_run_id)
            try:
                run = self.create(run_id, execution_mode=execution_mode)
            except RunStateError:
                run = self.get(run_id)
                if run.execution_mode != execution_mode:
                    raise RunStateError("run execution mode conflicts with duplicate submission")
            bound = self._repository.bind_submission(idempotency_key, run_id)
            if bound != run_id:
                raise RunStateError("idempotency key is bound to another run")
            return run

    def create(self, run_id: str, *, execution_mode: ExecutionMode = "foreground") -> DurableRun:
        return self._repository.create(DurableRun(run_id=run_id, execution_mode=execution_mode))

    def get(self, run_id: str) -> DurableRun:
        run = self._repository.get(run_id)
        if run is None:
            raise RunStateError(f"unknown run: {run_id}")
        return run

    def acquire_lease(self, run_id: str, ttl_seconds: int = 300) -> RunLease:
        with self._lock:
            run = self.get(run_id)
            token = run.fencing_token + 1
            lease = RunLease(
                lease_id=uuid4().hex,
                fencing_token=token,
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            )
            updated = replace(run, fencing_token=token, revision=run.revision + 1)
            self._repository.compare_and_set(updated, expected_revision=run.revision)
            self._repository.put_lease(run_id, lease)
            return lease

    def transition(self, run_id: str, status: RunStatus, *, fencing_token: int) -> DurableRun:
        with self._lock:
            run = self.get(run_id)
            self._assert_fence(run_id, run, fencing_token)
            if status == run.status:
                return run
            if status not in _TRANSITIONS[run.status]:
                raise RunStateError(f"illegal run transition {run.status}->{status}")
            updated = replace(run, status=status, revision=run.revision + 1)
            return self._repository.compare_and_set(updated, expected_revision=run.revision)

    def renew_lease(
        self,
        run_id: str,
        lease: RunLease,
        *,
        ttl_seconds: int = 300,
    ) -> RunLease:
        """Extend only the exact lease identity currently owning the run."""
        with self._lock:
            run = self.get(run_id)
            if run.fencing_token != lease.fencing_token:
                raise RunStateError("stale fencing token")
            renewed = replace(
                lease,
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            )
            if not self._repository.renew_lease(run_id, renewed):
                raise RunStateError("stale run lease")
            return renewed

    def request_cancel(self, run_id: str, *, fencing_token: int) -> DurableRun:
        run = self.get(run_id)
        if run.status in _TERMINAL:
            return run
        target: RunStatus = "cancelled" if run.status in {"created", "queued", "blocked_approval"} else "cancel_requested"
        return self.transition(run_id, target, fencing_token=fencing_token)

    def admit_external_completion(
        self,
        run_id: str,
        *,
        fencing_token: int,
        artifact_refs: tuple[str, ...] = (),
    ) -> DurableRun:
        with self._lock:
            run = self.get(run_id)
            self._assert_fence(run_id, run, fencing_token)
            if run.status in {"completed", "completed_degraded"}:
                return run
            if run.status in {"cancel_requested", "cancelling", "cancelled"}:
                updated = replace(
                    run,
                    status="cancelled",
                    revision=run.revision + 1,
                    orphan_artifact_refs=(*run.orphan_artifact_refs, *artifact_refs),
                )
                return self._repository.compare_and_set(updated, expected_revision=run.revision)
            return self.transition(run_id, "completed", fencing_token=fencing_token)

    def _assert_fence(self, run_id: str, run: DurableRun, fencing_token: int) -> None:
        lease = self._repository.get_lease(run_id)
        if lease is None or fencing_token != run.fencing_token or fencing_token != lease.fencing_token:
            raise RunStateError("stale fencing token")
        if lease.expires_at <= datetime.now(UTC):
            raise RunStateError("run lease expired")


__all__ = [
    "DurableRun",
    "DurableRunManager",
    "DurableRunRepository",
    "ExecutionMode",
    "InMemoryDurableRunRepository",
    "RunLease",
    "RunStateError",
    "RunStatus",
]

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from ..core.models import EntryInput
from ..storage.postgres_worker_queue_store import WorkerTask

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkerRunStats:
    leased: int = 0
    completed: int = 0
    failed: int = 0
    unsupported: int = 0


class WorkflowWorker:
    """Long-running activity worker over the durable Postgres queue."""

    def __init__(
        self,
        runtime,
        *,
        queue: str,
        worker_id: str | None = None,
        lease_seconds: int = 300,
        max_running_per_user: int = 1,
    ) -> None:
        self.runtime = runtime
        self.queue = queue
        self.worker_id = worker_id or f"worker-{uuid4().hex[:10]}"
        self.lease_seconds = max(1, lease_seconds)
        self.max_running_per_user = max(0, max_running_per_user)
        self._handlers: dict[str, Callable[[WorkerTask], bool]] = {
            "graph_sync_note": self._handle_graph_sync_note,
            "research_run": self._handle_research_run,
            "research_delivery": self._handle_research_delivery,
        }

    def run_once(self) -> WorkerRunStats:
        stats = WorkerRunStats()
        task = self.runtime.worker_queue_store.lease_next(
            queue=self.queue,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            max_running_per_user=self.max_running_per_user,
        )
        if task is None:
            return stats
        stats.leased = 1
        handler = self._handlers.get(task.task_type)
        if handler is None:
            self.runtime.worker_queue_store.fail(
                task.task_id,
                f"unsupported task_type={task.task_type}",
                retry_delay_seconds=0,
            )
            stats.failed = 1
            stats.unsupported = 1
            return stats
        try:
            self.runtime.worker_queue_store.heartbeat(
                task.task_id,
                self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if handler(task):
                self.runtime.worker_queue_store.complete(task.task_id)
                stats.completed = 1
            else:
                self.runtime.worker_queue_store.fail(
                    task.task_id,
                    "activity returned false",
                    retry_delay_seconds=30,
                )
                stats.failed = 1
        except Exception as exc:
            logger.exception("Worker task failed task_id=%s type=%s", task.task_id, task.task_type)
            self.runtime.worker_queue_store.fail(
                task.task_id,
                f"{type(exc).__name__}: {exc}",
                retry_delay_seconds=30,
            )
            stats.failed = 1
        return stats

    def run_forever(
        self,
        *,
        poll_seconds: float = 1.0,
        max_tasks: int = 0,
    ) -> WorkerRunStats:
        total = WorkerRunStats()
        while max_tasks <= 0 or total.leased < max_tasks:
            current = self.run_once()
            total.leased += current.leased
            total.completed += current.completed
            total.failed += current.failed
            total.unsupported += current.unsupported
            if current.leased == 0:
                time.sleep(max(0.05, poll_seconds))
        return total

    def _handle_graph_sync_note(self, task: WorkerTask) -> bool:
        note_id = str(task.payload.get("note_id") or "")
        return bool(note_id) and self.runtime.sync_note_to_graph(note_id)

    def _handle_research_run(self, task: WorkerTask) -> bool:
        run_id = str(task.payload.get("run_id") or "")
        if not run_id:
            return False
        run = self.runtime.research_store.get_run(run_id)
        if run is None:
            return False
        if hasattr(self.runtime, "execute_entry"):
            result = self.runtime.execute_entry(EntryInput(
                text=f"执行 Research run {run_id}: {run.topic}",
                user_id=run.user_id,
                session_id=f"research:{run_id}",
                source_platform="worker",
                metadata={
                    "intent_override": "execute_research_run",
                    "research_run_id": run_id,
                },
            ))
            if getattr(result, "run_status", "") not in {"completed", ""}:
                return False
            run = self.runtime.research_store.get_run(run_id)
            if run is None:
                return False
        else:
            run = self.runtime.research_service.execute_run(run_id)
        if run.status not in {"completed", "partial"}:
            return False
        if run.subscription_id and run.digest_id:
            self.runtime.research_store.enqueue_delivery(run)
        return True

    def _handle_research_delivery(self, task: WorkerTask) -> bool:
        run_id = str(task.payload.get("run_id") or "")
        return bool(run_id) and self.runtime.research_service.deliver_run(run_id)

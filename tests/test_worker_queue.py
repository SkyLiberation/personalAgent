from __future__ import annotations

from unittest.mock import MagicMock

from personal_agent.agent.runtime import AgentRuntime
from personal_agent.core.models import local_now
from personal_agent.graphiti.store import GraphCaptureResult, GraphitiStore
from personal_agent.storage.postgres_memory_store import PostgresMemoryStore
from personal_agent.storage.postgres_worker_queue_store import PostgresWorkerQueueStore
from tests.note_factory import make_note


def test_worker_queue_enqueue_lease_complete(postgres_url, clean_postgres_business_tables):
    store = PostgresWorkerQueueStore(postgres_url)

    task = store.enqueue(
        queue="graph",
        task_type="graph_sync_note",
        payload={"note_id": "n1"},
        idempotency_key="graph_sync_note:n1",
    )
    duplicate = store.enqueue(
        queue="graph",
        task_type="graph_sync_note",
        payload={"note_id": "n1", "title": "updated"},
        idempotency_key="graph_sync_note:n1",
    )

    assert duplicate.task_id == task.task_id
    leased = store.lease_next(queue="graph", worker_id="w1")
    assert leased.task_id == task.task_id
    assert leased.status == "running"
    assert leased.attempts == 1

    store.complete(leased.task_id)
    completed = store.list_tasks(queue="graph", statuses=["completed"])
    assert [item.task_id for item in completed] == [task.task_id]


def test_worker_queue_fail_moves_to_dead_after_max_attempts(postgres_url, clean_postgres_business_tables):
    store = PostgresWorkerQueueStore(postgres_url)
    task = store.enqueue(
        queue="graph",
        task_type="graph_sync_note",
        payload={"note_id": "n1"},
        idempotency_key="graph_sync_note:n1",
        max_attempts=1,
    )

    leased = store.lease_next(queue="graph", worker_id="w1")
    store.fail(leased.task_id, "boom", retry_delay_seconds=0)

    dead = store.list_tasks(queue="graph", statuses=["dead"])
    assert [item.task_id for item in dead] == [task.task_id]
    assert dead[0].last_error == "boom"
    assert store.queue_stats("graph")["dead"] == 1
    assert store.retry_dead(task.task_id) is True
    assert store.queue_stats("graph")["queued"] == 1


def test_worker_queue_heartbeat_extends_owned_lease(postgres_url, clean_postgres_business_tables):
    store = PostgresWorkerQueueStore(postgres_url)
    task = store.enqueue(
        queue="graph",
        task_type="graph_sync_note",
        payload={"note_id": "n1", "user_id": "u1"},
        idempotency_key="heartbeat:n1",
    )
    leased = store.lease_next(queue="graph", worker_id="w1", lease_seconds=1)

    assert leased is not None
    assert store.heartbeat(task.task_id, "w1", lease_seconds=60) is True
    assert store.heartbeat(task.task_id, "w2", lease_seconds=60) is False


def test_capture_enqueues_graph_sync_tasks(settings, temp_dir, clean_postgres_business_tables):
    runtime = AgentRuntime(
        settings,
        store=PostgresMemoryStore(temp_dir, settings.postgres_url),
        graph_store=GraphitiStore(settings),
    )
    runtime.graph_store = MagicMock()
    runtime.graph_store.configured.return_value = True
    runtime.graph_store.ingest_note.return_value = GraphCaptureResult(enabled=False)

    result = runtime.execute_capture(
        text="\n".join(["## A", "A" * 1500, "## B", "B" * 1500]),
        source_type="text",
        user_id="queue-user",
    )

    tasks = runtime.worker_queue_store.list_tasks(queue="graph", statuses=["queued"])
    task_note_ids = {task.payload["note_id"] for task in tasks}
    assert {chunk.id for chunk in result.chunk_notes} <= task_note_ids


def test_drain_worker_queue_runs_graph_sync(settings, temp_dir, clean_postgres_business_tables):
    runtime = AgentRuntime(
        settings,
        store=PostgresMemoryStore(temp_dir, settings.postgres_url),
        graph_store=GraphitiStore(settings),
    )
    runtime.graph_store = MagicMock()
    runtime.graph_store.configured.return_value = True
    runtime.graph_store.ingest_note.return_value = GraphCaptureResult(
        enabled=True,
        episode_uuid="ep-1",
        entity_names=["Redis"],
        relation_facts=["Redis 缓存热点数据"],
    )
    note = make_note(
        title="Redis",
        content="Redis 缓存热点数据。",
        summary="Redis",
        user_id="queue-user",
        graph_sync_status="pending",
    )
    note.updated_at = local_now()
    runtime.store.add_note(note)
    task_id = runtime.enqueue_graph_sync(note.id, user_id="queue-user")

    stats = runtime.drain_worker_queue(queue="graph", limit=1, worker_id="test-worker")

    assert stats == {"leased": 1, "completed": 1, "failed": 0, "unsupported": 0}
    assert runtime.store.get_note(note.id).graph_sync.status == "synced"
    completed = runtime.worker_queue_store.list_tasks(queue="graph", statuses=["completed"])
    assert [task.task_id for task in completed] == [task_id]

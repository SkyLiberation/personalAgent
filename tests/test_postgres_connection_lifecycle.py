from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from psycopg.rows import dict_row

from personal_agent.infra.storage.postgres_common import (
    PostgresStoreBase,
    close_postgres_connection_pools,
)


def test_stores_reuse_one_physical_connection_for_sequential_operations(postgres_url: str):
    close_postgres_connection_pools()
    first_store = PostgresStoreBase(postgres_url)
    second_store = PostgresStoreBase(postgres_url)
    backend_pids: list[int] = []

    try:
        for index in range(100):
            store = first_store if index % 2 == 0 else second_store
            row_factory = dict_row if index % 2 else None
            with store._connect(row_factory=row_factory) as conn:
                row = conn.execute(
                    "SELECT pg_backend_pid() AS backend_pid, %s::int AS operation_index",
                    (index,),
                ).fetchone()
                if isinstance(row, dict):
                    backend_pids.append(row["backend_pid"])
                    assert row["operation_index"] == index
                else:
                    backend_pids.append(row[0])
                    assert row[1] == index
    finally:
        close_postgres_connection_pools()

    assert len(set(backend_pids)) == 1


def test_pool_bounds_concurrent_physical_connections(postgres_url: str):
    close_postgres_connection_pools()
    store = PostgresStoreBase(postgres_url)

    def operation(index: int) -> int:
        with store._connect() as conn:
            return conn.execute(
                "SELECT pg_backend_pid(), %s::int FROM pg_sleep(0.01)",
                (index,),
            ).fetchone()[0]

    try:
        with ThreadPoolExecutor(max_workers=20) as executor:
            backend_pids = tuple(executor.map(operation, range(100)))
    finally:
        close_postgres_connection_pools()

    assert 1 < len(set(backend_pids)) <= 8

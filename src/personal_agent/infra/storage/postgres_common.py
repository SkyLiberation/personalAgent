from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool


_POOL_MAX_SIZE = 8
_POOL_TIMEOUT_SECONDS = 5.0


class PostgresConnectionPools:
    """Own one bounded physical connection pool for each normalized database URL."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._pools: dict[str, ConnectionPool] = {}

    @contextmanager
    def connection(self, postgres_url: str, *, row_factory: Any = None):
        pool = self._pool(postgres_url)
        with pool.connection(timeout=_POOL_TIMEOUT_SECONDS) as conn:
            previous_row_factory = conn.row_factory
            conn.row_factory = row_factory or tuple_row
            try:
                yield conn
            finally:
                conn.row_factory = previous_row_factory

    def close(self) -> None:
        with self._lock:
            pools = tuple(self._pools.values())
            self._pools.clear()
        for pool in pools:
            pool.close(timeout=_POOL_TIMEOUT_SECONDS)

    def _pool(self, postgres_url: str) -> ConnectionPool:
        url = normalize_postgres_url(postgres_url)
        with self._lock:
            pool = self._pools.get(url)
            if pool is None:
                pool = ConnectionPool(
                    url,
                    min_size=0,
                    max_size=_POOL_MAX_SIZE,
                    open=False,
                    timeout=_POOL_TIMEOUT_SECONDS,
                    check=ConnectionPool.check_connection,
                    name="personal-agent-postgres",
                )
                pool.open(wait=True, timeout=_POOL_TIMEOUT_SECONDS)
                self._pools[url] = pool
            return pool


_connection_pools = PostgresConnectionPools()


class PostgresStoreBase:
    def __init__(self, postgres_url: str) -> None:
        self.postgres_url = postgres_url
        self._initialized = False

    def _connect(self, *, row_factory: Any = None):
        return _connection_pools.connection(self.postgres_url, row_factory=row_factory)


def close_postgres_connection_pools() -> None:
    """Close process-owned pools after request and scheduler activity has stopped."""

    _connection_pools.close()


def normalize_postgres_url(postgres_url: str | None) -> str:
    if not postgres_url:
        raise ValueError("Postgres URL is not configured.")

    parts = urlsplit(postgres_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("connect_timeout", "5")
    query.setdefault("sslmode", "disable")
    host = parts.hostname or ""
    if host == "localhost":
        host = "127.0.0.1"
        netloc = host
        if parts.username:
            auth = parts.username
            if parts.password:
                auth = f"{auth}:{parts.password}"
            netloc = f"{auth}@{netloc}"
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
    else:
        netloc = parts.netloc
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), parts.fragment))

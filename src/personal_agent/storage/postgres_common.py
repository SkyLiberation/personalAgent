from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from psycopg import connect


class PostgresStoreBase:
    def __init__(self, postgres_url: str) -> None:
        self.postgres_url = postgres_url
        self._initialized = False

    def _connect(self, *, row_factory: Any = None):
        url = normalize_postgres_url(self.postgres_url)
        if row_factory is None:
            return connect(url)
        return connect(url, row_factory=row_factory)


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

from __future__ import annotations

from pathlib import Path

from psycopg import sql

from .postgres_common import PostgresStoreBase

_NAMED_TABLES = {
    "knowledge_notes": "notes",
    "review_cards": "reviews",
    "ask_history": "ask_history",
    "pending_actions": "pending_actions",
    "cross_session_artifacts": "cross_session_artifacts",
    "checkpoints": "checkpoints",
    "checkpoint_blobs": "checkpoint_blobs",
    "checkpoint_writes": "checkpoint_writes",
    "checkpoint_migrations": "checkpoint_migrations",
}


class PostgresDebugResetStore(PostgresStoreBase):
    """Destructive development-only reset for every table in the Postgres schema."""

    def clear_all_data(self) -> dict[str, int]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname = current_schema()
                    ORDER BY tablename
                    """
                )
                tables = [row[0] for row in cur.fetchall()]
                counts_by_table = {
                    table: _count_rows(cur, table)
                    for table in tables
                }
                if tables:
                    cur.execute(
                        sql.SQL("TRUNCATE TABLE {}").format(
                            sql.SQL(", ").join(sql.Identifier(table) for table in tables)
                        )
                    )
            conn.commit()
        result = {
            key: counts_by_table.get(table, 0)
            for table, key in _NAMED_TABLES.items()
        }
        result["postgres_tables"] = len(tables)
        result["postgres_rows"] = sum(counts_by_table.values())
        return result


def clear_upload_files(data_dir: Path) -> int:
    uploads_dir = (data_dir / "uploads").resolve()
    if not uploads_dir.exists():
        return 0

    removed = 0
    for item in sorted(uploads_dir.rglob("*"), reverse=True):
        if item.is_file():
            item.unlink()
            removed += 1
        elif item.is_dir():
            item.rmdir()
    return removed


def _count_rows(cur, table: str) -> int:
    cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
    return int(cur.fetchone()[0])

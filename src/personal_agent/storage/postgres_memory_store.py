from __future__ import annotations

from datetime import datetime
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..core.models import KnowledgeNote, ReviewCard
from .postgres_common import PostgresStoreBase


class PostgresMemoryStore(PostgresStoreBase):
    """Postgres-backed source of truth for notes and reviews."""

    def __init__(self, data_dir: Path, postgres_url: str) -> None:
        super().__init__(postgres_url)
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS knowledge_notes (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        parent_note_id TEXT,
                        graph_episode_uuid TEXT,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_user_idx ON knowledge_notes (user_id, created_at)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_parent_idx ON knowledge_notes (parent_note_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_episode_idx ON knowledge_notes (graph_episode_uuid)"
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS review_cards (
                        id TEXT PRIMARY KEY,
                        note_id TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        due_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS review_cards_note_idx ON review_cards (note_id, due_at)"
                )
            conn.commit()
        self._initialized = True

    def add_note(self, note: KnowledgeNote) -> None:
        self._upsert_note(note)

    def update_note(self, note: KnowledgeNote) -> None:
        self._upsert_note(note)

    def _upsert_note(self, note: KnowledgeNote) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO knowledge_notes
                        (id, user_id, parent_note_id, graph_episode_uuid, payload, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        parent_note_id = EXCLUDED.parent_note_id,
                        graph_episode_uuid = EXCLUDED.graph_episode_uuid,
                        payload = EXCLUDED.payload,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        note.id,
                        note.user_id,
                        note.parent_note_id,
                        note.graph_episode_uuid,
                        Jsonb(note.model_dump(mode="json")),
                        note.created_at,
                        note.updated_at,
                    ),
                )
            conn.commit()

    def add_review(self, review: ReviewCard) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO review_cards (id, note_id, payload, due_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        note_id = EXCLUDED.note_id,
                        payload = EXCLUDED.payload,
                        due_at = EXCLUDED.due_at
                    """,
                    (review.id, review.note_id, Jsonb(review.model_dump(mode="json")), review.due_at),
                )
            conn.commit()

    def list_notes(self, user_id: str, *, include_chunks: bool = True) -> list[KnowledgeNote]:
        self.ensure_schema()
        clause = "" if include_chunks else " AND parent_note_id IS NULL"
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT payload FROM knowledge_notes WHERE user_id = %s{clause} ORDER BY created_at",
                    (user_id,),
                )
                return [KnowledgeNote.model_validate(row["payload"]) for row in cur.fetchall()]

    def get_note(self, note_id: str) -> KnowledgeNote | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM knowledge_notes WHERE id = %s", (note_id,))
                row = cur.fetchone()
        return KnowledgeNote.model_validate(row["payload"]) if row else None

    def get_chunks_for_parent(self, parent_note_id: str) -> list[KnowledgeNote]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM knowledge_notes
                    WHERE parent_note_id = %s
                    ORDER BY (payload->>'chunk_index')::integer NULLS LAST
                    """,
                    (parent_note_id,),
                )
                return [KnowledgeNote.model_validate(row["payload"]) for row in cur.fetchall()]

    def get_parent_note(self, note_id: str) -> KnowledgeNote | None:
        note = self.get_note(note_id)
        if note is None or note.parent_note_id is None:
            return None
        return self.get_note(note.parent_note_id)

    def find_notes_by_graph_episode_uuids(
        self, user_id: str, episode_uuids: list[str]
    ) -> list[KnowledgeNote]:
        if not episode_uuids:
            return []
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM knowledge_notes
                    WHERE user_id = %s AND graph_episode_uuid = ANY(%s)
                    """,
                    (user_id, episode_uuids),
                )
                by_episode = {
                    note.graph_episode_uuid: note
                    for row in cur.fetchall()
                    for note in [KnowledgeNote.model_validate(row["payload"])]
                }
        return [by_episode[item] for item in episode_uuids if item in by_episode]

    def find_similar_notes(self, user_id: str, query: str, limit: int = 3) -> list[KnowledgeNote]:
        tokens = {token.lower() for token in query.split() if token.strip()}
        scored: list[tuple[int, KnowledgeNote]] = []
        for note in self.list_notes(user_id):
            text = f"{note.title} {note.summary} {note.content}".lower()
            score = sum(1 for token in tokens if token in text)
            if score:
                scored.append((score, note))
        scored.sort(key=lambda item: item[0], reverse=True)
        seen_parents: set[str] = set()
        results: list[KnowledgeNote] = []
        for _, note in scored:
            if len(results) >= limit * 2:
                break
            if note.parent_note_id:
                if note.parent_note_id in seen_parents:
                    continue
                seen_parents.add(note.parent_note_id)
                results.append(note)
                parent = self.get_note(note.parent_note_id)
                if parent is not None and parent not in results:
                    results.append(parent)
            else:
                results.append(note)
        return results[:limit]

    def due_reviews(self, user_id: str) -> list[ReviewCard]:
        return [review for review in self.list_reviews(user_id) if review.due_at <= datetime.utcnow()]

    def list_reviews(self, user_id: str) -> list[ReviewCard]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT r.payload FROM review_cards r
                    JOIN knowledge_notes n ON n.id = r.note_id
                    WHERE n.user_id = %s ORDER BY r.due_at
                    """,
                    (user_id,),
                )
                return [ReviewCard.model_validate(row["payload"]) for row in cur.fetchall()]

    def delete_note(self, note_id: str, user_id: str, cascade_chunks: bool = False) -> KnowledgeNote | None:
        target = self.get_note(note_id)
        if target is None or target.user_id != user_id:
            return None
        targets = [target]
        if cascade_chunks:
            targets.extend(note for note in self.get_chunks_for_parent(note_id) if note.user_id == user_id)
        ids = [note.id for note in targets]
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM review_cards WHERE note_id = ANY(%s)", (ids,))
                cur.execute("DELETE FROM knowledge_notes WHERE id = ANY(%s)", (ids,))
            conn.commit()
        self._remove_uploads(targets)
        return target

    def clear_user_data(self, user_id: str, remove_uploaded_files: bool = True) -> dict[str, int]:
        notes = self.list_notes(user_id)
        ids = [note.id for note in notes]
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                if ids:
                    cur.execute("DELETE FROM review_cards WHERE note_id = ANY(%s)", (ids,))
                    removed_reviews = cur.rowcount or 0
                else:
                    removed_reviews = 0
                cur.execute("DELETE FROM knowledge_notes WHERE user_id = %s", (user_id,))
                removed_notes = cur.rowcount or 0
            conn.commit()
        removed_uploads = self._remove_uploads(notes) if remove_uploaded_files else 0
        return {
            "notes": int(removed_notes),
            "reviews": int(removed_reviews),
            "conversations": 0,
            "uploads": removed_uploads,
        }

    def _remove_uploads(self, notes: list[KnowledgeNote]) -> int:
        uploads_dir = (self.data_dir / "uploads").resolve()
        removed = 0
        for note in notes:
            if not note.source_ref:
                continue
            try:
                source_path = Path(note.source_ref).resolve()
                if _is_relative_to(source_path, uploads_dir) and source_path.is_file():
                    source_path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import KnowledgeNote, ReviewCard


class LocalMemoryStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.notes_file = data_dir / "notes.json"
        self.reviews_file = data_dir / "reviews.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_files()

    def _ensure_files(self) -> None:
        for file_path in (self.notes_file, self.reviews_file):
            if not file_path.exists():
                file_path.write_text("[]", encoding="utf-8")

    def _load_notes(self) -> list[KnowledgeNote]:
        raw = json.loads(self.notes_file.read_text(encoding="utf-8"))
        return [KnowledgeNote.model_validate(item) for item in raw]

    def _save_notes(self, notes: list[KnowledgeNote]) -> None:
        payload = [note.model_dump(mode="json") for note in notes]
        self.notes_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_reviews(self) -> list[ReviewCard]:
        raw = json.loads(self.reviews_file.read_text(encoding="utf-8"))
        return [ReviewCard.model_validate(item) for item in raw]

    def _save_reviews(self, reviews: list[ReviewCard]) -> None:
        payload = [review.model_dump(mode="json") for review in reviews]
        self.reviews_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_note(self, note: KnowledgeNote) -> None:
        notes = self._load_notes()
        notes.append(note)
        self._save_notes(notes)

    def update_note(self, note: KnowledgeNote) -> None:
        notes = self._load_notes()
        updated: list[KnowledgeNote] = []
        replaced = False
        for existing in notes:
            if existing.id == note.id:
                updated.append(note)
                replaced = True
            else:
                updated.append(existing)
        if not replaced:
            updated.append(note)
        self._save_notes(updated)

    def add_review(self, review: ReviewCard) -> None:
        reviews = self._load_reviews()
        reviews.append(review)
        self._save_reviews(reviews)

    def list_notes(self, user_id: str) -> list[KnowledgeNote]:
        return [note for note in self._load_notes() if note.user_id == user_id]

    def get_note(self, note_id: str) -> KnowledgeNote | None:
        for note in self._load_notes():
            if note.id == note_id:
                return note
        return None

    def find_notes_by_graph_episode_uuids(
        self, user_id: str, episode_uuids: list[str]
    ) -> list[KnowledgeNote]:
        wanted = set(episode_uuids)
        if not wanted:
            return []
        note_by_episode_uuid = {
            note.graph_episode_uuid: note
            for note in self.list_notes(user_id)
            if note.graph_episode_uuid is not None and note.graph_episode_uuid in wanted
        }
        ordered_notes: list[KnowledgeNote] = []
        seen_note_ids: set[str] = set()
        for episode_uuid in episode_uuids:
            note = note_by_episode_uuid.get(episode_uuid)
            if note is None or note.id in seen_note_ids:
                continue
            seen_note_ids.add(note.id)
            ordered_notes.append(note)
        return ordered_notes

    def find_similar_notes(self, user_id: str, query: str, limit: int = 3) -> list[KnowledgeNote]:
        tokens = {token.lower() for token in query.split() if token.strip()}
        scored: list[tuple[int, KnowledgeNote]] = []
        for note in self.list_notes(user_id):
            haystack = f"{note.title} {note.summary} {note.content}".lower()
            score = sum(1 for token in tokens if token in haystack)
            if score > 0:
                scored.append((score, note))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [note for _, note in scored[:limit]]

    def due_reviews(self, user_id: str) -> list[ReviewCard]:
        now = datetime.utcnow()
        return [
            review
            for review in self._load_reviews()
            if review.due_at <= now and self._note_belongs_to_user(review.note_id, user_id)
        ]

    def list_reviews(self, user_id: str) -> list[ReviewCard]:
        return [
            review
            for review in self._load_reviews()
            if self._note_belongs_to_user(review.note_id, user_id)
        ]

    def _note_belongs_to_user(self, note_id: str, user_id: str) -> bool:
        return any(note.id == note_id and note.user_id == user_id for note in self._load_notes())

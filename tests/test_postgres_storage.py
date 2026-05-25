from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from personal_agent.core.models import Citation, KnowledgeNote, PendingAction, ReviewCard
from personal_agent.storage.postgres_cross_session_store import PostgresCrossSessionStore
from personal_agent.storage.postgres_memory_store import PostgresMemoryStore
from personal_agent.storage.postgres_pending_action_store import PostgresPendingActionStore
from tests.conftest import POSTGRES_URL

import pytest

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


def _user() -> str:
    return f"pytest-{uuid4().hex}"


def test_notes_and_reviews_are_persisted_in_postgres(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    note = KnowledgeNote(id=str(uuid4()), title="测试", content="内容", summary="摘要", user_id=user_id)
    store.add_note(note)
    store.add_review(
        ReviewCard(note_id=note.id, prompt="复习", answer_hint="答案", due_at=datetime.utcnow() - timedelta(days=1))
    )

    reloaded = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    assert reloaded.get_note(note.id).title == "测试"
    assert len(reloaded.due_reviews(user_id)) == 1

    result = reloaded.clear_user_data(user_id, remove_uploaded_files=False)
    assert result["notes"] == 1
    assert result["reviews"] == 1


def test_note_chunks_and_episode_mapping_are_persisted(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    parent = KnowledgeNote(id=str(uuid4()), title="父", content="全文", summary="摘要", user_id=user_id)
    child = KnowledgeNote(
        id=str(uuid4()),
        title="子",
        content="片段",
        summary="片段摘要",
        user_id=user_id,
        parent_note_id=parent.id,
        chunk_index=1,
        graph_episode_uuid=str(uuid4()),
    )
    store.add_note(parent)
    store.add_note(child)

    assert store.get_chunks_for_parent(parent.id)[0].id == child.id
    assert store.find_notes_by_graph_episode_uuids(user_id, [child.graph_episode_uuid])[0].id == child.id
    store.clear_user_data(user_id, remove_uploaded_files=False)


def test_pending_actions_are_database_backed():
    user_id = _user()
    store = PostgresPendingActionStore(POSTGRES_URL)
    action = store.create(
        PendingAction(
            user_id=user_id,
            action_type="delete_note",
            target_id="note-1",
            title="删除笔记",
            description="测试",
        )
    )

    confirmed = store.confirm(action.id, action.token, user_id)
    assert confirmed is not None and confirmed.status == "confirmed"
    assert store.mark_executed(action.id, user_id).status == "executed"
    assert store.clear_user(user_id) == 1


def test_cross_session_artifacts_are_database_backed():
    user_id = _user()
    store = PostgresCrossSessionStore(POSTGRES_URL)
    draft_id = store.save_draft(user_id, "草稿", source_context="ctx")
    conclusion_id = store.add_conclusion(user_id, "结论", "session-1")
    store.add_citations(user_id, [Citation(note_id="n1", title="笔记", snippet="片段")], "问题")

    assert store.get_draft(user_id, draft_id)["text"] == "草稿"
    assert store.mark_draft_status(user_id, draft_id, "solidified")
    assert store.mark_conclusion_solidified(user_id, conclusion_id)
    assert store.recent_citations(user_id)[0]["note_id"] == "n1"
    assert store.clear_user(user_id) == 3

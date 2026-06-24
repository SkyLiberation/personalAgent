from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from personal_agent.kernel.models import MemoryEpisode, MemoryItem, ReviewCard
from personal_agent.kernel.query_understanding import RetrievalFilters
from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
from tests.conftest import POSTGRES_URL
from tests.note_factory import make_note

import pytest

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


def _user() -> str:
    return f"pytest-{uuid4().hex}"


def test_notes_and_reviews_are_persisted_in_postgres(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    note = make_note(id=str(uuid4()), title="测试", content="内容", summary="摘要", user_id=user_id)
    store.add_note(note)
    store.add_review(
        ReviewCard(note_id=note.id, prompt="复习", answer_hint="答案", due_at=datetime.utcnow() - timedelta(days=1))
    )

    reloaded = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    assert reloaded.get_note(note.id).body.title == "测试"
    assert len(reloaded.due_reviews(user_id)) == 1

    result = reloaded.clear_user_data(user_id, remove_uploaded_files=False)
    assert result["notes"] == 1
    assert result["reviews"] == 1


def test_note_chunks_and_episode_mapping_are_persisted(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    parent = make_note(id=str(uuid4()), title="父", content="全文", summary="摘要", user_id=user_id)
    child = make_note(
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
    assert store.find_notes_by_graph_episode_uuids(user_id, [child.graph.episode_uuid])[0].id == child.id
    store.clear_user_data(user_id, remove_uploaded_files=False)


def test_find_note_by_source_fingerprint_prefers_parent(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    fingerprint = "fp-" + uuid4().hex
    parent = make_note(
        id=str(uuid4()),
        title="来源文章",
        content="全文",
        summary="摘要",
        user_id=user_id,
        source_ref="https://example.com/source",
        source_fingerprint=fingerprint,
        metadata={"title": "来源文章", "author": "tester"},
    )
    child = make_note(
        id=str(uuid4()),
        title="来源文章片段",
        content="片段",
        summary="片段摘要",
        user_id=user_id,
        parent_note_id=parent.id,
        chunk_index=1,
        source_fingerprint=fingerprint,
    )
    store.add_note(parent)
    store.add_note(child)

    found = store.find_note_by_source_fingerprint(user_id, fingerprint)

    assert found is not None
    assert found.id == parent.id
    assert found.source.metadata["author"] == "tester"
    store.clear_user_data(user_id, remove_uploaded_files=False)


def test_find_similar_notes_supports_chinese_bm25_search(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    target = make_note(
        id=str(uuid4()),
        title="服务降级",
        content="服务降级是在系统压力过大时主动关闭非核心能力。",
        summary="系统压力过大时关闭非核心能力",
        user_id=user_id,
    )
    distractor = make_note(
        id=str(uuid4()),
        title="缓存策略",
        content="缓存策略用于减少数据库访问。",
        summary="缓存优化",
        user_id=user_id,
    )
    store.add_note(target)
    store.add_note(distractor)

    matches = store.find_similar_notes(user_id, "什么是服务降级", limit=5)

    assert matches
    assert matches[0].id == target.id
    assert all(match.user_id == user_id for match in matches)
    store.clear_user_data(user_id, remove_uploaded_files=False)


def test_find_similar_notes_applies_metadata_filters(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    link_note = make_note(
        id=str(uuid4()),
        title="RAG 链接",
        content="RAG 检索增强生成资料。",
        summary="RAG 资料",
        user_id=user_id,
        source_type="link",
        source_ref="https://example.com/rag",
        metadata={"author": "alice"},
    )
    file_note = make_note(
        id=str(uuid4()),
        title="RAG 文件",
        content="RAG 检索增强生成资料。",
        summary="RAG 文件",
        user_id=user_id,
        source_type="file",
        source_ref="D:/uploads/rag.md",
        metadata={"author": "bob"},
    )
    store.add_note(link_note)
    store.add_note(file_note)

    link_matches = store.find_similar_notes(
        user_id,
        "RAG 检索增强",
        filters=RetrievalFilters(source_types=["link"]),
    )
    file_matches = store.find_similar_notes(
        user_id,
        "RAG 检索增强",
        filters=RetrievalFilters(source_ref_contains="rag.md", metadata_contains="bob"),
    )

    assert [note.id for note in link_matches] == [link_note.id]
    assert [note.id for note in file_matches] == [file_note.id]
    store.clear_user_data(user_id, remove_uploaded_files=False)


def test_graph_episode_lookup_applies_filters(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    link_episode = str(uuid4())
    file_episode = str(uuid4())
    link_note = make_note(
        id=str(uuid4()),
        title="链接笔记",
        content="Graphiti 资料",
        summary="链接",
        user_id=user_id,
        source_type="link",
        graph_episode_uuid=link_episode,
    )
    file_note = make_note(
        id=str(uuid4()),
        title="文件笔记",
        content="Graphiti 资料",
        summary="文件",
        user_id=user_id,
        source_type="file",
        graph_episode_uuid=file_episode,
    )
    store.add_note(link_note)
    store.add_note(file_note)

    matches = store.find_notes_by_graph_episode_uuids(
        user_id,
        [link_episode, file_episode],
        filters=RetrievalFilters(source_types=["file"]),
    )

    assert [note.id for note in matches] == [file_note.id]
    store.clear_user_data(user_id, remove_uploaded_files=False)


def test_find_similar_notes_expands_chunk_to_parent_and_neighbors(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    parent = make_note(
        id=str(uuid4()),
        title="RAG 架构文档",
        content="完整文档",
        summary="RAG 总览",
        user_id=user_id,
        chunk_index=0,
    )
    chunk1 = make_note(
        id=str(uuid4()),
        title="检索",
        content="向量检索负责语义召回。",
        summary="向量检索",
        user_id=user_id,
        parent_note_id=parent.id,
        chunk_index=1,
    )
    chunk2 = make_note(
        id=str(uuid4()),
        title="重排",
        content="Cross encoder rerank 负责统一精排候选证据。",
        summary="统一重排",
        user_id=user_id,
        parent_note_id=parent.id,
        chunk_index=2,
    )
    chunk3 = make_note(
        id=str(uuid4()),
        title="生成",
        content="生成阶段只使用 ContextPack。",
        summary="上下文生成",
        user_id=user_id,
        parent_note_id=parent.id,
        chunk_index=3,
    )
    for note in (parent, chunk1, chunk2, chunk3):
        store.add_note(note)

    matches = store.find_similar_notes(user_id, "rerank 精排候选证据", limit=5)
    ids = [note.id for note in matches]

    assert chunk2.id in ids
    assert parent.id in ids
    assert chunk1.id in ids or chunk3.id in ids
    store.clear_user_data(user_id, remove_uploaded_files=False)


def test_find_similar_notes_merges_vector_only_candidates(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)

    def vector_at(index: int) -> list[float]:
        vector = [0.0] * 128
        vector[index] = 1.0
        return vector

    vectors = {
        "alpha document": vector_at(0),
        "beta document": vector_at(1),
        "semantic query": vector_at(0),
        "other": vector_at(2),
    }

    def fake_embed(text: str) -> list[float]:
        if "alpha unique body" in text:
            return vectors["alpha document"]
        if "beta unique body" in text:
            return vectors["beta document"]
        if text == "no lexical overlap":
            return vectors["semantic query"]
        return vectors["other"]

    store._embed_text = fake_embed  # type: ignore[method-assign]
    target = make_note(
        id=str(uuid4()),
        title="Alpha",
        content="alpha unique body",
        summary="first",
        user_id=user_id,
    )
    distractor = make_note(
        id=str(uuid4()),
        title="Beta",
        content="beta unique body",
        summary="second",
        user_id=user_id,
    )
    store.add_note(target)
    store.add_note(distractor)

    matches = store.find_similar_notes(user_id, "no lexical overlap", limit=3)

    assert matches
    assert matches[0].id == target.id
    store.clear_user_data(user_id, remove_uploaded_files=False)


def test_find_similar_notes_emits_retrieval_metrics(temp_dir: Path, monkeypatch):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    events: list[dict[str, object]] = []

    def capture_event(_logger, _level, event_name, **payload):
        events.append({"event": event_name, **payload})

    monkeypatch.setattr(
        "personal_agent.infra.storage.postgres_memory_store.log_event",
        capture_event,
    )
    store.add_note(
        make_note(
            id=str(uuid4()),
            title="Redis cache",
            content="Redis cache protects hot order reads.",
            summary="cache",
            user_id=user_id,
        )
    )

    matches = store.find_similar_notes(user_id, "Redis cache", limit=3)

    retrieval_events = [event for event in events if event["event"] == "retrieval.local"]
    assert matches
    assert retrieval_events
    assert retrieval_events[-1]["query_chars"] == len("Redis cache")
    assert retrieval_events[-1]["result_count"] == len(matches)
    assert retrieval_events[-1]["filters_active"] is False
    store.clear_user_data(user_id, remove_uploaded_files=False)


def test_find_similar_notes_excludes_superseded_and_deprecated_notes(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    old = make_note(
        id="old",
        title="部署流程旧版",
        content="部署流程使用 Jenkins。",
        summary="Jenkins",
        user_id=user_id,
        version_status="superseded",
        superseded_by_note_id="new",
    )
    deprecated = make_note(
        id="deprecated",
        title="部署流程废弃版",
        content="部署流程使用手工上传。",
        summary="手工上传",
        user_id=user_id,
        version_status="deprecated",
    )
    new = make_note(
        id="new",
        title="部署流程新版",
        content="部署流程使用 GitHub Actions。",
        summary="GitHub Actions",
        user_id=user_id,
    )
    for note in (old, deprecated, new):
        store.add_note(note)

    matches = store.find_similar_notes(user_id, "部署流程 使用", limit=10)

    assert [note.id for note in matches] == ["new"]


def test_graph_episode_lookup_excludes_superseded_notes(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    old = make_note(
        id="old",
        title="旧图谱",
        content="旧事实",
        summary="旧",
        user_id=user_id,
        graph_episode_uuid="ep-old",
        version_status="superseded",
        superseded_by_note_id="new",
    )
    new = make_note(
        id="new",
        title="新图谱",
        content="新事实",
        summary="新",
        user_id=user_id,
        graph_episode_uuid="ep-new",
    )
    store.add_note(old)
    store.add_note(new)

    matches = store.find_notes_by_graph_episode_uuids(user_id, ["ep-old", "ep-new"])

    assert [note.id for note in matches] == ["new"]


def test_memory_episodes_are_persisted_and_searchable(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    episode = MemoryEpisode(
        id=f"episode:{uuid4().hex}",
        user_id=user_id,
        session_id="s1",
        thread_id=f"{user_id}:s1",
        run_id="run-episode-search",
        workflow="delete_knowledge",
        title="删除知识: Graphiti 清理",
        summary="用户确认删除 Graphiti 笔记，并清理图谱 episode。",
        outcome="completed",
        entry_text="删除 Graphiti 笔记",
        decisions=["识别意图为 delete_knowledge，风险 high"],
        tool_refs=["delete_note"],
        note_refs=["note-graphiti"],
    )

    store.add_episode(episode)

    listed = store.list_episodes(user_id, session_id="s1")
    matches = store.search_episodes(user_id, "上次删除 Graphiti 做了什么", session_id="s1")

    assert listed[0].id == episode.id
    assert matches
    assert matches[0].id == episode.id

    result = store.clear_user_data(user_id, remove_uploaded_files=False)
    assert result["episodes"] == 1


def test_memory_items_are_persisted_and_searchable(temp_dir: Path):
    user_id = _user()
    store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
    item = MemoryItem(
        id="proc-1",
        memory_type="procedural",
        user_id=user_id,
        title="发布流程偏好",
        content="用户偏好先跑单元测试，再执行灰度发布。",
        status="confirmed",
        confidence=0.9,
        applies_to=["release"],
    )
    reflection = MemoryItem(
        id="refl-1",
        memory_type="reflection",
        user_id=user_id,
        title="失败复盘",
        content="删除目标不明确时应先让用户选择候选。",
        status="candidate",
        applies_to=["delete_knowledge"],
    )

    store.add_memory_item(item)
    store.add_memory_item(reflection)

    procedural = store.search_memory_items(user_id, "先跑单元测试", memory_type="procedural")
    reflections = store.list_memory_items(user_id, memory_type="reflection", status="candidate")

    assert procedural[0].id == "proc-1"
    assert reflections[0].id == "refl-1"

    result = store.clear_user_data(user_id, remove_uploaded_files=False)
    assert result["memory_items"] == 2

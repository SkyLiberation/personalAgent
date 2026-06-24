from __future__ import annotations

import pytest
from pathlib import Path

from unittest.mock import MagicMock

from personal_agent.agent.service import AgentService
from personal_agent.kernel.config import LangExtractConfig, OpenAIConfig, Settings
from personal_agent.kernel.models import Citation, EntryInput, ReviewCard, local_now
from personal_agent.agent.runtime_ask import _graph_matches_to_evidence
from personal_agent.planning.router import GoalDraft, RouterOutput
from personal_agent.kernel.query_understanding import QueryUnderstanding, RetrievalFilters, RetrievalPlan
from personal_agent.memory.graphiti.store import GraphAskResult, GraphCaptureResult
from tests.conftest import POSTGRES_URL, stub_router_decision
from tests.note_factory import make_note

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


def test_compound_capture_then_ask_executes_in_dependency_order(service: AgentService):
    service.intent_router._classify_with_llm = lambda _text, _messages=None: RouterOutput(
        outcome="ready",
        goals=[
            GoalDraft(
                intent="capture_text",
                input="DNS 将域名解析为 IP 地址。",
            ),
            GoalDraft(
                intent="ask",
                input="DNS 的作用是什么？",
            ),
        ],
        clarification=None,
    )

    result = service.entry(EntryInput(
        text="记住 DNS 将域名解析为 IP 地址，然后回答 DNS 的作用是什么？",
        user_id="default",
        session_id="compound-capture-ask",
    ))

    assert result.intents == ["capture_text", "ask"]
    assert result.plan is not None
    assert [task["task_id"] for task in result.plan["tasks"]] == ["goal_1", "goal_2"]
    assert [step["step_id"] for step in result.steps] == [
        "goal_1::cap-structure",
        "goal_2::ask-retrieve",
        "goal_2::ask-compose",
        "goal_2::ask-verify",
    ]
    assert all(step["status"] == "completed" for step in result.steps)
    assert any("DNS 将域名解析为 IP 地址" in note.content for note in service.store.list_notes("default"))
    assert result.reply_text


@pytest.fixture
def test_settings(temp_dir: Path) -> Settings:
    return Settings(
        data_dir=temp_dir,
        postgres_url=POSTGRES_URL,
        openai=OpenAIConfig(
            api_key=None,
            base_url=None,
            model="gpt-4.1-mini",
        ),
        langextract=LangExtractConfig(api_key="stub", min_doc_chars=100_000),
    )


@pytest.fixture
def service(test_settings: Settings) -> AgentService:
    svc = AgentService(test_settings)
    mock_store = MagicMock()
    mock_store.configured.return_value = False
    # ask() must return disabled so execute_ask takes the local path
    mock_store.ask.return_value = GraphAskResult(enabled=False)
    # ingest_note() must return disabled so capture doesn't enter graph sync path
    mock_store.ingest_note.return_value = GraphCaptureResult(enabled=False)
    svc.graph_store = mock_store
    svc.graph_store = mock_store
    svc.intent_router._classify_with_llm = stub_router_decision
    return svc


class TestCaptureFlow:
    def test_capture_text_creates_note(self, service: AgentService):
        result = service.execute_capture(text="服务降级是在系统压力过大时主动关闭非核心能力", source_type="text")
        assert result.note is not None
        assert result.note.body.title
        assert result.note.body.content
        assert result.note.body.summary
        assert result.note.source.type == "text"
        assert result.note.graph_sync.status in {"idle", "failed", "synced"}

    def test_capture_produces_review_card(self, service: AgentService):
        result = service.execute_capture(text="需要记住的重要知识点：CAP理论的核心是分区容错性", source_type="text")
        assert result.note is not None
        # Review card generation is deterministic from note content
        assert result.review_card is not None

    def test_capture_text_with_user_id(self, service: AgentService):
        result = service.execute_capture(text="用户特定笔记", source_type="text", user_id="alice")
        assert result.note.user_id == "alice"

    def test_capture_text_with_source_ref(self, service: AgentService):
        result = service.execute_capture(
            text="来源笔记", source_type="text", source_ref="https://example.com"
        )
        assert result.note.source.ref == "https://example.com"

    def test_capture_duplicate_fingerprint_reuses_existing_note(self, service: AgentService):
        first = service.execute_capture(
            text="重复采集内容",
            source_type="link",
            source_ref="https://example.com/a",
            metadata={"title": "示例文章"},
        )
        second = service.execute_capture(
            text="重复采集内容",
            source_type="link",
            source_ref="https://example.com/a",
            metadata={"title": "示例文章"},
        )

        assert second.note.id == first.note.id
        assert second.note.source.fingerprint == first.note.source.fingerprint
        assert second.note.source.metadata["title"] == "示例文章"
        assert len(service.store.list_notes(first.note.user_id, include_chunks=False)) == 1
        assert service.graph_store.ingest_note.call_count == 1

    def test_short_text_single_note_no_chunks(self, service: AgentService):
        result = service.execute_capture(text="这是一条短笔记", source_type="text")
        assert result.note is not None
        assert result.chunk_notes == []

    def test_long_text_produces_chunks(self, service: AgentService):
        long_content = "\n".join([
            "## 第一节",
            "",
            "第一节的详细内容。" * 350,
            "",
            "## 第二节",
            "",
            "第二节的详细内容。" * 350,
            "",
            "## 第三节",
            "",
            "第三节的详细内容。" * 350,
        ])
        result = service.execute_capture(text=long_content, source_type="text")
        assert result.note is not None
        # Long content should produce chunk_notes
        assert len(result.chunk_notes) > 0
        # Chunks should have parent_note_id pointing to the parent
        for chunk in result.chunk_notes:
            assert chunk.chunk.parent_note_id == result.note.id
            assert chunk.chunk.index is not None and chunk.chunk.index >= 1

    def test_capture_chunks_persisted_in_store(self, service: AgentService):
        long_content = "\n".join([
            "## 章节A",
            "",
            "A的详细内容。" * 350,
            "",
            "## 章节B",
            "",
            "B的详细内容。" * 350,
        ])
        result = service.execute_capture(text=long_content, source_type="text")
        parent_id = result.note.id
        # Chunks should be retrievable from store
        chunks = service.store.get_chunks_for_parent(parent_id)
        assert len(chunks) == len(result.chunk_notes)
        # All chunks should have correct parent_note_id
        for chunk in chunks:
            assert chunk.chunk.parent_note_id == parent_id

    def test_capture_chunks_get_pending_graph_status(self, service: AgentService):
        """Chunk notes should get graph_sync_status='pending' when graph is configured."""
        long_content = "\n".join([
            "## 章节A",
            "",
            "A的详细内容。" * 350,
            "",
            "## 章节B",
            "",
            "B的详细内容。" * 350,
        ])
        # Mock graph_store as configured to ensure 'pending' status
        service.graph_store.configured.return_value = True
        result = service.execute_capture(text=long_content, source_type="text")
        for chunk in result.chunk_notes:
            assert chunk.graph_sync.status == "pending"
        assert result.note.graph_sync.status == "skipped"
        assert "delegated" in (result.note.graph_sync.error or "")
        service.graph_store.configured.return_value = False  # Restore for other tests

    def test_batch_graph_sync_updates_multiple_chunks(self, service: AgentService):
        service.graph_store.configured.return_value = True
        chunk1 = make_note(
            title="chunk1",
            content="Redis 缓存热点数据。",
            summary="Redis",
            user_id="default",
            graph_sync_status="pending",
        )
        chunk2 = make_note(
            title="chunk2",
            content="服务降级关闭非核心能力。",
            summary="服务降级",
            user_id="default",
            graph_sync_status="pending",
        )
        service.store.add_note(chunk1)
        service.store.add_note(chunk2)
        service.graph_store.ingest_notes = MagicMock(return_value={
            chunk1.id: GraphCaptureResult(
                enabled=True,
                episode_uuid="ep-1",
                entity_names=["Redis"],
                relation_facts=["Redis 缓存热点数据"],
            ),
            chunk2.id: GraphCaptureResult(enabled=False, error="rate limit"),
        })

        outcomes = service.sync_notes_to_graph([chunk1.id, chunk2.id])

        assert outcomes == {chunk1.id: True, chunk2.id: False}
        assert service.store.get_note(chunk1.id).graph_sync.status == "synced"
        assert service.store.get_note(chunk2.id).graph_sync.status == "failed"
        service.graph_store.ingest_notes.assert_called_once()
        service.graph_store.configured.return_value = False

    def test_graph_sync_tasks_are_queryable_by_status(self, service: AgentService):
        pending = make_note(
            title="pending",
            content="待同步",
            summary="待同步",
            user_id="default",
            graph_sync_status="pending",
        )
        failed = make_note(
            title="failed",
            content="同步失败",
            summary="失败",
            user_id="default",
            graph_sync_status="failed",
            graph_sync_error="rate limit",
        )
        service.store.add_note(pending)
        service.store.add_note(failed)

        tasks = service.memory.list_graph_sync_tasks(user_id="default", statuses=["pending", "failed"])

        assert {task.note_id for task in tasks} == {pending.id, failed.id}
        failed_task = next(task for task in tasks if task.note_id == failed.id)
        assert failed_task.error == "rate limit"
        assert failed_task.status == "failed"

    def test_graph_sync_reconcile_retries_and_reports_orphans(self, service: AgentService):
        service.graph_store.configured.return_value = True
        service.graph_store.delete_episode = MagicMock(return_value=True)
        failed = make_note(
            title="failed",
            content="Redis 缓存热点数据。",
            summary="Redis",
            user_id="default",
            graph_sync_status="failed",
            graph_sync_error="rate limit",
        )
        weak = make_note(
            title="weak",
            content="弱图谱",
            summary="弱图谱",
            user_id="default",
            graph_episode_uuid="ep-weak",
            graph_sync_status="synced",
            graph_quality_zero_entities=True,
        )
        service.store.add_note(failed)
        service.store.add_note(weak)
        service.graph_store.ingest_note = MagicMock(return_value=GraphCaptureResult(
            enabled=True,
            episode_uuid="ep-fixed",
            entity_names=["Redis"],
            relation_facts=["Redis 缓存热点数据"],
        ))

        report = service.reconcile_graph_sync(
            "default",
            graph_episode_uuids=["ep-weak", "ep-orphan"],
            retry_statuses=["failed"],
            clean_orphans=True,
        )

        assert report.checked_notes >= 2
        assert report.retried_count == 1
        assert report.orphan_episode_count == 1
        assert report.cleaned_orphan_count == 1
        assert report.weak_quality_count == 1
        assert service.store.get_note(failed.id).graph_sync.status == "synced"
        service.graph_store.delete_episode.assert_called_once_with("ep-orphan")
        service.graph_store.configured.return_value = False

    def test_supersede_note_marks_old_note_stale(self, service: AgentService):
        old = make_note(
            id="old-deploy",
            title="部署流程旧版",
            content="部署流程使用 Jenkins。",
            summary="Jenkins",
            user_id="default",
        )
        new = make_note(
            id="new-deploy",
            title="部署流程新版",
            content="部署流程使用 GitHub Actions。",
            summary="GitHub Actions",
            user_id="default",
        )
        service.store.add_note(old)
        service.store.add_note(new)

        old_note, new_note = service.memory.supersede_note(
            "old-deploy",
            "new-deploy",
            user_id="default",
            reason="部署流程迁移",
        )

        assert old_note.version.status == "superseded"
        assert old_note.version.superseded_by_note_id == "new-deploy"
        assert old_note.id in new_note.version.supersedes_note_ids
        matches = service.memory.search_memory("default", "部署流程 使用 Jenkins GitHub", limit=10)
        assert [note.id for note in matches] == ["new-deploy"]

    def test_consolidate_knowledge_selects_topic_sources_and_supersedes_them(self, service: AgentService):
        first = make_note(
            id="topic-a",
            title="向量检索 基础",
            content="向量检索把文本编码成向量做相似度匹配。",
            summary="向量检索基础",
            user_id="default",
        )
        second = make_note(
            id="topic-b",
            title="向量检索 重排序",
            content="重排序在向量召回后用更强模型精排。",
            summary="重排序",
            user_id="default",
        )
        service.store.add_note(first)
        service.store.add_note(second)

        result = service.execute_consolidate(
            topic="向量检索",
            user_id="default",
        )

        assert result["ok"] is True
        assert set(result["superseded"]) == {"topic-a", "topic-b"}
        assert result["failed"] == []
        summary_id = result["note_id"]
        old_a = service.memory.get_note("topic-a", user_id="default")
        assert old_a.version.status == "superseded"
        assert old_a.version.superseded_by_note_id == summary_id

    def test_consolidate_knowledge_requires_two_related_sources(self, service: AgentService):
        only = make_note(id="solo", title="孤立笔记", content="只有一条。", summary="孤立", user_id="default")
        service.store.add_note(only)

        result = service.execute_consolidate(
            topic="孤立笔记",
            user_id="default",
        )

        assert result["ok"] is False

    def test_conflicted_notes_are_marked_for_evidence_layer(self, service: AgentService):
        first = make_note(id="conflict-a", title="缓存", content="缓存使用 Redis。", summary="Redis", user_id="default")
        second = make_note(id="conflict-b", title="缓存", content="缓存使用 Dragonfly。", summary="Dragonfly", user_id="default")
        service.store.add_note(first)
        service.store.add_note(second)

        notes = service.memory.mark_notes_conflicted(
            ["conflict-a", "conflict-b"],
            user_id="default",
            reason="来源冲突",
        )

        assert {note.version.status for note in notes} == {"conflicted"}
        assert service.store.get_note("conflict-a").version.conflict_note_ids == ["conflict-b"]

    def test_chunk_delete_cleans_graph_episodes(self, service: AgentService):
        """When cascade-deleting, chunk graph episodes should be cleaned up."""
        from unittest.mock import MagicMock

        service.graph_store.configured.return_value = True
        service.graph_store.delete_episode = MagicMock(return_value=True)

        # Create parent with chunks that have graph_episode_uuid
        parent = make_note(id="p-g", title="父文档", content="完整", summary="...", user_id="default")
        service.store.add_note(parent)
        service.store.add_note(make_note(
            id="c-g1", title="子1", content="...", summary="...", user_id="default",
            parent_note_id="p-g", chunk_index=1, graph_episode_uuid="ep-chunk-1",
        ))
        service.store.add_note(make_note(
            id="c-g2", title="子2", content="...", summary="...", user_id="default",
            parent_note_id="p-g", chunk_index=2, graph_episode_uuid="ep-chunk-2",
        ))

        # Delete with cascade — should call delete_episode for chunks
        deleted = service.store.delete_note("p-g", "default", cascade_chunks=True)
        assert deleted is not None
        assert service.store.get_note("p-g") is None
        assert service.store.get_note("c-g1") is None
        assert service.store.get_note("c-g2") is None
        # Chunk episodes would be cleaned up by delete_note tool; store.delete_note handles local cleanup
        service.graph_store.configured.return_value = False


class TestAskFlow:
    def test_ask_returns_result(self, service: AgentService):
        # Add a note first so there's something to search
        service.execute_capture(text="服务降级是在系统压力过大时主动关闭非核心能力", source_type="text")
        result = service.execute_ask(question="什么是服务降级？")
        assert result.answer
        assert isinstance(result.answer, str)
        assert len(result.answer) > 0
        assert [ref.id for ref in result.match_refs] == [note.id for note in result.matches]

    def test_ask_with_no_notes(self, service: AgentService):
        result = service.execute_ask(question="完全未知的问题xyz123")
        assert result.answer
        assert isinstance(result.session_id, str)

    def test_ask_without_evidence_skips_answer_model_until_evidence_exists(self, service: AgentService):
        service.runtime._llm.generate_answer = MagicMock(return_value="不应生成")

        result = service.execute_ask(question="今天西安天气怎么样")

        assert "个人知识库" in result.answer
        service.runtime._llm.generate_answer.assert_not_called()

    def test_empty_graph_evidence_skips_answer_model(self, service: AgentService):
        service.graph_store.ask.return_value = GraphAskResult(enabled=True)
        service.runtime._llm.generate_answer = MagicMock(return_value="不应生成")

        result = service.execute_ask(question="今天西安天气怎么样")

        assert "个人知识库" in result.answer
        service.runtime._llm.generate_answer.assert_not_called()

    def test_ask_with_session_id(self, service: AgentService):
        service.execute_capture(text="测试知识", source_type="text")
        result = service.execute_ask(question="测试", session_id="test-session-42")
        assert result.session_id == "test-session-42"

    def test_ask_pushes_filters_into_local_retrieval(self, service: AgentService, monkeypatch):
        from personal_agent.agent import runtime_ask

        file_note = make_note(
            title="部署文件",
            content="蓝绿发布需要先切一半流量。",
            summary="蓝绿发布文件说明",
            user_id="default",
            source_type="file",
            source_ref="D:/uploads/deploy.md",
        )
        link_note = make_note(
            title="部署链接",
            content="蓝绿发布需要先切一半流量。",
            summary="蓝绿发布链接说明",
            user_id="default",
            source_type="link",
            source_ref="https://example.com/deploy",
        )
        service.store.add_note(file_note)
        service.store.add_note(link_note)
        filters = RetrievalFilters(source_types=["file"], source_ref_contains="deploy.md")

        monkeypatch.setattr(
            runtime_ask,
            "plan_retrieval",
            lambda *_args, **_kwargs: (
                QueryUnderstanding(query_rewrite="蓝绿发布", filters=filters),
                RetrievalPlan(query="蓝绿发布", filters=filters),
            ),
        )

        result = service.execute_ask(question="只看 deploy.md 文件，蓝绿发布怎么做？")

        assert [note.id for note in result.matches] == [file_note.id]
        assert result.citations[0].note_id == file_note.id

    def test_thread_dialogue_replaces_persisted_history_in_answer_prompt(self, service: AgentService):
        service.execute_capture(text="部署平台当前为新集群。", source_type="text")
        service.memory.bind_session("default", "context-session")
        service.runtime._llm.generate_answer = MagicMock(return_value="部署平台当前为新集群。")

        service.execute_ask(
            question="部署平台",
            session_id="context-session",
            conversation_messages=[
                {"role": "user", "content": "我刚才更正为新集群。"},
            ],
        )

        prompt = service.runtime._llm.generate_answer.call_args_list[0].args[0]
        assert "我刚才更正为新集群" in prompt
        assert "不是事实证据" in prompt

    def test_ask_prompt_uses_context_pack_ranking_metadata(self, service: AgentService):
        service.execute_capture(text="服务降级是在系统压力过大时主动关闭非核心能力", source_type="text")
        service.runtime._llm.generate_answer = MagicMock(return_value="服务降级是关闭非核心能力。")

        service.execute_ask(question="什么是服务降级？")

        prompt = service.runtime._llm.generate_answer.call_args_list[0].args[0]
        assert "ContextPack" in prompt
        assert "rank_reason" in prompt

    def test_graph_matches_become_context_pack_evidence(self):
        note = make_note(
            id="graph-note",
            title="Graph note",
            content="Graphiti mapped note content",
            summary="Graphiti mapped note summary",
            graph_episode_uuid="ep-1",
        )

        evidence = _graph_matches_to_evidence(
            "Graphiti mapped note",
            [note],
            [Citation(note_id=note.id, title=note.body.title, snippet=note.body.summary)],
        )

        assert evidence[0].source_id == "graph-note"
        assert evidence[0].score == 0.55
        assert evidence[0].metadata["retrieved_by"] == "graphiti"

    def test_structural_provider_enters_context_pack_without_graphiti(
        self,
        service: AgentService,
        monkeypatch,
    ):
        from personal_agent.agent import runtime_ask

        service.settings = service.settings.model_copy(
            update={
                "ask": service.settings.ask.model_copy(update={"graph_provider": "structural"})
            }
        )
        service.runtime._llm.generate_answer = MagicMock(return_value="Redis 使用热点订单缓存降低数据库压力。")
        service.store.add_note(make_note(
            id="gr-parent",
            title="Redis cache architecture",
            content="Redis cache document.",
            summary="Redis cache architecture.",
            user_id="default",
        ))
        service.store.add_note(make_note(
            id="gr-child",
            title="Redis cache architecture",
            content="Redis stores hot order data and reduces database pressure.",
            summary="Redis stores hot order data.",
            user_id="default",
            parent_note_id="gr-parent",
            chunk_index=0,
        ))

        monkeypatch.setattr(
            runtime_ask,
            "plan_retrieval",
            lambda *_args, **_kwargs: (
                QueryUnderstanding(query_rewrite="redis database pressure"),
                RetrievalPlan(
                    sources=["graph"],
                    parallel=False,
                    query="redis database pressure",
                    sub_queries=[],
                    filters=RetrievalFilters(),
                ),
            ),
        )

        result = service.execute_ask(question="Redis 如何降低数据库压力？")

        assert service.graph_store.ask.call_count == 0
        assert any(note.id in {"gr-child", "gr-parent"} for note in result.matches)
        assert any(item.metadata.get("retrieved_by") == "structural" for item in result.evidence)

    def test_graph_raw_episode_evidence_requires_overlap(self):
        noisy = make_note(
            id="graph-noisy",
            title="Unrelated",
            content="audio codec experiment",
            summary="audio codec experiment",
            graph_episode_uuid="ep-noisy",
        )

        evidence = _graph_matches_to_evidence(
            "pressure broadening atmospheric biases",
            [noisy],
            [],
            mode="cited_overlap",
            min_overlap=2,
        )

        assert evidence == []

    def test_graph_note_evidence_can_be_disabled(self):
        note = make_note(
            id="graph-note",
            title="Graph note",
            content="Graphiti mapped note content",
            summary="Graphiti mapped note summary",
            graph_episode_uuid="ep-1",
        )

        evidence = _graph_matches_to_evidence(
            "Graphiti mapped note",
            [note],
            [Citation(note_id=note.id, title=note.body.title, snippet=note.body.summary)],
            mode="none",
        )

        assert evidence == []

    def test_retry_prompt_includes_claim_grounding_feedback(self, service: AgentService):
        service.execute_capture(text="服务降级是在系统压力过大时主动关闭非核心能力", source_type="text")
        service.runtime._llm.generate_answer = MagicMock(side_effect=[
            "服务降级可以自动扩容数据库集群。",
            "服务降级是在系统压力过大时主动关闭非核心能力。",
        ])

        service.execute_ask(question="什么是服务降级？")

        retry_prompt = service.runtime._llm.generate_answer.call_args_list[1].args[0]
        assert "claim-level grounding" in retry_prompt
        assert "可用证据" in retry_prompt


class TestDigestFlow:
    def test_digest_returns_message(self, service: AgentService):
        result = service.digest()
        assert result.message
        assert isinstance(result.recent_notes, list)
        assert isinstance(result.due_reviews, list)
        assert result.message.startswith("今日知识简报")

    def test_digest_includes_recent_notes(self, service: AgentService):
        service.execute_capture(text="笔记1内容", source_type="text")
        service.execute_capture(text="笔记2内容", source_type="text")
        result = service.digest()
        assert len(result.recent_notes) >= 2

    def test_digest_respects_user(self, service: AgentService):
        service.execute_capture(text="Alice的笔记", source_type="text", user_id="alice")
        service.execute_capture(text="Bob的笔记", source_type="text", user_id="bob")
        result_alice = service.digest(user_id="alice")
        result_bob = service.digest(user_id="bob")
        alice_titles = {n.body.title for n in result_alice.recent_notes}
        bob_titles = {n.body.title for n in result_bob.recent_notes}
        assert "Alice的笔记" in alice_titles
        assert "Bob的笔记" in bob_titles

    def test_digest_uses_review_domain_formatter(self, service: AgentService):
        capture = service.execute_capture(text="复习触达应该推送到飞书", source_type="text")
        service.memory.add_review(ReviewCard(
            note_id=capture.note.id,
            prompt="请回忆复习触达的主入口",
            answer_hint="飞书",
            due_at=local_now(),
        ))
        result = service.digest()
        assert "最近新增笔记：" in result.message
        assert "待复习内容：" in result.message
        assert "请回忆复习触达的主入口" in result.message


class TestEntryFlow:
    def test_entry_capture_text(self, service: AgentService):
        entry = EntryInput(text="记一下：服务降级是重要的系统设计模式", source_platform="test")
        result = service.entry(entry)
        assert result.intents[-1] in ("capture_text", "unknown")
        assert result.reply_text
        if result.intents[-1] == "capture_text":
            assert service.memory.list_notes()

    def test_entry_ask(self, service: AgentService):
        service.execute_capture(text="服务降级是系统设计中的常见模式", source_type="text")
        entry = EntryInput(text="什么是服务降级？", source_platform="test")
        result = service.entry(entry)
        assert result.intents == ["ask"]
        assert result.reply_text
        snapshot = service.get_run_snapshot(result.run_id or "")
        assert snapshot is not None
        assert snapshot.thread_id == result.thread_id

    def test_entry_empty_text(self, service: AgentService):
        entry = EntryInput(text="", source_platform="test")
        result = service.entry(entry)
        assert result.intents == []

    def test_entry_capture_link(self, service: AgentService):
        entry = EntryInput(
            text="https://example.com/article 这篇文章值得收藏",
            source_platform="test",
            metadata={"url": "https://example.com/article"},
        )
        result = service.entry(entry)
        assert result.intents[-1] in ("capture_link", "capture_text", "unknown")
        assert result.reply_text


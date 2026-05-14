from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from personal_agent.core.models import Citation, KnowledgeNote
from personal_agent.memory.facade import MemoryFacade
from personal_agent.storage.cross_session_store import CrossSessionStore


class TestCrossSessionStoreDrafts:
    """Draft lifecycle: save → list → get → mark_status → list filtered."""

    def test_save_and_list_drafts(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        draft_id = store.save_draft("user-1", "这是一条固化草稿", source_context="测试上下文")
        assert draft_id

        drafts = store.list_drafts("user-1")
        assert len(drafts) == 1
        assert drafts[0]["text"] == "这是一条固化草稿"
        assert drafts[0]["status"] == "draft"
        assert drafts[0]["source_context"] == "测试上下文"

    def test_get_draft_by_id(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        draft_id = store.save_draft("user-1", "草稿A")
        store.save_draft("user-1", "草稿B")

        found = store.get_draft("user-1", draft_id)
        assert found is not None
        assert found["text"] == "草稿A"

    def test_get_nonexistent_draft(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        assert store.get_draft("user-1", "nonexistent-id") is None

    def test_mark_draft_status(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        draft_id = store.save_draft("user-1", "待固化草稿")

        ok = store.mark_draft_status("user-1", draft_id, "solidified")
        assert ok is True

        drafts = store.list_drafts("user-1", status="solidified")
        assert len(drafts) == 1
        assert drafts[0]["id"] == draft_id
        assert drafts[0]["status"] == "solidified"

        # Draft drafts should no longer include this one
        drafts_draft = store.list_drafts("user-1", status="draft")
        assert len(drafts_draft) == 0

    def test_mark_nonexistent_draft(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        assert store.mark_draft_status("user-1", "nonexistent", "solidified") is False

    def test_list_drafts_respects_filter(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        id_a = store.save_draft("user-1", "草稿A")
        id_b = store.save_draft("user-1", "草稿B")
        store.mark_draft_status("user-1", id_a, "solidified")

        all_drafts = store.list_drafts("user-1")
        assert len(all_drafts) == 2

        solidified = store.list_drafts("user-1", status="solidified")
        assert len(solidified) == 1
        assert solidified[0]["id"] == id_a

        draft_only = store.list_drafts("user-1", status="draft")
        assert len(draft_only) == 1
        assert draft_only[0]["id"] == id_b


class TestCrossSessionStoreConclusions:
    """Candidate conclusion lifecycle: add → list → mark_solidified → list filtered."""

    def test_add_and_list_conclusions(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        cid = store.add_conclusion("user-1", "用户偏好深色主题", source_session_id="session-1")
        assert cid

        conclusions = store.list_conclusions("user-1")
        assert len(conclusions) == 1
        assert conclusions[0]["text"] == "用户偏好深色主题"
        assert conclusions[0]["solidified"] is False
        assert conclusions[0]["source_session_id"] == "session-1"

    def test_mark_conclusion_solidified(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        cid = store.add_conclusion("user-1", "需要每周五进行代码审查")

        ok = store.mark_conclusion_solidified("user-1", cid)
        assert ok is True

        solidified = store.list_conclusions("user-1", solidified=True)
        assert len(solidified) == 1
        assert solidified[0]["id"] == cid

        unsolidified = store.list_conclusions("user-1", solidified=False)
        assert len(unsolidified) == 0

    def test_mark_nonexistent_conclusion(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        assert store.mark_conclusion_solidified("user-1", "nonexistent") is False

    def test_list_conclusions_unfiltered(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        cid_a = store.add_conclusion("user-1", "结论A")
        cid_b = store.add_conclusion("user-1", "结论B")
        store.mark_conclusion_solidified("user-1", cid_a)

        all_conclusions = store.list_conclusions("user-1")
        assert len(all_conclusions) == 2


class TestCrossSessionStoreCitations:
    """Citation lifecycle for delete targeting resolution."""

    def test_add_and_retrieve_citations(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        citations = [
            Citation(note_id="n1", title="笔记一", snippet="片段一"),
            Citation(note_id="n2", title="笔记二", snippet="片段二"),
        ]
        store.add_citations("user-1", citations, question="测试问题")

        recent = store.recent_citations("user-1")
        assert len(recent) == 2
        assert recent[0]["note_id"] == "n1"
        assert recent[0]["source_question"] == "测试问题"

    def test_citations_respect_limit(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        citations = [
            Citation(note_id=f"n{i}", title=f"笔记{i}", snippet="...")
            for i in range(5)
        ]
        store.add_citations("user-1", citations)

        recent = store.recent_citations("user-1", limit=3)
        assert len(recent) == 3


class TestCrossSessionStoreTTLAndCapacity:
    """TTL expiry and max count enforcement."""

    def test_draft_ttl_respected(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        # Manually insert an expired draft
        store._ensure_loaded()
        store._data["user-1"] = {
            "solidify_drafts": [{
                "id": "expired-draft",
                "text": "过期草稿",
                "source_context": "",
                "status": "draft",
                "created_at": (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat(),
            }],
        }
        store._save()

        drafts = store.list_drafts("user-1")
        assert len(drafts) == 0  # expired and filtered out

    def test_conclusion_ttl_respected(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        store._ensure_loaded()
        store._data["user-1"] = {
            "candidate_conclusions": [{
                "id": "expired-conclusion",
                "text": "过期结论",
                "source_session_id": "",
                "solidified": False,
                "created_at": (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat(),
            }],
        }
        store._save()

        conclusions = store.list_conclusions("user-1")
        assert len(conclusions) == 0

    def test_citation_ttl_respected(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        store._ensure_loaded()
        store._data["user-1"] = {
            "recent_citations": [{
                "id": "expired-citation",
                "note_id": "n1",
                "title": "旧笔记",
                "snippet": "...",
                "relation_fact": None,
                "source_question": "旧问题",
                "created_at": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
            }],
        }
        store._save()

        recent = store.recent_citations("user-1")
        assert len(recent) == 0


class TestCrossSessionStoreUserIsolation:
    """Data should be isolated per user."""

    def test_drafts_isolated_per_user(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        store.save_draft("user-1", "用户1的草稿")
        store.save_draft("user-2", "用户2的草稿")

        assert len(store.list_drafts("user-1")) == 1
        assert len(store.list_drafts("user-2")) == 1
        assert store.list_drafts("user-1")[0]["text"] == "用户1的草稿"
        assert store.list_drafts("user-2")[0]["text"] == "用户2的草稿"

    def test_conclusions_isolated_per_user(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        store.add_conclusion("user-1", "结论1")
        store.add_conclusion("user-2", "结论2")

        assert len(store.list_conclusions("user-1")) == 1
        assert len(store.list_conclusions("user-2")) == 1

    def test_clear_user_removes_all_artifacts(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        store.save_draft("user-1", "草稿")
        store.add_conclusion("user-1", "结论")
        store.add_citations("user-1", [Citation(note_id="n1", title="笔记", snippet="...")])

        count = store.clear_user("user-1")
        assert count == 3
        assert store.list_drafts("user-1") == []
        assert store.list_conclusions("user-1") == []
        assert store.recent_citations("user-1") == []

    def test_clear_nonexistent_user(self, temp_dir: Path):
        store = CrossSessionStore(temp_dir)
        assert store.clear_user("nonexistent") == 0


class TestCrossSessionStorePersistence:
    """Data should survive store reload."""

    def test_drafts_persist_across_reload(self, temp_dir: Path):
        store_a = CrossSessionStore(temp_dir)
        draft_id = store_a.save_draft("user-1", "持久化草稿")

        store_b = CrossSessionStore(temp_dir)
        drafts = store_b.list_drafts("user-1")
        assert len(drafts) == 1
        assert drafts[0]["id"] == draft_id
        assert drafts[0]["text"] == "持久化草稿"

    def test_conclusions_persist_across_reload(self, temp_dir: Path):
        store_a = CrossSessionStore(temp_dir)
        cid = store_a.add_conclusion("user-1", "持久化结论")
        store_a.mark_conclusion_solidified("user-1", cid)

        store_b = CrossSessionStore(temp_dir)
        conclusions = store_b.list_conclusions("user-1", solidified=True)
        assert len(conclusions) == 1
        assert conclusions[0]["id"] == cid


class TestMemoryFacadeCrossSessionIntegration:
    """MemoryFacade convenience methods for cross-session operations."""

    def test_mark_draft_solidified_via_facade(self, temp_dir: Path):
        cross_session = CrossSessionStore(temp_dir)
        local_store = MagicMock()
        ask_history = MagicMock()
        ask_history.configured.return_value = False
        facade = MemoryFacade(local_store, ask_history, cross_session_store=cross_session)

        draft_id = cross_session.save_draft("user-1", "测试草稿")
        ok = facade.mark_draft_solidified("user-1", draft_id)
        assert ok is True

        drafts = cross_session.list_drafts("user-1", status="solidified")
        assert len(drafts) == 1

    def test_mark_conclusion_solidified_via_facade(self, temp_dir: Path):
        cross_session = CrossSessionStore(temp_dir)
        local_store = MagicMock()
        ask_history = MagicMock()
        ask_history.configured.return_value = False
        facade = MemoryFacade(local_store, ask_history, cross_session_store=cross_session)

        cid = cross_session.add_conclusion("user-1", "测试结论")
        ok = facade.mark_conclusion_solidified("user-1", cid)
        assert ok is True

        conclusions = cross_session.list_conclusions("user-1", solidified=True)
        assert len(conclusions) == 1

    def test_facade_save_and_get_draft(self, temp_dir: Path):
        cross_session = CrossSessionStore(temp_dir)
        local_store = MagicMock()
        ask_history = MagicMock()
        ask_history.configured.return_value = False
        facade = MemoryFacade(local_store, ask_history, cross_session_store=cross_session)

        draft_id = facade.save_draft("user-1", "通过Facade保存的草稿", source_context="ctx")
        assert draft_id

        draft = facade.get_draft("user-1", draft_id)
        assert draft is not None
        assert draft["text"] == "通过Facade保存的草稿"
        assert draft["source_context"] == "ctx"

    def test_facade_add_and_list_conclusions(self, temp_dir: Path):
        cross_session = CrossSessionStore(temp_dir)
        local_store = MagicMock()
        ask_history = MagicMock()
        ask_history.configured.return_value = False
        facade = MemoryFacade(local_store, ask_history, cross_session_store=cross_session)

        cid = facade.add_conclusion("user-1", "Facade结论", session_id="s1")
        assert cid

        all_cons = facade.list_conclusions("user-1")
        assert len(all_cons) == 1
        assert all_cons[0]["solidified"] is False

        facade.mark_conclusion_solidified("user-1", cid)
        solidified = facade.list_conclusions("user-1", solidified=True)
        assert len(solidified) == 1

    def test_facade_list_drafts_with_status_filter(self, temp_dir: Path):
        cross_session = CrossSessionStore(temp_dir)
        local_store = MagicMock()
        ask_history = MagicMock()
        ask_history.configured.return_value = False
        facade = MemoryFacade(local_store, ask_history, cross_session_store=cross_session)

        d1 = facade.save_draft("user-1", "草稿1")
        d2 = facade.save_draft("user-1", "草稿2")
        facade.mark_draft_solidified("user-1", d1)

        all_drafts = facade.list_drafts("user-1")
        assert len(all_drafts) == 2
        solidified = facade.list_drafts("user-1", status="solidified")
        assert len(solidified) == 1
        assert solidified[0]["id"] == d1

    def test_facade_without_cross_session_graceful(self):
        local_store = MagicMock()
        ask_history = MagicMock()
        facade = MemoryFacade(local_store, ask_history, cross_session_store=None)

        assert facade.save_draft("user-1", "text") == ""
        assert facade.get_draft("user-1", "any") is None
        assert facade.list_drafts("user-1") == []
        assert facade.mark_draft_solidified("user-1", "any") is False
        assert facade.add_conclusion("user-1", "text") == ""
        assert facade.list_conclusions("user-1") == []
        assert facade.mark_conclusion_solidified("user-1", "any") is False


class TestCrossSessionStoreDraftSolidifiedContinuation:
    """Full lifecycle: draft saved → stored → status writeback (integration simulation)."""

    def test_full_draft_solidify_flow(self, temp_dir: Path):
        """Simulate the solidify_conversation → capture_text → status writeback loop."""
        store = CrossSessionStore(temp_dir)

        # Step 1: compose saves a draft
        draft_id = store.save_draft("user-1", "固化后的知识文本", source_context="对话上下文")
        assert draft_id
        drafts = store.list_drafts("user-1", status="draft")
        assert len(drafts) == 1

        # Step 2: capture_text creates a KnowledgeNote (simulated)
        # In real code, note creation happens in ToolRegistry

        # Step 3: status writeback — mark draft as solidified
        ok = store.mark_draft_status("user-1", draft_id, "solidified")
        assert ok is True

        # Verify the draft is now solidified
        draft = store.get_draft("user-1", draft_id)
        assert draft is not None
        assert draft["status"] == "solidified"

        # Draft drafts should be empty
        active_drafts = store.list_drafts("user-1", status="draft")
        assert len(active_drafts) == 0

    def test_conclusion_solidify_follows_draft(self, temp_dir: Path):
        """Candidate conclusions should be markable as solidified alongside drafts."""
        store = CrossSessionStore(temp_dir)

        cid = store.add_conclusion("user-1", "项目使用React 19", source_session_id="s1")
        store.mark_conclusion_solidified("user-1", cid)

        # Unsolidified list should not contain it
        unsolidified = store.list_conclusions("user-1", solidified=False)
        assert all(c["id"] != cid for c in unsolidified)

        # Solidified list should contain it
        solidified = store.list_conclusions("user-1", solidified=True)
        assert any(c["id"] == cid for c in solidified)


class TestExtractConclusions:
    """Unit tests for the _extract_conclusions helper in plan_executor."""

    def test_extracts_factual_sentences_with_indicators(self):
        from personal_agent.agent.plan_executor import _extract_conclusions
        # Use indicator characters that are ASCII-safe: "已" is commonly used
        # Each sentence must contain one of the indicator chars and be >= 15 chars
        answer = (
            "Task1已完成前端重构部署工作。"
            "Team已确认使用新构建工具。"
            "Good weather today."
            "用户偏好设置为深色主题。"
        )
        conclusions = _extract_conclusions(answer)
        # At least the sentences with indicators should be extracted
        assert len(conclusions) >= 2

    def test_filters_short_sentences_correctly(self, temp_dir=None):
        from personal_agent.agent.plan_executor import _extract_conclusions
        # Very short sentences should be filtered out regardless of content
        answer = "OK。好的。知道了。a。b。c。def。ghij。klmno。"
        conclusions = _extract_conclusions(answer)
        # No sentence meets the 15-char minimum
        assert len(conclusions) == 0

    def test_trims_to_max_5(self, temp_dir=None):
        from personal_agent.agent.plan_executor import _extract_conclusions
        # Generate 7 sentences each with an indicator
        answer = "。".join([
            f"根据第{i}次讨论确认事项{i}"
            for i in range(7)
        ])
        conclusions = _extract_conclusions(answer)
        # capped at 5
        assert len(conclusions) <= 5

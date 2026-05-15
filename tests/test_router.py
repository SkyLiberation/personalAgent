from __future__ import annotations

import logging

import pytest

from personal_agent.agent.entry_nodes import (
    EntryNodeDeps,
    heuristic_entry_intent,
    route_entry_intent_node,
)
from personal_agent.agent.router import DefaultIntentRouter, RouterDecision
from personal_agent.core.models import AgentState, EntryInput


class TestHeuristicEntryIntent:
    def test_empty_text_returns_unknown(self):
        intent, reason = heuristic_entry_intent("")
        assert intent == "unknown"
        assert "空" in reason

    def test_url_only_returns_capture_link(self):
        intent, reason = heuristic_entry_intent("https://example.com/article")
        assert intent == "capture_link"
        assert "链接" in reason

    def test_url_with_ask_keyword_returns_ask(self):
        intent, reason = heuristic_entry_intent(
            "https://example.com/article 这篇文章讲了什么？"
        )
        assert intent == "ask"
        assert "提问" in reason

    def test_question_marks_returns_ask(self):
        intent, _ = heuristic_entry_intent("什么是服务降级？")
        assert intent == "ask"

    def test_ask_keyword_zenme_returns_ask(self):
        intent, _ = heuristic_entry_intent("怎么配置Neo4j连接？")
        assert intent == "ask"

    def test_capture_keyword_returns_capture_text(self):
        intent, _ = heuristic_entry_intent("记一下：今天学习了LangGraph")
        assert intent == "capture_text"

    def test_capture_keyword_baocun_returns_capture_text(self):
        intent, _ = heuristic_entry_intent("保存这篇文章到知识库")
        assert intent == "capture_text"

    def test_summarize_thread_keywords_returns_summarize(self):
        intent, _ = heuristic_entry_intent("帮我总结一下今天群聊讨论了什么")
        assert intent == "summarize_thread"

    def test_default_falls_back_to_capture_text(self):
        intent, _ = heuristic_entry_intent("今天天气不错")
        assert intent == "capture_text"

    def test_url_in_text_is_detected(self):
        intent, _ = heuristic_entry_intent("看看这个 https://docs.python.org/3/")
        assert intent == "capture_link"


class TestDefaultIntentRouter:
    @pytest.fixture
    def router(self, settings):
        return DefaultIntentRouter(settings)

    def test_file_source_type_bypasses_llm(self, router):
        entry = EntryInput(source_type="file", text="any.pdf")
        decision = router.classify(entry)
        assert decision.route == "capture_file"
        assert decision.confidence == 0.9
        assert decision.risk_level == "low"

    def test_empty_text_returns_unknown_without_llm(self, router):
        entry = EntryInput(source_type="text", text="")
        decision = router.classify(entry)
        assert decision.route == "unknown"

    def test_whitespace_only_text_returns_unknown(self, router):
        entry = EntryInput(source_type="text", text="   ")
        decision = router.classify(entry)
        assert decision.route == "unknown"

    def test_llm_not_configured_falls_back_to_heuristic(self):
        from personal_agent.core.config import Settings

        router_no_llm = DefaultIntentRouter(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
        )
        entry = EntryInput(source_type="text", text="什么是服务降级？")
        decision = router_no_llm.classify(entry)
        assert decision.route == "ask"
        assert decision.requires_retrieval is True
        assert decision.risk_level == "low"

    def test_router_returns_structured_decision(self):
        from personal_agent.core.config import Settings

        router_no_llm = DefaultIntentRouter(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
        )
        entry = EntryInput(source_type="text", text="删除那条旧笔记")
        decision = router_no_llm.classify(entry)
        assert isinstance(decision, RouterDecision)
        assert decision.route == "delete_knowledge"
        assert decision.risk_level == "high"
        assert decision.requires_confirmation is True
        assert decision.requires_planning is True

    def test_router_decision_has_all_fields(self):
        from personal_agent.core.config import Settings

        router_no_llm = DefaultIntentRouter(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
        )
        entry = EntryInput(source_type="text", text="记一下今天学习了LangGraph")
        decision = router_no_llm.classify(entry)
        assert hasattr(decision, "route")
        assert hasattr(decision, "confidence")
        assert hasattr(decision, "requires_tools")
        assert hasattr(decision, "requires_retrieval")
        assert hasattr(decision, "requires_planning")
        assert hasattr(decision, "risk_level")
        assert hasattr(decision, "requires_confirmation")
        assert hasattr(decision, "missing_information")
        assert hasattr(decision, "candidate_tools")
        assert hasattr(decision, "user_visible_message")

    def test_router_logs_structured_decision(self, caplog):
        from personal_agent.core.config import Settings

        router_no_llm = DefaultIntentRouter(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
        )
        caplog.set_level(logging.INFO)

        decision = router_no_llm.classify(
            EntryInput(source_type="text", text="什么是服务降级？", user_id="alice")
        )

        assert decision.route == "ask"
        assert "router.decision" in caplog.text
        assert '"strategy": "heuristic"' in caplog.text
        assert '"route": "ask"' in caplog.text

    def test_entry_route_node_logs_target_node(self, caplog):
        deps = EntryNodeDeps(
            classify_intent=lambda _entry: RouterDecision(
                route="ask",
                confidence=0.86,
                requires_retrieval=True,
                candidate_tools=["graph_search"],
                user_visible_message="测试路由到问答分支。",
            ),
            capture=lambda **_kwargs: None,
            ask=lambda *_args, **_kwargs: None,
        )
        state = AgentState(
            mode="entry",
            user_id="alice",
            entry_input=EntryInput(
                text="什么是服务降级？", user_id="alice", session_id="s1"
            ),
        )
        caplog.set_level(logging.INFO)

        result = route_entry_intent_node(state, deps)

        assert result.intent == "ask"
        assert "entry.route.selected" in caplog.text
        assert '"route": "ask"' in caplog.text
        assert '"target_node": "ask_branch"' in caplog.text

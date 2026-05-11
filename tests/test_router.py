from __future__ import annotations

import pytest

from personal_agent.agent.entry_nodes import heuristic_entry_intent
from personal_agent.agent.router import DefaultIntentRouter
from personal_agent.core.models import EntryInput


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
        intent, _ = router.classify(entry)
        assert intent == "capture_file"

    def test_empty_text_returns_unknown_without_llm(self, router):
        entry = EntryInput(source_type="text", text="")
        intent, _ = router.classify(entry)
        assert intent == "unknown"

    def test_whitespace_only_text_returns_unknown(self, router):
        entry = EntryInput(source_type="text", text="   ")
        intent, _ = router.classify(entry)
        assert intent == "unknown"

    def test_llm_not_configured_falls_back_to_heuristic(self):
        from personal_agent.core.config import Settings

        router_no_llm = DefaultIntentRouter(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
        )
        entry = EntryInput(source_type="text", text="什么是服务降级？")
        intent, _ = router_no_llm.classify(entry)
        assert intent == "ask"

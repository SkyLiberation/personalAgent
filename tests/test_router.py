from __future__ import annotations

import logging

import pytest

from personal_agent.agent.router import DefaultIntentRouter, RouterDecision
from personal_agent.core.models import EntryInput


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

    def test_llm_not_configured_reports_router_unavailable(self):
        from personal_agent.core.config import OpenAIConfig, Settings

        router_no_llm = DefaultIntentRouter(
            Settings(openai=OpenAIConfig(api_key=None, base_url=None, small_model=""))
        )
        entry = EntryInput(source_type="text", text="什么是服务降级？")
        decision = router_no_llm.classify(entry)
        assert decision.route == "unknown"
        assert decision.requires_retrieval is False
        assert decision.requires_clarification is False
        assert decision.risk_level == "low"
        assert "路由模型当前不可用" in decision.user_visible_message

    def test_llm_current_weather_ask_decision_enables_retrieval(self, monkeypatch):
        from personal_agent.core.config import OpenAIConfig, Settings

        router = DefaultIntentRouter(Settings())
        monkeypatch.setattr(
            router,
            "_classify_with_llm",
            lambda _text, _context="": RouterDecision(
                route="ask",
                user_visible_message="需要查询最新外部天气信息。",
            ),
        )

        decision = router.classify(
            EntryInput(source_type="text", text="今天西安天气怎么样")
        )

        assert decision.route == "ask"
        assert decision.requires_retrieval is True
        assert "web_search" in decision.candidate_tools

    def test_llm_router_receives_thread_conversation_messages(self, monkeypatch):
        from personal_agent.core.config import OpenAIConfig, Settings

        router = DefaultIntentRouter(Settings())
        captured: dict[str, str] = {}

        def classify(text: str, context: str = "") -> RouterDecision:
            captured["text"] = text
            captured["context"] = context
            return RouterDecision(route="direct_answer")

        monkeypatch.setattr(router, "_classify_with_llm", classify)
        router.classify(
            EntryInput(source_type="text", text="它有什么用？"),
            conversation_messages=[
                {"role": "user", "content": "什么是 DNS？"},
                {"role": "assistant", "content": "DNS 是域名系统。"},
            ],
        )

        assert captured["text"] == "它有什么用？"
        assert any("DNS" in item.get("content", "") for item in captured["context"])

    def test_llm_decision_is_not_overridden_by_contextual_keyword_rules(self, monkeypatch):
        from personal_agent.core.config import OpenAIConfig, Settings

        router = DefaultIntentRouter(
            Settings(
                openai=OpenAIConfig(
                    api_key="key",
                    base_url="https://example.invalid/v1",
                    small_model="model",
                )
            )
        )
        monkeypatch.setattr(
            router,
            "_classify_with_llm",
            lambda _text, _context="": RouterDecision(route="capture_text"),
        )

        decision = router.classify(
            EntryInput(text="将DNS相关知识存储至知识库"),
            conversation_messages=[
                {"role": "user", "content": "什么是DNS"},
                {"role": "assistant", "content": "DNS 是域名系统。"},
            ],
        )

        assert decision.route == "capture_text"
        assert decision.requires_planning is False

    def test_configured_llm_failure_reports_router_unavailable(self, monkeypatch):
        from personal_agent.core.config import OpenAIConfig, Settings

        router = DefaultIntentRouter(
            Settings(
                openai=OpenAIConfig(
                    api_key="key",
                    base_url="https://example.invalid/v1",
                    small_model="model",
                )
            )
        )
        monkeypatch.setattr(router, "_classify_with_llm", lambda _text, _context="": None)

        decision = router.classify(EntryInput(text="什么是DNS"))

        assert decision.route == "unknown"
        assert decision.requires_clarification is False
        assert "路由模型当前不可用" in decision.user_visible_message

    def test_explicit_note_content_remains_plain_capture(self, monkeypatch):
        from personal_agent.core.config import OpenAIConfig, Settings

        router = DefaultIntentRouter(Settings())
        monkeypatch.setattr(
            router,
            "_classify_with_llm",
            lambda _text, _context="": RouterDecision(route="capture_text"),
        )

        decision = router.classify(
            EntryInput(text="记一下：DNS 是将域名转换为 IP 地址的系统。"),
            conversation_messages=[
                {"role": "user", "content": "什么是DNS"},
                {"role": "assistant", "content": "DNS 是域名系统。"},
            ],
        )

        assert decision.route == "capture_text"

    def test_llm_delete_decision_applies_high_risk_defaults(self, monkeypatch):
        from personal_agent.core.config import OpenAIConfig, Settings

        router = DefaultIntentRouter(Settings())
        monkeypatch.setattr(
            router,
            "_classify_with_llm",
            lambda _text, _context="": RouterDecision(
                route="delete_knowledge",
                risk_level="high",
                requires_confirmation=True,
            ),
        )
        entry = EntryInput(source_type="text", text="删除那条旧笔记")
        decision = router.classify(entry)
        assert isinstance(decision, RouterDecision)
        assert decision.route == "delete_knowledge"
        assert decision.risk_level == "high"
        assert decision.requires_confirmation is True
        assert decision.requires_planning is True

    def test_delete_defaults_remain_safe_when_llm_omits_risk_fields(self, monkeypatch):
        from personal_agent.core.config import OpenAIConfig, Settings

        router = DefaultIntentRouter(Settings())
        monkeypatch.setattr(
            router,
            "_classify_with_llm",
            lambda _text, _context="": RouterDecision(route="delete_knowledge"),
        )

        decision = router.classify(EntryInput(text="删除关于DNS的知识"))

        assert decision.risk_level == "high"
        assert decision.requires_confirmation is True

    def test_router_unavailable_decision_has_all_fields(self):
        from personal_agent.core.config import OpenAIConfig, Settings

        router_no_llm = DefaultIntentRouter(
            Settings(openai=OpenAIConfig(api_key=None, base_url=None, small_model=""))
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
        assert hasattr(decision, "requires_clarification")
        assert hasattr(decision, "missing_information")
        assert hasattr(decision, "clarification_prompt")
        assert hasattr(decision, "candidate_tools")
        assert hasattr(decision, "user_visible_message")

    def test_llm_may_request_clarification_for_incomplete_fragment(self, monkeypatch):
        from personal_agent.core.config import OpenAIConfig, Settings

        router = DefaultIntentRouter(Settings())
        monkeypatch.setattr(
            router,
            "_classify_with_llm",
            lambda _text, _context="": RouterDecision(
                route="unknown",
                requires_clarification=True,
                missing_information=["具体目标或待处理内容"],
                clarification_prompt="请补充具体内容。",
            ),
        )
        decision = router.classify(EntryInput(source_type="text", text="帮我"))

        assert decision.route == "unknown"
        assert decision.requires_clarification is True
        assert decision.missing_information
        assert decision.clarification_prompt

    def test_router_logs_unconfigured_model_decision(self, caplog):
        from personal_agent.core.config import OpenAIConfig, Settings

        router_no_llm = DefaultIntentRouter(
            Settings(openai=OpenAIConfig(api_key=None, base_url=None, small_model=""))
        )
        caplog.set_level(logging.INFO)

        decision = router_no_llm.classify(
            EntryInput(source_type="text", text="什么是服务降级？", user_id="alice")
        )

        assert decision.route == "unknown"
        assert "router.decision" in caplog.text
        assert '"strategy": "llm_unconfigured"' in caplog.text
        assert '"route": "unknown"' in caplog.text

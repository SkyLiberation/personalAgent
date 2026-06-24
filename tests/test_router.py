from __future__ import annotations

import logging
import pytest
from pydantic import ValidationError

from personal_agent.agent.router import (
    ClarificationDraft,
    DefaultIntentRouter,
    Goal,
    GoalDraft,
    RouterOutput,
    describe_router_decision,
)
from personal_agent.kernel.models import EntryInput
from personal_agent.core.structured_model import StructuredModelResponse


class TestRouterOutputContract:
    def test_ready_requires_goals(self):
        with pytest.raises(ValidationError, match="requires at least one goal"):
            RouterOutput(outcome="ready", goals=[], clarification=None)

    def test_ready_rejects_clarification(self):
        with pytest.raises(ValidationError, match="cannot contain clarification"):
            RouterOutput(
                outcome="ready",
                goals=[GoalDraft(intent="ask", input="问题")],
                clarification=ClarificationDraft(
                    missing_information=["x"],
                    prompt="补充 x",
                ),
            )

    def test_clarify_requires_payload(self):
        with pytest.raises(ValidationError, match="requires clarification"):
            RouterOutput(outcome="clarify", goals=[], clarification=None)

    def test_schema_is_generated_from_pydantic_model(self):
        schema = RouterOutput.model_json_schema()
        assert set(schema["properties"]) == {"outcome", "goals", "clarification"}
        assert "goal_id" not in str(schema)
        assert "depends_on" not in str(schema)
        assert "confidence" not in str(schema)


class TestDefaultIntentRouter:
    @pytest.fixture
    def router(self, settings):
        return DefaultIntentRouter(None)

    def test_file_source_type_bypasses_llm(self, router):
        decision = router.classify(EntryInput(source_type="file", text="any.pdf"))
        assert [item.intent for item in decision.goals] == ["capture_file"]
        assert decision.goals[0].goal_id == "goal_1"

    def test_empty_text_requests_clarification(self, router):
        decision = router.classify(EntryInput(text=""))
        assert decision.requires_clarification is True
        assert decision.clarification_prompt

    def test_domain_goal_contains_no_execution_policy(self):
        fields = Goal.model_fields
        assert "requires_tools" not in fields
        assert "risk_level" not in fields
        assert "requires_confirmation" not in fields

    def test_llm_not_configured_reports_router_unavailable(self):
        router = DefaultIntentRouter(None)
        decision = router.classify(EntryInput(text="什么是服务降级？"))
        assert decision.error == "router_unavailable"
        assert "路由模型当前不可用" in describe_router_decision(decision)

    def test_compound_output_is_normalized_to_stable_goal_ids(self, monkeypatch):
        router = DefaultIntentRouter(None)
        monkeypatch.setattr(
            router,
            "_classify_with_llm",
            lambda _text, _context=None: RouterOutput(
                outcome="ready",
                goals=[
                    GoalDraft(
                        intent="capture_text",
                        input="DNS 将域名解析为 IP。",
                    ),
                    GoalDraft(
                        intent="ask",
                        input="DNS 为什么需要缓存？",
                    ),
                ],
                clarification=None,
            ),
        )

        decision = router.classify(EntryInput(text="复合请求"))

        assert [item.goal_id for item in decision.goals] == ["goal_1", "goal_2"]
        assert [item.intent for item in decision.goals] == ["capture_text", "ask"]

    def test_router_uses_typed_structured_adapter(self, monkeypatch):
        expected = RouterOutput(
            outcome="ready",
            goals=[GoalDraft(intent="ask", input="什么是 DNS？")],
            clarification=None,
        )
        class FakeModelClient:
            request = None

            def generate(self, request):
                self.request = request
                return StructuredModelResponse(
                    value=expected,
                    model="router-model",
                    latency_ms=1.0,
                )

        client = FakeModelClient()
        router = DefaultIntentRouter(client)

        result = router._classify_with_llm("什么是 DNS？")

        assert result == expected
        assert client.request.output_type is RouterOutput
        assert not hasattr(client.request, "upload_inputs_outputs")

    def test_router_logs_goal_list(self, caplog):
        router = DefaultIntentRouter(None)
        caplog.set_level(logging.INFO)
        router.classify(EntryInput(text="什么是服务降级？", user_id="alice"))
        assert "router.decision" in caplog.text
        assert '"goals": []' in caplog.text

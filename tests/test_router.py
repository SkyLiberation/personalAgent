from __future__ import annotations

import logging
import pytest
from pydantic import ValidationError

from personal_agent.planning.router import (
    ClarificationDraft,
    DefaultIntentRouter,
    Goal,
    GoalDraft,
    RouterOutput,
    describe_router_decision,
)
from personal_agent.kernel.models import ArtifactRef, EntryInput
from personal_agent.infra.structured_model import StructuredModelResponse


class TestRouterOutputContract:
    def test_ready_requires_goals(self):
        with pytest.raises(ValidationError, match="requires at least one goal"):
            _router_output(goals=[])

    def test_ready_rejects_clarification(self):
        with pytest.raises(ValidationError, match="cannot contain clarification"):
            RouterOutput(
                user_goal="回答问题",
                route_type="single_workflow",
                matched_capabilities=["ask"],
                coverage="full",
                missing_requirements=[],
                outcome="ready",
                goals=[GoalDraft(intent="ask", input="问题")],
                clarification=ClarificationDraft(
                    missing_information=["x"],
                    prompt="补充 x",
                ),
            )

    def test_clarify_requires_payload(self):
        with pytest.raises(ValidationError, match="requires clarification"):
            RouterOutput(
                user_goal="识别用户目标",
                route_type="clarify",
                matched_capabilities=[],
                coverage="ambiguous",
                missing_requirements=["明确的目标"],
                outcome="clarify",
                goals=[],
                clarification=None,
            )

    def test_schema_is_generated_from_pydantic_model(self):
        schema = RouterOutput.model_json_schema()
        assert set(schema["properties"]) == {
            "user_goal",
            "route_type",
            "matched_capabilities",
            "coverage",
            "missing_requirements",
            "outcome",
            "goals",
            "clarification",
        }
        assert "goal_id" not in str(schema)
        assert "depends_on" not in str(schema)
        assert "confidence" not in str(schema)

    def test_unsupported_requires_missing_requirements(self):
        with pytest.raises(ValidationError, match="requires missing_requirements"):
            RouterOutput(
                user_goal="发送邮件",
                route_type="unsupported",
                matched_capabilities=[],
                coverage="unsupported",
                missing_requirements=[],
                outcome="unsupported",
                goals=[],
                clarification=None,
            )


class TestDefaultIntentRouter:
    @pytest.fixture
    def router(self, settings):
        return DefaultIntentRouter(None)

    def test_file_source_type_no_longer_implies_capture(self, router):
        decision = router.classify(EntryInput(source_type="file", text="any.pdf"))
        assert [item.intent for item in decision.goals] == ["ask"]

    def test_artifact_summary_routes_to_analyze_artifact(self, router):
        decision = router.classify(EntryInput(
            text="总结这张图里的内容",
            artifacts=[_artifact()],
        ))
        assert [item.intent for item in decision.goals] == ["analyze_artifact"]
        assert decision.goals[0].goal_id == "goal_1"
        assert decision.user_goal == "总结这张图里的内容"
        assert decision.route_type == "single_workflow"
        assert decision.coverage == "full"

    def test_artifact_capture_requires_explicit_save_intent(self, router):
        decision = router.classify(EntryInput(
            text="把这个 PDF 收进知识库",
            artifacts=[_artifact(filename="paper.pdf", source_type="pdf")],
        ))
        assert [item.intent for item in decision.goals] == ["capture_file"]
        assert decision.matched_capabilities == ["capture_file"]

    def test_empty_text_requests_clarification(self, router):
        decision = router.classify(EntryInput(text=""))
        assert decision.requires_clarification is True
        assert decision.clarification_prompt

    def test_domain_goal_contains_no_execution_policy(self):
        fields = Goal.model_fields
        assert "requires_tools" not in fields
        assert "risk_level" not in fields
        assert "requires_confirmation" not in fields

    def test_llm_not_configured_uses_offline_ask_fallback(self):
        router = DefaultIntentRouter(None)
        decision = router.classify(EntryInput(text="什么是服务降级？"))
        assert [item.intent for item in decision.goals] == ["ask"]
        assert "已识别目标：ask" in describe_router_decision(decision)

    def test_research_request_uses_deterministic_research_once_rule(self):
        router = DefaultIntentRouter(None)
        decision = router.classify(EntryInput(
            text="调研 Agent Runtime SDK 最近的重要发布，最多整理 1 条，高可信，优先确认官方来源"
        ))

        assert [item.intent for item in decision.goals] == ["research_once"]
        assert decision.goals[0].input.startswith("调研 Agent Runtime SDK")

    def test_simple_fresh_fact_question_does_not_use_research_rule(self):
        router = DefaultIntentRouter(None)
        decision = router.classify(EntryInput(text="查一下 Python 最新稳定版本是多少"))

        assert [item.intent for item in decision.goals] == ["ask"]

    def test_research_deliverable_lookup_uses_research_once_rule(self):
        router = DefaultIntentRouter(None)
        decision = router.classify(EntryInput(
            text="帮我收集最近一周 Agent Runtime SDK 的官方发布和 GitHub 动态，最多 2 条"
        ))

        assert [item.intent for item in decision.goals] == ["research_once"]

    def test_compound_capture_then_ask_rule_wins_over_negative_research_phrase(self):
        router = DefaultIntentRouter(None)
        decision = router.classify(EntryInput(
            text="先记一下：Gamma 发布窗口是周五 20:00；然后直接回答 Gamma 发布窗口是什么，不要发起调研。"
        ))

        assert decision.route_type == "composite_workflow"
        assert [item.intent for item in decision.goals] == ["capture_text", "ask"]
        assert [item.goal_id for item in decision.goals] == ["goal_1", "goal_2"]

    @pytest.mark.parametrize(
        ("text", "intent"),
        [
            ("生成今天的知识简报", "review_digest"),
            ("检查我的知识库还有哪些缺口", "inspect_knowledge_gaps"),
            ("查看 workflow run_id abc 的步骤执行情况", "inspect_workflow"),
            ("worker 是否堆积，查看失败任务", "inspect_operations"),
            ("这条知识过期了，帮我标记一下", "maintain_knowledge"),
            ("把 AI 简报订阅暂停", "manage_research"),
            ("每天9点收集AI新闻简报", "create_research_subscription"),
            ("删除关于 DNS 的知识", "delete_knowledge"),
            ("把刚才结论固化下来", "solidify_conversation"),
            ("总结这个群聊线程", "summarize_thread"),
            ("把 Redis 相关笔记整理成一篇综述", "consolidate_knowledge"),
        ],
    )
    def test_offline_fallback_covers_explicit_workflow_intents(self, text, intent):
        router = DefaultIntentRouter(None)
        decision = router.classify(EntryInput(text=text))

        assert [item.intent for item in decision.goals] == [intent]

    def test_compound_output_is_normalized_to_stable_goal_ids(self, monkeypatch):
        router = DefaultIntentRouter(None)
        monkeypatch.setattr(
            router,
            "_classify_with_llm",
            lambda _text, _context=None: RouterOutput(
                user_goal="记录 DNS 事实并回答缓存原因",
                route_type="composite_workflow",
                matched_capabilities=["capture_text", "ask"],
                coverage="full",
                missing_requirements=[],
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
            user_goal="解释 DNS",
            route_type="single_workflow",
            matched_capabilities=["ask"],
            coverage="full",
            missing_requirements=[],
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
        assert '"goals": ["ask"]' in caplog.text
        assert '"strategy": "offline_fallback"' in caplog.text


def _router_output(**overrides) -> RouterOutput:
    data = {
        "user_goal": "回答问题",
        "route_type": "single_workflow",
        "matched_capabilities": ["ask"],
        "coverage": "full",
        "missing_requirements": [],
        "outcome": "ready",
        "goals": [GoalDraft(intent="ask", input="问题")],
        "clarification": None,
    }
    data.update(overrides)
    return RouterOutput(**data)


def _artifact(filename: str = "image.png", source_type: str = "image") -> ArtifactRef:
    return ArtifactRef(
        artifact_id="art-test",
        filename=filename,
        content_type="image/png" if source_type == "image" else "application/pdf",
        source_type=source_type,
        file_path="/tmp/art-test",
        size_bytes=123,
    )

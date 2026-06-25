from __future__ import annotations

import json
import time

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from pydantic import ValidationError

from personal_agent.orchestration.orchestration_models import AgentGraphState, ReactSubState, ToolTrackingSubState
from personal_agent.governance import InMemoryToolAuditSink, ToolExecutor
from personal_agent.tools import (
    ToolError,
    governance_extras,
    tool_failure,
    tool_governance,
    tool_invocation_event,
    tool_response,
    tool_schema,
    tool_success,
)


@tool(
    "echo",
    description="回显输入内容",
    response_format="content_and_artifact",
    extras=governance_extras(side_effects=("none",), permission_scope="test:read"),
)
def echo(message: str):
    return tool_response(tool_success(f"echo: {message}"))


@tool(
    "failer",
    description="总是失败",
    response_format="content_and_artifact",
    extras=governance_extras(side_effects=("none",), permission_scope="test:read"),
)
def failer():
    return tool_response(tool_failure("工具执行失败"))


@tool("ungoverned", description="缺少治理元数据", response_format="content_and_artifact")
def ungoverned():
    return tool_response(tool_success("ok"))


@tool(
    "dangerous",
    description="高风险操作",
    response_format="content_and_artifact",
    extras=governance_extras(
        risk_level="high",
        requires_confirmation=True,
        side_effects=("irreversible",),
        permission_scope="dangerous:execute",
        idempotency_key_required=True,
    ),
)
def dangerous(target: str):
    return tool_response(tool_success(target))


@tool(
    "rate_limited",
    description="限流测试工具",
    response_format="content_and_artifact",
    extras=governance_extras(
        side_effects=("none",),
        permission_scope="test:read",
        rate_limit_per_minute=1,
    ),
)
def rate_limited(message: str):
    return tool_response(tool_success(message))


flaky_attempts = {"count": 0}


@tool(
    "flaky",
    description="首次失败后成功",
    response_format="content_and_artifact",
    extras=governance_extras(
        side_effects=("none",),
        permission_scope="test:read",
        max_retries=1,
        retry_backoff_seconds=0,
    ),
)
def flaky():
    flaky_attempts["count"] += 1
    if flaky_attempts["count"] == 1:
        raise ToolError("temporary failure", kind="transient")
    return tool_response(tool_success("ok"))


@tool(
    "slow",
    description="超时测试工具",
    response_format="content_and_artifact",
    extras=governance_extras(
        side_effects=("none",),
        permission_scope="test:read",
        timeout_seconds=0.01,
    ),
)
def slow():
    time.sleep(0.1)
    return tool_response(tool_success("too late"))


@tool(
    "workflow_only",
    description="仅 workflow activity 调用",
    response_format="content_and_artifact",
    extras=governance_extras(
        exposure="workflow_activity",
        side_effects=("write_longterm",),
        permission_scope="test:workflow",
    ),
)
def workflow_only():
    return tool_response(tool_success("workflow"))


class TestToolExecutor:
    @pytest.fixture
    def executor(self):
        return ToolExecutor()

    def test_registers_langchain_tool(self, executor):
        executor.register(echo)
        assert len(executor) == 1
        assert executor.get("echo") is echo
        assert executor.list_tools()[0].name == "echo"

    def test_tool_schema_is_inferred_from_annotation(self):
        schema = tool_schema(echo)
        assert schema["properties"]["message"]["type"] == "string"
        assert schema["required"] == ["message"]

    def test_tool_metadata_carries_governance(self):
        governance = tool_governance(dangerous)
        assert governance.exposure == "public_agent"
        assert governance.risk_level == "high"
        assert governance.requires_confirmation is True
        assert governance.side_effects == ("irreversible",)
        assert governance.permission_scope == "dangerous:execute"
        assert governance.idempotency_key_required is True
        assert governance.timeout_seconds == 30.0
        assert governance.max_retries == 0

    def test_tool_without_governance_is_rejected(self):
        with pytest.raises(ValueError):
            tool_governance(ungoverned)

    def test_tool_invocation_event_has_audit_shape(self):
        event = tool_invocation_event(
            dangerous,
            tool_call_id="call-1",
            input={"target": "note-1", "idempotency_key": "idem-1"},
            output=tool_success({"deleted": True}),
            execution_mode="direct",
            step_id="step-1",
            thread_id="thread-1",
            user_id="user-1",
            latency_ms=12.3,
        )

        assert event.tool_name == "dangerous"
        assert event.artifact_ok is True
        assert event.exposure == "public_agent"
        assert event.risk_level == "high"
        assert event.requires_confirmation is True
        assert event.side_effects == ["irreversible"]
        assert event.permission_scope == "dangerous:execute"
        assert event.side_effect_id == "idem-1"
        assert event.attempts == 1
        assert event.timed_out is False
        assert event.rate_limited is False
        assert event.timeout_seconds == 30.0
        assert event.max_retries == 0

    def test_invokes_directly_for_non_graph_callers(self, executor):
        executor.register(echo)
        result = executor.invoke_direct("echo", message="hello")
        assert result["ok"] is True
        assert result["data"] == "echo: hello"

    def test_missing_tool_returns_error(self, executor):
        result = executor.invoke_direct("nonexistent")
        assert result["ok"] is False
        assert "未找到工具" in result["error"]

    def test_tool_failure_artifact_is_returned(self, executor):
        executor.register(failer)
        result = executor.invoke_direct("failer")
        assert result["ok"] is False
        assert "工具执行失败" in result["error"]

    def test_direct_invocation_validates_required_argument(self, executor):
        executor.register(echo)
        result = executor.invoke_direct("echo")
        assert result["ok"] is False
        assert "message" in result["error"]

    def test_overwrite_keeps_single_tool(self, executor):
        executor.register(echo)
        executor.register(echo)
        assert len(executor) == 1

    def test_list_tools_can_filter_by_exposure(self, executor):
        executor.register(echo)
        executor.register(workflow_only)

        public = executor.list_tools(exposures={"public_agent"})
        workflow = executor.list_tools(exposures={"workflow_activity"})

        assert [tool.name for tool in public] == ["echo"]
        assert [tool.name for tool in workflow] == ["workflow_only"]

    def test_direct_invocation_records_gateway_audit(self):
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(echo)

        result = executor.invoke_direct("echo", message="hello", user_id="u1")

        assert result["ok"] is True
        assert len(sink.events) == 1
        assert sink.events[0].tool_name == "echo"
        assert sink.events[0].execution_mode == "direct"
        assert sink.events[0].user_id == "u1"

    def test_high_risk_confirmed_execution_requires_idempotency_key(self):
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(dangerous)

        result = executor.invoke_direct("dangerous", target="note-1", confirmed=True)

        assert result["ok"] is False
        assert "idempotency_key" in result["error"]
        assert sink.events[0].artifact_ok is False

    def test_gateway_blocks_react_write_tool_even_if_prompt_allows_it(self):
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(dangerous)

        state = AgentGraphState(
            react=ReactSubState(allowed_tools=["dangerous"]),
            tool_tracking=ToolTrackingSubState(active_context="react", pending_call_id="call-1"),
            tool_messages=[
                AIMessage(content="", tool_calls=[{
                    "name": "dangerous",
                    "args": {"target": "note-1", "confirmed": True, "idempotency_key": "idem-1"},
                    "id": "call-1",
                    "type": "tool_call",
                }])
            ],
        )
        message = executor.graph_node()(state)["tool_messages"][0]
        result = message.artifact

        assert result["ok"] is False
        assert "不允许在 ReAct" in result["error"]
        assert sink.events[0].execution_mode == "react"

    def test_gateway_rate_limits_per_user_and_tool(self):
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(rate_limited)

        first = executor.invoke_direct("rate_limited", message="one", user_id="u1")
        second = executor.invoke_direct("rate_limited", message="two", user_id="u1")
        other_user = executor.invoke_direct("rate_limited", message="three", user_id="u2")

        assert first["ok"] is True
        assert second["ok"] is False
        assert "速率限制" in second["error"]
        assert other_user["ok"] is True
        assert sink.events[1].rate_limited is True

    def test_gateway_denies_tool_blocked_by_policy_override(self):
        from personal_agent.governance.policy import PolicyEngine, PolicyRules

        sink = InMemoryToolAuditSink()
        engine = PolicyEngine(PolicyRules(deny_tools=frozenset({"echo"})))
        executor = ToolExecutor(audit_sink=sink, policy_engine=engine)
        executor.register(echo)

        result = executor.invoke_direct("echo", message="hi", user_id="u1")

        assert result["ok"] is False
        assert "被策略禁止" in result["error"]
        assert sink.events[0].artifact_ok is False

    def test_gateway_retries_transient_exception(self):
        flaky_attempts["count"] = 0
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(flaky)

        result = executor.invoke_direct("flaky")

        assert result["ok"] is True
        assert result["data"] == "ok"
        assert flaky_attempts["count"] == 2
        assert sink.events[0].attempts == 2

    def test_gateway_times_out_tool_execution(self):
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(slow)

        result = executor.invoke_direct("slow")

        assert result["ok"] is False
        assert "超时" in result["error"]
        assert sink.events[0].timed_out is True

    def test_explicit_args_schema_rejects_invalid_web_search_limit(self):
        from personal_agent.tools.web_search import WebSearchArgs

        with pytest.raises(ValidationError):
            WebSearchArgs.model_validate({"query": "agent tools", "limit": 99})

    def test_web_search_provider_factory_uses_configured_provider(self):
        from personal_agent.application.capture.providers.web_search import (
            TavilyWebSearchProvider,
            build_web_search_provider,
        )
        from personal_agent.kernel.config import Settings, WebSearchConfig

        settings = Settings(
            web_search=WebSearchConfig(provider="tavily", api_key="test-key")
        )

        assert isinstance(build_web_search_provider(settings), TavilyWebSearchProvider)

    def test_tavily_provider_uses_generic_web_search_config(self, monkeypatch: pytest.MonkeyPatch):
        from personal_agent.application.capture.providers import web_search as web_search_module
        from personal_agent.application.capture.providers.web_search import TavilyWebSearchProvider
        from personal_agent.kernel.config import Settings, WebSearchConfig

        captured = {}

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    "results": [
                        {
                            "title": "Result",
                            "url": "https://example.com",
                            "content": "Snippet",
                            "published_date": "2026-01-01",
                        }
                    ]
                }).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return DummyResponse()

        monkeypatch.setattr(web_search_module, "urlopen", fake_urlopen)
        settings = Settings(
            web_search=WebSearchConfig(
                provider="tavily",
                api_key="test-key",
                base_url="https://search.example",
                timeout_ms=9000,
            )
        )

        results = TavilyWebSearchProvider(settings).search("agent tools", limit=3)

        assert captured["url"] == "https://search.example/search"
        assert captured["headers"]["Authorization"] == "Bearer test-key"
        assert captured["payload"]["max_results"] == 3
        assert captured["timeout"] == 9
        assert results[0].source == "tavily"

    def test_web_search_scrape_respects_allowed_domains(self):
        from personal_agent.application.capture.providers.web_search import WebSearchResult
        from personal_agent.kernel.config import Settings, WebSearchConfig
        from personal_agent.tools.web_search import build_web_search_tool

        captured_urls: list[str] = []

        class DummyProvider:
            name = "dummy"

            def search(self, query: str, limit: int = 5):
                return [
                    WebSearchResult(
                        title="Allowed",
                        url="https://allowed.example/page",
                        snippet="Allowed snippet",
                        source="dummy",
                    ),
                    WebSearchResult(
                        title="Blocked",
                        url="https://blocked.example/page",
                        snippet="Blocked snippet",
                        source="dummy",
                    ),
                ]

        class DummyCaptureService:
            def capture_text_from_url(self, url: str) -> str:
                captured_urls.append(url)
                return f"body for {url}"

        settings = Settings(
            web_search=WebSearchConfig(
                provider="tavily",
                api_key="test-key",
                allowed_domains=("allowed.example",),
            )
        )
        search_tool = build_web_search_tool(
            settings,
            DummyProvider(),
            capture_service=DummyCaptureService(),
        )

        message = search_tool.invoke({
            "name": "web_search",
            "args": {"query": "agent tools", "scrape": True},
            "id": "call-1",
            "type": "tool_call",
        })

        assert captured_urls == ["https://allowed.example/page"]
        results = message.artifact.data["results"]
        assert "body for https://allowed.example/page" in results[0]["snippet"]
        assert "已跳过抓取" in results[1]["snippet"]

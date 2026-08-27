from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
from langchain_core.tools import tool
from pydantic import ValidationError

from personal_agent.capabilities.contracts.grants import GrantDependencySet, ProcedureNodeGrant
from personal_agent.governance import InMemoryToolAuditSink, ToolExecutor, ToolGateway, ToolGatewayContext
from personal_agent.kernel.contracts.resource import OperationScope, ResourceSelector
from personal_agent.kernel.contracts.scope import interaction_execution_scope
from personal_agent.tools import (
    ToolError,
    build_capture_text_tool,
    build_inspect_knowledge_gaps_tool,
    governance_extras,
    tool_failure,
    tool_governance,
    tool_invocation_event,
    tool_response,
    tool_schema,
    tool_success,
)


def _scope(user_id: str = "u1", task_id: str = "direct"):
    return interaction_execution_scope(
        tenant_id="tenant-1",
        user_id=user_id,
        execution_id=f"run-{user_id}",
        task_id=task_id,
    )


def test_capture_text_timeout_covers_complete_ingestion_transaction() -> None:
    capture_text = build_capture_text_tool(lambda **_kwargs: None)

    assert tool_governance(capture_text).timeout_seconds == 180.0
    assert tool_governance(capture_text).idempotency_key_required is True


def test_inspect_knowledge_gaps_is_available_to_public_agent() -> None:
    inspect_knowledge_gaps = build_inspect_knowledge_gaps_tool(SimpleNamespace())

    governance = tool_governance(inspect_knowledge_gaps)
    assert governance.exposure == "public_agent"
    assert governance.side_effects == ("read_longterm",)


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


idempotent_write_calls = {"count": 0}


@tool(
    "idempotent_write",
    description="可重放 receipt 的写入测试工具",
    response_format="content_and_artifact",
    extras=governance_extras(
        side_effects=("write_longterm",),
        permission_scope="test:write",
        idempotency_key_required=True,
    ),
)
def idempotent_write(target: str):
    idempotent_write_calls["count"] += 1
    return tool_response(tool_success({"target": target, "receipt": "receipt-1"}))


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
        result = executor.invoke_direct("echo", execution_scope=_scope(), message="hello")
        assert result["ok"] is True
        assert result["data"] == "echo: hello"

    def test_missing_tool_returns_error(self, executor):
        result = executor.invoke_direct("nonexistent", execution_scope=_scope())
        assert result["ok"] is False
        assert "未找到工具" in result["error"]

    def test_tool_failure_artifact_is_returned(self, executor):
        executor.register(failer)
        result = executor.invoke_direct("failer", execution_scope=_scope())
        assert result["ok"] is False
        assert "工具执行失败" in result["error"]

    def test_direct_invocation_validates_required_argument(self, executor):
        executor.register(echo)
        result = executor.invoke_direct("echo", execution_scope=_scope())
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

        result = executor.invoke_direct(
            "echo", execution_scope=_scope(), message="hello"
        )

        assert result["ok"] is True
        assert len(sink.events) == 1
        assert sink.events[0].tool_name == "echo"
        assert sink.events[0].execution_mode == "direct"
        assert sink.events[0].user_id == "tenant-1:u1"

    def test_high_risk_confirmed_execution_requires_idempotency_key(self):
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(dangerous)

        result = executor.invoke_direct(
            "dangerous",
            execution_scope=_scope(),
            target="note-1",
            confirmed=True,
        )

        assert result["ok"] is False
        assert "idempotency_key" in result["error"]
        assert sink.events[0].artifact_ok is False

    def test_gateway_replays_committed_receipt_without_duplicate_side_effect(self):
        idempotent_write_calls["count"] = 0
        executor = ToolExecutor()
        executor.register(idempotent_write)

        first = executor.invoke_direct(
            "idempotent_write",
            execution_scope=_scope(),
            target="note-1",
            confirmed=True,
            idempotency_key="idem-write-1",
        )
        replayed = executor.invoke_direct(
            "idempotent_write",
            execution_scope=_scope(),
            target="note-1",
            confirmed=True,
            idempotency_key="idem-write-1",
        )

        assert first == replayed
        assert idempotent_write_calls["count"] == 1

    def test_gateway_requires_confirmation_bound_grant_for_confirmed_high_risk_tool(self):
        gateway = ToolGateway()
        gateway.register(dangerous)
        context = ToolGatewayContext(
            execution_scope=_scope(task_id="step-confirm"),
            execution_mode="invocation_batch",
            tool_call_id="call-confirm",
        )
        grant = ProcedureNodeGrant(
            request_id="request-confirm",
            action_ref="action-confirm",
            authorization_digest="authorization-digest",
            execution_command_digest="command-digest",
            granted_resource_selector=ResourceSelector(),
            granted_operation_scope=OperationScope(operations=frozenset({"delete"})),
            granted_data_egress="none",
            granted_credential_mode="none",
            retry_family_id="retry-confirm",
            dependency_set=GrantDependencySet(
                task_revision=1,
                goal_definition_fingerprint="goal-fingerprint",
                action_fingerprint="action-fingerprint",
                capability_definition_revision=1,
                authority_revision=1,
                policy_bundle_hash="policy-hash",
            ),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
            procedure_run_id="procedure-run",
            node_id="step-confirm",
            capability_ref="capability-dangerous",
            provider_binding_ref="test:dangerous",
        )

        rejected = gateway.invoke(
            "dangerous",
            {"target": "note-1", "confirmed": True, "idempotency_key": "idem-1"},
            context,
            grant=grant,
        )

        assert rejected["ok"] is False
        assert "confirmation-bound grant" in rejected["error"]

        confirmed = gateway.invoke(
            "dangerous",
            {"target": "note-1", "confirmed": True, "idempotency_key": "idem-2"},
            context,
            grant=grant.model_copy(update={"required_confirmation_ref": "step-confirm"}),
        )

        assert confirmed["ok"] is True

    def test_gateway_rate_limits_per_user_and_tool(self):
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(rate_limited)

        first = executor.invoke_direct(
            "rate_limited", execution_scope=_scope("u1"), message="one"
        )
        second = executor.invoke_direct(
            "rate_limited", execution_scope=_scope("u1"), message="two"
        )
        other_user = executor.invoke_direct(
            "rate_limited", execution_scope=_scope("u2"), message="three"
        )

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

        result = executor.invoke_direct(
            "echo", execution_scope=_scope(), message="hi"
        )

        assert result["ok"] is False
        assert "被策略禁止" in result["error"]
        assert sink.events[0].artifact_ok is False

    def test_gateway_retries_transient_exception(self):
        flaky_attempts["count"] = 0
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(flaky)

        result = executor.invoke_direct("flaky", execution_scope=_scope())

        assert result["ok"] is True
        assert result["data"] == "ok"
        assert flaky_attempts["count"] == 2
        assert sink.events[0].attempts == 2

    def test_gateway_times_out_tool_execution(self):
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(slow)

        result = executor.invoke_direct("slow", execution_scope=_scope())

        assert result["ok"] is False
        assert "超时" in result["error"]
        assert sink.events[0].timed_out is True

    def test_explicit_args_schema_rejects_invalid_web_search_limit(self):
        from personal_agent.tools.web_search import WebSearchArgs

        with pytest.raises(ValidationError):
            WebSearchArgs.model_validate({"query": "agent tools", "limit": 99})

        with pytest.raises(ValidationError):
            WebSearchArgs.model_validate({"query": "x" * 401})

    def test_web_search_provider_factory_uses_configured_provider(self):
        from personal_agent.application.capture.providers.web_search import (
            AnySearchWebSearchProvider,
            SerpApiWebSearchProvider,
            TavilyWebSearchProvider,
            build_web_search_provider,
        )
        from personal_agent.kernel.config import Settings, WebSearchConfig

        settings = Settings(
            web_search=WebSearchConfig(provider="tavily", api_key="test-key")
        )

        assert isinstance(build_web_search_provider(settings), TavilyWebSearchProvider)

        settings = Settings(
            web_search=WebSearchConfig(provider="serpapi", api_key="test-key")
        )

        assert isinstance(build_web_search_provider(settings), SerpApiWebSearchProvider)

        settings = Settings(
            web_search=WebSearchConfig(provider="anysearch", api_key="test-key")
        )

        assert isinstance(build_web_search_provider(settings), AnySearchWebSearchProvider)

    def test_web_search_provider_defaults_to_anysearch(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from personal_agent.application.capture.providers.web_search import (
            AnySearchWebSearchProvider,
            build_web_search_provider,
        )
        from personal_agent.kernel.config import Settings

        monkeypatch.delenv("PERSONAL_AGENT_WEB_SEARCH_PROVIDER", raising=False)
        settings = Settings.from_env()

        assert settings.web_search.provider == "anysearch"
        assert isinstance(build_web_search_provider(settings), AnySearchWebSearchProvider)

    def test_anysearch_provider_uses_unified_search_contract(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from personal_agent.application.capture.providers import web_search as web_search_module
        from personal_agent.application.capture.providers.web_search import AnySearchWebSearchProvider
        from personal_agent.kernel.config import Settings, WebSearchConfig

        captured = {}

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    "code": 0,
                    "message": "success",
                    "data": {
                        "results": [
                            {
                                "title": "Official result",
                                "url": "https://example.com/result",
                                "content": "Structured content.",
                                "published_at": "2026-08-21",
                            },
                            {
                                "title": "Overflow result",
                                "url": "https://example.com/overflow",
                                "snippet": "Must be truncated by the Adapter.",
                            },
                        ],
                        "metadata": {"total_results": 2},
                    },
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
                provider="anysearch",
                api_key="anysearch-token",
                base_url="https://api.anysearch.com",
                timeout_ms=9000,
            )
        )

        results = AnySearchWebSearchProvider(settings).search("agent tools", limit=1)

        assert captured["url"] == "https://api.anysearch.com/v1/search"
        assert captured["headers"]["Authorization"] == "Bearer anysearch-token"
        assert captured["headers"]["X-anysearch-client"] == "personal-agent/1.0"
        assert captured["payload"] == {
            "max_results": 1,
            "query": "agent tools",
        }
        assert captured["timeout"] == 9
        assert len(results) == 1
        assert results[0].source == "anysearch"
        assert results[0].url == "https://example.com/result"
        assert results[0].snippet == "Structured content."
        assert results[0].published_at == "2026-08-21"

    def test_anysearch_provider_rejects_http_200_business_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from personal_agent.application.capture.providers import web_search as web_search_module
        from personal_agent.application.capture.providers.web_search import AnySearchWebSearchProvider
        from personal_agent.kernel.config import Settings, WebSearchConfig

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    "code": 401,
                    "message": "API key authentication failed",
                    "data": None,
                }).encode("utf-8")

        monkeypatch.setattr(
            web_search_module,
            "urlopen",
            lambda *_args, **_kwargs: DummyResponse(),
        )
        settings = Settings(
            web_search=WebSearchConfig(provider="anysearch", api_key="invalid")
        )

        with pytest.raises(PermissionError, match="code 401"):
            AnySearchWebSearchProvider(settings).search("agent tools")

    def test_anysearch_provider_allows_documented_anonymous_access(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from personal_agent.application.capture.providers import web_search as web_search_module
        from personal_agent.application.capture.providers.web_search import AnySearchWebSearchProvider
        from personal_agent.kernel.config import Settings, WebSearchConfig

        captured = {}

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"code": 0, "data": {"results": []}}).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["headers"] = dict(request.header_items())
            return DummyResponse()

        monkeypatch.setattr(web_search_module, "urlopen", fake_urlopen)
        settings = Settings(
            web_search=WebSearchConfig(provider="anysearch", api_key=None)
        )

        assert AnySearchWebSearchProvider(settings).search("agent tools") == []
        assert "Authorization" not in captured["headers"]

    def test_serpapi_provider_uses_google_organic_results_contract(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from urllib.parse import parse_qs, urlparse

        from personal_agent.application.capture.providers import web_search as web_search_module
        from personal_agent.application.capture.providers.web_search import (
            SerpApiWebSearchProvider,
        )
        from personal_agent.kernel.config import Settings, WebSearchConfig

        captured = {}

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    "search_metadata": {"status": "Success"},
                    "organic_results": [{
                        "title": "Official release",
                        "link": "https://example.com/release",
                        "snippet": "Released with typed contracts.",
                        "date": "Jun 30, 2025",
                    }, {
                        "title": "Ignored overflow result",
                        "link": "https://example.com/overflow",
                        "snippet": "The Adapter must enforce the requested limit.",
                    }],
                }).encode("utf-8")

        def fake_urlopen(request, timeout):
            parsed = urlparse(request.full_url)
            captured["base_url"] = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            captured["query"] = parse_qs(parsed.query)
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return DummyResponse()

        monkeypatch.setattr(web_search_module, "urlopen", fake_urlopen)
        settings = Settings(
            web_search=WebSearchConfig(
                provider="serpapi",
                api_key="serpapi-key",
                base_url="https://serpapi.example",
                timeout_ms=9000,
            )
        )

        results = SerpApiWebSearchProvider(settings).search("agent tools", limit=1)

        assert captured["base_url"] == "https://serpapi.example/search.json"
        assert captured["query"] == {
            "api_key": ["serpapi-key"],
            "engine": ["google"],
            "hl": ["en"],
            "num": ["1"],
            "q": ["agent tools"],
        }
        assert captured["headers"]["Accept"] == "application/json"
        assert captured["timeout"] == 9
        assert len(results) == 1
        assert results[0].source == "serpapi"
        assert results[0].url == "https://example.com/release"
        assert results[0].published_at == "Jun 30, 2025"

    def test_serpapi_provider_does_not_turn_provider_error_into_empty_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from personal_agent.application.capture.providers import web_search as web_search_module
        from personal_agent.application.capture.providers.web_search import (
            SerpApiWebSearchProvider,
        )
        from personal_agent.kernel.config import Settings, WebSearchConfig

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"error": "Invalid API key"}).encode("utf-8")

        monkeypatch.setattr(
            web_search_module,
            "urlopen",
            lambda *_args, **_kwargs: DummyResponse(),
        )
        settings = Settings(
            web_search=WebSearchConfig(provider="serpapi", api_key="invalid-key")
        )

        with pytest.raises(RuntimeError, match="SerpAPI search failed"):
            SerpApiWebSearchProvider(settings).search("agent tools")

    def test_serpapi_provider_treats_google_no_results_as_valid_empty_result(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from personal_agent.application.capture.providers import web_search as web_search_module
        from personal_agent.application.capture.providers.web_search import (
            SerpApiWebSearchProvider,
        )
        from personal_agent.kernel.config import Settings, WebSearchConfig

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    "error": "Google hasn't returned any results for this query.",
                }).encode("utf-8")

        monkeypatch.setattr(
            web_search_module,
            "urlopen",
            lambda *_args, **_kwargs: DummyResponse(),
        )
        settings = Settings(
            web_search=WebSearchConfig(provider="serpapi", api_key="test-key")
        )

        assert SerpApiWebSearchProvider(settings).search("too narrow") == []

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

    def test_tavily_provider_does_not_turn_rejected_query_into_empty_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from personal_agent.application.capture.providers import web_search as web_search_module
        from personal_agent.application.capture.providers.web_search import TavilyWebSearchProvider
        from personal_agent.kernel.config import Settings, WebSearchConfig

        def rejected(*_args, **_kwargs):
            raise HTTPError(
                "https://search.example/search",
                400,
                "Bad Request",
                None,
                BytesIO(b'{"detail":"query too long"}'),
            )

        monkeypatch.setattr(web_search_module, "urlopen", rejected)
        settings = Settings(
            web_search=WebSearchConfig(
                provider="tavily",
                api_key="test-key",
                base_url="https://search.example",
            )
        )

        with pytest.raises(ValueError, match="HTTP 400"):
            TavilyWebSearchProvider(settings).search("x" * 401)

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
        assert tool_governance(search_tool).timeout_seconds == 60.0

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

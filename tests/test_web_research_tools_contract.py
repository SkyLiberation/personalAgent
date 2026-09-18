"""发现/指定来源读取的责任边界 Contract；不替模型决策，不作为 Product E2E。"""

import pytest
from pydantic import ValidationError

from personal_agent.application.capture.models import UrlCaptureResult
from personal_agent.application.capture.providers.web_search import WebSearchProvider
from personal_agent.application.capture.web_source import WebReadOutput, WebSearchArgs
from personal_agent.governance import ToolExecutor
from personal_agent.kernel.config import Settings, WebSearchConfig
from personal_agent.kernel.contracts.scope import interaction_execution_scope
from personal_agent.kernel.models import WebSearchResult
from personal_agent.orchestration.runtime import AgentRuntime
from personal_agent.tools.web_read import build_web_read_tool
from personal_agent.tools.web_search import build_web_search_tool


class _Search(WebSearchProvider):
    def search(self, query: str, limit: int = 5):
        return [WebSearchResult(
            title=f"来源 {index}", url=f"https://example.org/{index}", snippet="发现摘要",
        ) for index in range(limit)]


class _Capture:
    def __init__(self):
        self.urls = []

    def capture_url(self, url):
        self.urls.append(url)
        return UrlCaptureResult(url=url, text="该来源的完整正文：" + url, provider="contract")


def test_search_does_not_capture_and_reader_accepts_selected_or_direct_url():
    capture = _Capture()
    executor = ToolExecutor()
    executor.register(build_web_search_tool(Settings(), _Search()))
    executor.register(build_web_read_tool(Settings(), capture))
    scope = interaction_execution_scope(tenant_id="contract", user_id="reader", execution_id="web")
    search = executor.invoke_interaction(
        "web_search", {"query": "比较公开规范", "limit": 3}, execution_scope=scope,
        tool_call_id="discover", source_platform="web",
    )
    assert search["ok"]
    assert set(search["data"]) == {"query", "limit", "results"}
    assert search["data"]["query"] == "比较公开规范" and search["data"]["limit"] == 3
    assert capture.urls == []
    for index, url in enumerate((search["data"]["results"][2]["url"], "https://example.org/direct")):
        result = executor.invoke_interaction(
            "web_read", {"url": url}, execution_scope=scope,
            tool_call_id=f"read-{index}", source_platform="web",
        )
        assert result["ok"]
        source = WebReadOutput.model_validate(result["data"])
        assert source.source_url == url
        assert source.source_text == "该来源的完整正文：" + url
    assert capture.urls == ["https://example.org/2", "https://example.org/direct"]
    with pytest.raises(ValidationError):
        WebSearchArgs(query="旧调用", scrape=True)


def test_gateway_rejects_disallowed_url_before_capture():
    capture = _Capture()
    settings = Settings(web_search=WebSearchConfig(allowed_domains=("allowed.example",)))
    executor = ToolExecutor()
    executor.register(build_web_read_tool(settings, capture))
    result = executor.invoke_interaction(
        "web_read", {"url": "https://blocked.example/spec"},
        execution_scope=interaction_execution_scope(tenant_id="contract", user_id="reader", execution_id="denied"),
        tool_call_id="denied", source_platform="web",
    )
    assert not result["ok"]
    assert result["error_kind"] == "permission"
    assert capture.urls == []


class _Unused:
    def __getattr__(self, name):
        raise AssertionError(f"注册检查不得执行业务依赖：{name}")


class _Registration:
    """仅测试生产注册函数，未替代生产 Agent 的任何语义决策。"""

    def __init__(self, *, capture):
        self.settings = Settings()
        self._tool_executor = ToolExecutor()
        self._structured_client = None
        self.capture_service = capture
        self.artifact_service = _Unused()
        self.memory = _Unused()
        self._knowledge_consolidation_use_case = _Unused()
        self._review_digest_use_case = _Unused()
        self._knowledge_gap_use_case = _Unused()
        self._research_service = _Unused()

    def _active_graph_store(self):
        return _Unused()


@pytest.mark.parametrize("available", [True, False])
def test_production_registration_exposes_reader_only_with_capture_dependency(available):
    registration = _Registration(capture=_Capture() if available else None)
    AgentRuntime._register_tools(registration)
    tools = {item.name: item for item in registration._tool_executor.list_interaction_tools()}
    assert ("web_read" in tools) is available
    assert "capture_url" not in tools
    if available:
        assert set(tools["web_read"].input_schema["properties"]) == {"url"}

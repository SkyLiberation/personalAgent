from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from personal_agent.governance import InMemoryToolAuditSink, ToolExecutor
from personal_agent.infra import mcp as mcp_module
from personal_agent.kernel.config_env import _parse_mcp_config
from personal_agent.tools import (
    build_enterprise_knowledge_search_tool,
    build_mcp_tools,
    build_raw_wiki_search_tools,
    governance_extras,
    tool_governance,
    tool_response,
    tool_schema,
    tool_success,
)
from personal_agent.kernel.config_models import EnterpriseKnowledgeConfig
from langchain_core.tools import tool


class DummyResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_parse_mcp_config_from_env_json():
    config = _parse_mcp_config(json.dumps({
        "enabled": True,
        "servers": [{
            "server_id": "docs",
            "endpoint": "https://mcp.example/rpc",
            "authorization": "Bearer token",
            "tools": [{
                "remote_name": "search",
                "name": "enterprise.search_docs",
                "business_role": "enterprise_knowledge_search",
                "risk_level": "low",
                "side_effects": ["read_longterm"],
                "permission_scope": "docs:read",
            }],
        }],
    }))

    assert config.enabled is True
    assert config.servers[0].server_id == "docs"
    assert config.servers[0].tools[0].name == "enterprise.search_docs"
    assert config.servers[0].tools[0].business_role == "enterprise_knowledge_search"
    assert config.servers[0].tools[0].side_effects == ("read_longterm",)


def test_build_mcp_tool_registers_governed_tool(monkeypatch):
    requests: list[dict] = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        requests.append(payload)
        method = payload["method"]
        if method == "initialize":
            return DummyResponse({"jsonrpc": "2.0", "id": payload["id"], "result": {}})
        if method == "notifications/initialized":
            return DummyResponse({})
        if method == "tools/list":
            return DummyResponse({
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "tools": [{
                        "name": "search",
                        "description": "Search docs",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search query"},
                                "limit": {"type": "integer", "default": 5},
                            },
                            "required": ["query"],
                        },
                    }]
                },
            })
        if method == "tools/call":
            assert payload["params"]["name"] == "search"
            assert payload["params"]["arguments"] == {"query": "agent", "limit": 2}
            return DummyResponse({
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "content": [{"type": "text", "text": "found docs"}],
                    "structuredContent": {"count": 1},
                },
            })
        raise AssertionError(method)

    monkeypatch.setattr(mcp_module, "urlopen", fake_urlopen)
    config = _parse_mcp_config(json.dumps({
        "enabled": True,
        "servers": [{
            "server_id": "docs",
            "endpoint": "https://mcp.example/rpc",
            "tools": [{
                "remote_name": "search",
                "name": "enterprise.search_docs",
                "business_role": "enterprise_knowledge_search",
                "side_effects": ["read_longterm"],
                "permission_scope": "docs:read",
                "timeout_seconds": 3,
            }],
        }],
    }))

    tools = build_mcp_tools(config)

    assert [tool.name for tool in tools] == ["enterprise.search_docs"]
    schema = tool_schema(tools[0])
    assert schema["properties"]["query"]["type"] == "string"
    assert schema["required"] == ["query"]
    governance = tool_governance(tools[0])
    assert governance.side_effects == ("read_longterm",)
    assert governance.permission_scope == "docs:read"
    assert governance.timeout_seconds == 3
    assert tools[0].extras["mcp"]["business_role"] == "enterprise_knowledge_search"

    sink = InMemoryToolAuditSink()
    executor = ToolExecutor(audit_sink=sink)
    executor.register(tools[0])
    result = executor.invoke_direct(
        "enterprise.search_docs",
        query="agent",
        limit=2,
        user_id="u1",
    )

    assert result["ok"] is True
    assert result["data"]["provider"] == "mcp"
    assert result["data"]["text"] == "found docs"
    assert result["data"]["structured_content"] == {"count": 1}
    assert sink.events[0].tool_name == "enterprise.search_docs"
    assert sink.events[0].permission_scope == "docs:read"
    assert [request["method"] for request in requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]


def test_enterprise_knowledge_search_wraps_mcp_business_sources():
    @tool(
        "enterprise.search_docs",
        description="Search enterprise docs",
        response_format="content_and_artifact",
        extras={
            **governance_extras(
                side_effects=("read_longterm",),
                permission_scope="docs:read",
            ),
            "mcp": {
                "server_id": "docs",
                "remote_name": "search",
                "business_role": "enterprise_knowledge_search",
            },
        },
    )
    def enterprise_search_docs(query: str, limit: int = 5):
        return tool_response(tool_success({
            "structured_content": {
                "results": [{
                    "id": "doc-1",
                    "title": "Agent framework design",
                    "content": f"{query} appears in the enterprise framework design.",
                    "url": "https://docs.example/agent-framework",
                }]
            }
        }))

    sink = InMemoryToolAuditSink()
    executor = ToolExecutor(audit_sink=sink)
    executor.register(enterprise_search_docs)
    executor.register(build_enterprise_knowledge_search_tool(executor))

    result = executor.invoke_direct(
        "enterprise_knowledge_search",
        query="Agent framework",
        limit=3,
        user_id="alice",
    )

    assert result["ok"] is True
    assert result["data"]["results"] == [{
        "id": "doc-1",
        "title": "Agent framework design",
        "content": "Agent framework appears in the enterprise framework design.",
        "url": "https://docs.example/agent-framework",
        "source": "enterprise.search_docs",
        "raw": {
            "id": "doc-1",
            "title": "Agent framework design",
            "content": "Agent framework appears in the enterprise framework design.",
            "url": "https://docs.example/agent-framework",
        },
    }]
    assert [event.tool_name for event in sink.events] == [
        "enterprise.search_docs",
        "enterprise_knowledge_search",
    ]


def test_enterprise_knowledge_search_wraps_raw_wiki_provider():
    wiki_root = Path("data") / f"test-raw-wiki-{uuid4().hex}" / "raw"
    try:
        wiki_root.mkdir(parents=True)
        (wiki_root / "Agent Framework.md").write_text(
            "# Agent Framework\n\nworkflow-first planner, ToolGateway, MCP provider, verifier.",
            encoding="utf-8",
        )
        (wiki_root / "Unrelated.md").write_text("database isolation notes", encoding="utf-8")
        config = EnterpriseKnowledgeConfig(raw_roots=(wiki_root,))

        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        for source_tool in build_raw_wiki_search_tools(config):
            executor.register(source_tool)
        executor.register(build_enterprise_knowledge_search_tool(executor))

        result = executor.invoke_direct(
            "enterprise_knowledge_search",
            query="Agent Framework MCP",
            limit=5,
            user_id="alice",
        )

        assert result["ok"] is True
        assert result["data"]["results"][0]["title"] == "Agent Framework"
        assert result["data"]["results"][0]["source"].startswith("enterprise.raw_wiki_")
        assert "ToolGateway" in result["data"]["results"][0]["content"]
        assert [event.tool_name for event in sink.events] == [
            "enterprise.raw_wiki_raw",
            "enterprise_knowledge_search",
        ]
    finally:
        shutil.rmtree(wiki_root.parent, ignore_errors=True)

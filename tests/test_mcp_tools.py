from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

from personal_agent.capabilities.contracts.grants import AtomicCapabilityGrant, GrantDependencySet
from personal_agent.governance import InMemoryToolAuditSink, ToolExecutor
from personal_agent.governance import ToolGateway, ToolGatewayContext
from personal_agent.infra import mcp as mcp_module
from personal_agent.infra.mcp import MCPToolDefinition
from personal_agent.kernel.config_env import (
    _github_mcp_tool_config,
    _mcp_config_from_env,
    _parse_mcp_config,
)
from personal_agent.kernel.config_models import EnterpriseKnowledgeConfig, MCPServerConfig
from personal_agent.kernel.contracts.resource import OperationScope, ResourceSelector
from personal_agent.tools import (
    build_enterprise_knowledge_search_tool,
    build_mcp_capability_portfolio,
    build_mcp_tools,
    build_raw_wiki_search_tools,
    governance_extras,
    mcp_capability_from_tool,
    tool_governance,
    tool_response,
    tool_schema,
    tool_success,
)
from personal_agent.tools.mcp import build_mcp_tool
from personal_agent.tools.mcp_capability import capability_from_tool
from langchain_core.tools import tool
from tests.test_tools import _scope


class DummyResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_capture_url_capability_is_read_only() -> None:
    @tool(
        "capture_url",
        extras=governance_extras(
            side_effects=("external_network",),
            permission_scope="network:read",
        ),
    )
    def capture_url(url: str) -> str:
        """Read one URL and return its content."""
        return url

    capability = capability_from_tool(capture_url)

    assert capability.operations == ("read",)
    assert "ingest" not in capability.operations


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
                "semantic_domains": ["docs"],
                "resource_types": ["page"],
                "operations": ["search"],
                "trust_level": "scoped",
                "credential_mode": "delegated_token",
                "data_egress_class": "content",
                "attestation_status": "pinned",
                "freshness_profile": "near_realtime",
                "risk_level": "low",
                "side_effects": ["read_longterm"],
                "permission_scope": "docs:read",
                "output_contract": "ToolResult",
                "evidence_contract": "provider_output",
                "failure_semantics": "return_typed_failure",
            }],
        }],
    }))

    assert config.enabled is True
    assert config.servers[0].server_id == "docs"
    assert config.servers[0].tools[0].name == "enterprise.search_docs"
    assert config.servers[0].tools[0].business_role == "enterprise_knowledge_search"
    assert config.servers[0].tools[0].side_effects == ("read_longterm",)


def test_parse_stdio_mcp_config_from_env_json():
    config = _parse_mcp_config(json.dumps({
        "enabled": True,
        "servers": [{
            "server_id": "github",
            "transport": "stdio",
            "command": "docker",
            "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "ghcr.io/github/github-mcp-server"],
            "env": {
                "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PAT}",
                "GITHUB_READ_ONLY": "1",
            },
            "tools": [{
                "remote_name": "search_code",
                "name": "github.search_code",
                "business_role": "enterprise_knowledge_search",
                "semantic_domains": ["codebase"],
                "resource_types": ["repository", "file", "code"],
                "operations": ["search"],
                "trust_level": "scoped",
                "credential_mode": "delegated_token",
                "data_egress_class": "content",
                "attestation_status": "pinned",
                "freshness_profile": "near_realtime",
                "side_effects": ["external_network"],
                "permission_scope": "github:repo:read",
                "output_contract": "ToolResult",
                "evidence_contract": "provider_output",
                "failure_semantics": "return_typed_failure",
            }],
        }],
    }))

    assert config.enabled is True
    assert config.servers[0].transport == "stdio"
    assert config.servers[0].command == "docker"
    assert config.servers[0].args[0] == "run"
    assert config.servers[0].env["GITHUB_READ_ONLY"] == "1"
    assert config.servers[0].tools[0].name == "github.search_code"


def test_parse_mcp_config_rejects_tool_without_capability_metadata():
    import pytest

    with pytest.raises(ValueError):
        _parse_mcp_config(json.dumps({
            "enabled": True,
            "servers": [{
                "server_id": "github",
                "transport": "stdio",
                "command": "docker",
                "tools": [{
                    "remote_name": "search_code",
                    "name": "github.search_code",
                    "side_effects": ["external_network"],
                    "permission_scope": "github:repo:read",
                    "output_contract": "ToolResult",
                    "evidence_contract": "provider_output",
                    "failure_semantics": "return_typed_failure",
                }],
            }],
        }))


def test_parse_mcp_config_rejects_invalid_json():
    import pytest

    with pytest.raises(ValueError):
        _parse_mcp_config("{not-json")


def test_parse_mcp_config_rejects_non_object_payload():
    import pytest

    with pytest.raises(ValueError):
        _parse_mcp_config("[]")


def test_github_mcp_preset_from_env(monkeypatch):
    monkeypatch.setenv("PERSONAL_AGENT_GITHUB_MCP_ENABLED", "true")
    monkeypatch.setenv("PERSONAL_AGENT_GITHUB_MCP_TOKEN_ENV", "GITHUB_PAT")
    monkeypatch.delenv("PERSONAL_AGENT_NOTION_MCP_ENABLED", raising=False)
    monkeypatch.delenv("PERSONAL_AGENT_MCP_SERVERS", raising=False)

    config = _mcp_config_from_env()

    assert config.enabled is True
    server = config.servers[0]
    assert server.server_id == "github"
    assert server.transport == "stdio"
    assert server.command == "docker"
    assert "ghcr.io/github/github-mcp-server" in server.args
    assert server.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "${GITHUB_PAT}"
    assert server.env["GITHUB_READ_ONLY"] == "1"
    assert [tool.name for tool in server.tools] == [
        "github.search_code",
        "github.get_file_contents",
        "github.search_repositories",
    ]
    assert all(tool.permission_scope == "github:repo:read" for tool in server.tools)
    assert server.tools[0].semantic_domains == ("codebase",)
    assert server.tools[0].resource_types == ("repository", "file", "code")
    assert server.tools[0].operations == ("search",)
    assert server.tools[0].trust_level == "scoped"
    assert server.tools[0].credential_mode == "delegated_token"
    assert server.tools[0].data_egress_class == "content"
    assert server.tools[0].attestation_status == "pinned"


def test_notion_mcp_preset_from_env(monkeypatch):
    monkeypatch.setenv("PERSONAL_AGENT_NOTION_MCP_ENABLED", "true")
    monkeypatch.setenv("PERSONAL_AGENT_NOTION_MCP_TOKEN_ENV", "NOTION_TOKEN")
    monkeypatch.delenv("PERSONAL_AGENT_GITHUB_MCP_ENABLED", raising=False)
    monkeypatch.delenv("PERSONAL_AGENT_MCP_SERVERS", raising=False)

    config = _mcp_config_from_env()

    assert config.enabled is True
    server = config.servers[0]
    assert server.server_id == "notion"
    assert server.transport == "stdio"
    assert Path(server.command).name in {"npx", "npx.cmd"}
    assert server.args == ("-y", "@notionhq/notion-mcp-server")
    assert server.env["NOTION_TOKEN"] == "${NOTION_TOKEN}"
    assert [(tool.remote_name, tool.name) for tool in server.tools] == [
        ("API-post-search", "notion.search"),
        ("API-retrieve-page-markdown", "notion.retrieve_page_markdown"),
    ]
    assert all(tool.permission_scope == "notion:workspace:read" for tool in server.tools)
    assert server.tools[0].semantic_domains == ("personal_knowledge", "docs")
    assert server.tools[0].resource_types == ("page", "data_source")
    assert server.tools[0].operations == ("search",)
    assert server.tools[0].trust_level == "scoped"
    assert server.tools[0].credential_mode == "delegated_token"
    assert server.tools[0].data_egress_class == "content"
    assert server.tools[0].attestation_status == "pinned"


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
                "semantic_domains": ["docs"],
                "resource_types": ["page"],
                "operations": ["search"],
                "trust_level": "scoped",
                "credential_mode": "delegated_token",
                "data_egress_class": "content",
                "attestation_status": "pinned",
                "freshness_profile": "near_realtime",
                "side_effects": ["read_longterm"],
                "permission_scope": "docs:read",
                "output_contract": "ToolResult",
                "evidence_contract": "provider_output",
                "failure_semantics": "return_typed_failure",
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
    capability = mcp_capability_from_tool(tools[0])
    assert capability is not None
    assert capability.capability_id == "mcp:docs:search"
    assert capability.provider == "enterprise"
    assert capability.server_id == "docs"
    assert capability.remote_tool_name == "search"
    assert capability.local_name == "enterprise.search_docs"
    assert capability.auth_scope == "docs:read"
    assert capability.input_schema["properties"]["query"]["type"] == "string"

    sink = InMemoryToolAuditSink()
    executor = ToolExecutor(audit_sink=sink)
    executor.register(tools[0])
    result = executor.invoke_direct(
        "enterprise.search_docs",
        execution_scope=_scope(),
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


def test_mcp_optional_non_nullable_argument_accepts_none_and_omits_it():
    calls: list[dict] = []

    class RecordingClient:
        def call_tool(self, remote_name: str, arguments: dict):
            calls.append({"remote_name": remote_name, "arguments": arguments})
            return {"content": [{"type": "text", "text": "document"}]}

    mapping = _parse_mcp_config(json.dumps({
        "enabled": True,
        "servers": [{
            "server_id": "filesystem",
            "endpoint": "https://mcp.example/rpc",
            "tools": [{
                "remote_name": "read_text_file",
                "name": "filesystem.read_text_file",
                "semantic_domains": ["docs"],
                "resource_types": ["file"],
                "operations": ["read"],
                "trust_level": "scoped",
                "credential_mode": "none",
                "data_egress_class": "none",
                "attestation_status": "pinned",
                "freshness_profile": "realtime",
                "output_contract": "ToolResult",
                "evidence_contract": "provider_output",
                "failure_semantics": "return_typed_failure"
            }]
        }]
    })).servers[0].tools[0]
    server = MCPServerConfig(
        server_id="filesystem",
        endpoint="https://mcp.example/rpc",
    )
    remote = MCPToolDefinition(
        name="read_text_file",
        description="Read one text file",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "tail": {"type": "number"},
            },
            "required": ["path"],
        },
        raw={},
    )
    built = build_mcp_tool(RecordingClient(), server, mapping, remote)

    # Invoke the LangChain tool directly so its dynamically generated Pydantic
    # model validates the explicit null before the MCP adapter sees it.
    message = built.invoke({
        "name": built.name,
        "args": {"path": "D:/docs/architecture.md", "tail": None},
        "id": "call-1",
        "type": "tool_call",
    })

    assert message.artifact.ok is True
    assert calls == [{
        "remote_name": "read_text_file",
        "arguments": {"path": "D:/docs/architecture.md"},
    }]


def test_mcp_gateway_enforces_grant_resource_locator_binding():
    calls: list[dict] = []

    class RecordingClient:
        def call_tool(self, remote_name: str, arguments: dict):
            calls.append(arguments)
            return {"content": [{"type": "text", "text": "document"}]}

    mapping = _parse_mcp_config(json.dumps({
        "enabled": True,
        "servers": [{
            "server_id": "filesystem",
            "endpoint": "https://mcp.example/rpc",
            "tools": [{
                "remote_name": "read_text_file",
                "name": "filesystem.read_text_file",
                "resource_locator_arg": "path",
                "semantic_domains": ["docs"],
                "resource_types": ["file"],
                "operations": ["read"],
                "trust_level": "scoped",
                "credential_mode": "none",
                "data_egress_class": "none",
                "attestation_status": "pinned",
                "freshness_profile": "realtime",
                "output_contract": "ToolResult",
                "evidence_contract": "provider_output",
                "failure_semantics": "return_typed_failure"
            }]
        }]
    })).servers[0].tools[0]
    tool = build_mcp_tool(
        RecordingClient(),
        MCPServerConfig(server_id="filesystem", endpoint="https://mcp.example/rpc"),
        mapping,
        MCPToolDefinition(
            name="read_text_file",
            description="Read one text file",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            raw={},
        ),
    )
    grant = AtomicCapabilityGrant(
        request_id="request-1",
        action_ref="step-1",
        authorization_digest="authorization-digest",
        execution_command_digest="command-digest",
        granted_resource_selector=ResourceSelector(
            semantic_domains=frozenset({"docs"}),
            resource_types=frozenset({"file"}),
            locator="D:/docs/architecture.md",
        ),
        granted_operation_scope=OperationScope(operations=frozenset({"read"})),
        granted_data_egress="none",
        granted_credential_mode="none",
        retry_family_id="retry-1",
        dependency_set=GrantDependencySet(
            task_revision=1,
            goal_definition_fingerprint="goal",
            action_fingerprint="action",
            capability_definition_revision=1,
            authority_revision=1,
            policy_bundle_hash="policy",
        ),
        capability_ref="mcp:filesystem:read_text_file",
        provider_binding_ref="mcp:filesystem.read_text_file",
    )
    gateway = ToolGateway()
    gateway.register(tool)
    context = ToolGatewayContext(
        execution_scope=_scope(task_id="step-1"),
        execution_mode="react",
        tool_call_id="call-1",
        react_allowed_tools=("filesystem.read_text_file",),
    )

    rejected = gateway.invoke(
        tool.name,
        {"path": "D:/docs/other.md"},
        context,
        grant=grant,
    )
    accepted = gateway.invoke(
        tool.name,
        {"path": "D:/docs/architecture.md"},
        context,
        grant=grant,
    )

    assert rejected["ok"] is False
    assert "resource locator" in rejected["error"]
    assert accepted["ok"] is True
    assert calls == [{"path": "D:/docs/architecture.md"}]


def test_mcp_capability_registry_indexes_governed_tools():
    server = MCPServerConfig(
        server_id="github",
        transport="stdio",
        command="docker",
    )
    client = object()
    remote = MCPToolDefinition(
        name="search_code",
        description="Search repository code",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        raw={},
    )
    tool = __import__(
        "personal_agent.tools.mcp",
        fromlist=["build_mcp_tool"],
    ).build_mcp_tool(
        client,
        server,
        _github_mcp_tool_config("search_code"),
        remote,
    )

    registry = build_mcp_capability_portfolio([tool])
    capability = registry.get("mcp:github:search_code")

    assert capability is not None
    assert capability == mcp_capability_from_tool(tool)
    assert registry.get_by_tool("github.search_code") == capability
    assert registry.by_provider("github") == (capability,)
    assert registry.by_domain("codebase") == (capability,)


def test_build_mcp_tool_supports_stdio_transport():
    root = Path("data") / f"test-mcp-stdio-{uuid4().hex}"
    server_script = root / "fake_mcp_stdio.py"
    try:
        root.mkdir(parents=True)
        server_script.write_text(
            """
import json
import os
import sys

for line in sys.stdin:
    payload = json.loads(line)
    method = payload["method"]
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {}
    elif method == "tools/list":
        result = {
            "tools": [{
                "name": "search_code",
                "description": "Search repository code",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "perPage": {"type": "integer", "default": 5}
                    },
                    "required": ["query"]
                }
            }]
        }
    elif method == "tools/call":
        args = payload["params"]["arguments"]
        result = {
            "content": [{"type": "text", "text": f"{args['query']} token={os.getenv('FAKE_MCP_TOKEN')}"}],
            "structuredContent": {
                "results": [{
                    "title": "repo/file.py",
                    "content": "matching code",
                    "url": "https://github.com/example/repo/blob/main/file.py"
                }]
            }
        }
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": result}), flush=True)
    if method == "tools/call":
        break
""".strip(),
            encoding="utf-8",
        )
        config = _parse_mcp_config(json.dumps({
            "enabled": True,
            "servers": [{
                "server_id": "github",
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-u", str(server_script)],
                "env": {"FAKE_MCP_TOKEN": "visible-to-server"},
                "tools": [{
                    "remote_name": "search_code",
                    "name": "github.search_code",
                    "business_role": "enterprise_knowledge_search",
                    "semantic_domains": ["codebase"],
                    "resource_types": ["repository", "file", "code"],
                    "operations": ["search"],
                    "trust_level": "scoped",
                    "credential_mode": "delegated_token",
                    "data_egress_class": "content",
                    "attestation_status": "pinned",
                    "freshness_profile": "near_realtime",
                    "side_effects": ["external_network"],
                    "permission_scope": "github:repo:read",
                    "output_contract": "ToolResult",
                    "evidence_contract": "provider_output",
                    "failure_semantics": "return_typed_failure",
                }],
            }],
        }))

        tools = build_mcp_tools(config)

        assert [tool.name for tool in tools] == ["github.search_code"]
        executor = ToolExecutor(audit_sink=InMemoryToolAuditSink())
        executor.register(tools[0])
        result = executor.invoke_direct(
            "github.search_code",
            execution_scope=_scope(),
            query="repo:example/repo agent",
            perPage=1,
            user_id="u1",
        )

        assert result["ok"] is True
        assert result["data"]["provider"] == "mcp"
        assert "visible-to-server" in result["data"]["text"]
        assert result["data"]["structured_content"]["results"][0]["title"] == "repo/file.py"
    finally:
        shutil.rmtree(root, ignore_errors=True)


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
        execution_scope=_scope("alice"),
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
            execution_scope=_scope("alice"),
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

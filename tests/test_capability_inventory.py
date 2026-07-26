from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.tools import tool

from personal_agent.adapters.web.routes.system import register_system_routes
from personal_agent.capabilities.inventory import (
    A2AAssemblyDefinition,
)
from personal_agent.orchestration.capability_inventory import build_runtime_capability_inventory
from personal_agent.kernel.config_models import (
    MCPConfig,
    MCPServerConfig,
    MCPToolConfig,
)
from personal_agent.kernel.contracts.agent import SubagentProfile
from personal_agent.infra.mcp import MCPToolDefinition
from personal_agent.tools.base import governance_extras
from personal_agent.tools.mcp import build_mcp_tool


def test_runtime_inventory_keeps_definition_configuration_and_health_separate() -> None:
    @tool(
        "local_read",
        description="Read local data.",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="low",
            side_effects=("none",),
        ),
    )
    def local_read(query: str) -> str:
        return query

    mapping = MCPToolConfig(
        remote_name="search_code",
        name="mcp.github.search_code",
        semantic_domains=("code",),
        resource_types=("repository",),
        operations=("search",),
        trust_level="scoped",
        credential_mode="user_token",
        data_egress_class="content",
        attestation_status="pinned",
        freshness_profile="realtime",
        output_contract="ToolResult",
        evidence_contract="provider_output",
        failure_semantics="return_typed_failure",
    )
    server = MCPServerConfig(
        server_id="github",
        endpoint="https://mcp.example/rpc",
        tools=(mapping,),
    )

    class UnusedClient:
        def call_tool(self, remote_name: str, arguments: dict):
            raise AssertionError("inventory must not call the MCP provider")

    mcp_search_code = build_mcp_tool(
        UnusedClient(),
        server,
        mapping,
        MCPToolDefinition(
            name="search_code",
            description="Search code through MCP.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            raw={},
        ),
    )
    inventory = build_runtime_capability_inventory(
        tools=(local_read, mcp_search_code),
        mcp_config=MCPConfig(
            enabled=True,
            servers=(server,),
        ),
        agent_profiles=(SubagentProfile(
            agent_id="gpt_researcher",
            provider="gpt_researcher",
            protocol="a2a_jsonrpc",
            capability_ids=("agent:gpt_researcher",),
        ),),
        a2a_assembly=(A2AAssemblyDefinition(
            agent_id="gpt_researcher",
            implementation_present=True,
            configuration_state="enabled",
        ),),
    )

    assert [item.tool_name for item in inventory.local_tools] == ["local_read"]
    assert inventory.local_tools[0].provider_availability == "not_applicable"
    assert inventory.mcp_connectors[0].configuration_state == "enabled"
    assert inventory.mcp_connectors[0].discovery_state == "discovered"
    assert inventory.mcp_connectors[0].provider_availability == "not_observed"
    assert inventory.a2a_agents[0].implementation_present is True
    assert inventory.a2a_agents[0].discovery_state == "registered_profile"
    assert inventory.a2a_agents[0].provider_availability == "not_observed"


def test_disabled_remote_config_is_reported_without_inventing_discovery() -> None:
    mapping = MCPToolConfig(
        remote_name="search",
        semantic_domains=("knowledge",),
        resource_types=("document",),
        operations=("search",),
        trust_level="external",
        credential_mode="delegated_token",
        data_egress_class="content",
        attestation_status="unknown",
        freshness_profile="unknown",
        output_contract="ToolResult",
        evidence_contract="provider_output",
        failure_semantics="return_typed_failure",
    )

    inventory = build_runtime_capability_inventory(
        tools=(),
        mcp_config=MCPConfig(
            enabled=False,
            servers=(MCPServerConfig(
                server_id="notion",
                endpoint="https://mcp.example/rpc",
                tools=(mapping,),
            ),),
        ),
        agent_profiles=(),
        a2a_assembly=(A2AAssemblyDefinition(
            agent_id="gpt_researcher",
            implementation_present=True,
            configuration_state="disabled",
        ),),
    )

    assert inventory.mcp_connectors[0].configuration_state == "disabled"
    assert inventory.mcp_connectors[0].discovery_state == "not_observed"
    assert inventory.a2a_agents[0].configuration_state == "disabled"
    assert inventory.a2a_agents[0].discovery_state == "not_observed"


def test_system_inventory_endpoint_exposes_the_derived_projection() -> None:
    inventory = build_runtime_capability_inventory(
        tools=(),
        mcp_config=MCPConfig(),
        agent_profiles=(),
        a2a_assembly=(),
    )

    class InventoryService:
        def capability_inventory(self):
            return inventory

    app = FastAPI()
    register_system_routes(app, service=InventoryService())  # type: ignore[arg-type]

    response = TestClient(app).get("/api/capabilities/inventory")

    assert response.status_code == 200
    assert response.json() == {
        "local_tools": [],
        "mcp_connectors": [],
        "a2a_agents": [],
    }

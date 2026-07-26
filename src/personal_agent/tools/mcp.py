from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import ConfigDict, Field, create_model

from personal_agent.infra.mcp import MCPError, MCPJsonRpcClient, MCPToolDefinition
from personal_agent.capabilities.contracts.execution import MCPCapability
from personal_agent.kernel.config_models import MCPConfig, MCPServerConfig, MCPToolConfig
from personal_agent.tools.base import governance_extras, tool_response, tool_success

logger = logging.getLogger(__name__)

_GATEWAY_CONTEXT_ARG_NAMES = frozenset({
    "run_id",
    "user_id",
    "session_id",
    "source_platform",
    "thread_id",
    "step_id",
})


def build_mcp_tools(config: MCPConfig) -> list[BaseTool]:
    """Build governed LangChain tools from business-approved MCP mappings."""
    if not config.enabled:
        return []
    tools: list[BaseTool] = []
    for server in config.servers:
        if not server.enabled:
            continue
        client = MCPJsonRpcClient(server)
        discovered = {tool.name: tool for tool in client.list_tools()}
        for mapping in server.tools:
            remote = discovered.get(mapping.remote_name)
            if remote is None:
                raise MCPError(
                    f"MCP server {server.server_id} does not expose tool {mapping.remote_name!r}."
                )
            tools.append(build_mcp_tool(client, server, mapping, remote))
    return tools


def build_mcp_tool(
    client: MCPJsonRpcClient,
    server: MCPServerConfig,
    mapping: MCPToolConfig,
    remote: MCPToolDefinition,
) -> BaseTool:
    tool_name = mapping.name or f"mcp.{server.server_id}.{remote.name}"
    description = mapping.description or remote.description
    properties = remote.input_schema.get("properties", {})
    if (
        mapping.resource_locator_arg is not None
        and (
            not isinstance(properties, dict)
            or mapping.resource_locator_arg not in properties
        )
    ):
        raise MCPError(
            f"MCP tool {server.server_id}.{remote.name} declares unknown "
            f"resource locator argument {mapping.resource_locator_arg!r}."
        )
    (
        args_schema,
        allowed_arg_names,
        additional_properties,
        omit_none_arg_names,
    ) = _json_schema_to_args_model(
        tool_name,
        remote.input_schema,
    )

    capability = _mcp_capability(
        server=server,
        mapping=mapping,
        remote=remote,
        tool_name=tool_name,
        description=description,
    )

    def _invoke(**kwargs: Any):
        arguments = _remote_arguments(
            kwargs,
            allowed_arg_names=allowed_arg_names,
            additional_properties=additional_properties,
            omit_none_arg_names=omit_none_arg_names,
        )
        result = client.call_tool(mapping.remote_name, arguments)
        return tool_response(tool_success(_normalize_mcp_result(
            server_id=server.server_id,
            remote_name=mapping.remote_name,
            result=result,
        )))

    return StructuredTool.from_function(
        func=_invoke,
        name=tool_name,
        description=description,
        args_schema=args_schema,
        infer_schema=False,
        response_format="content_and_artifact",
        extras={
            **governance_extras(
                exposure=mapping.exposure,  # type: ignore[arg-type]
                risk_level=mapping.risk_level,  # type: ignore[arg-type]
                requires_confirmation=mapping.requires_confirmation,
                side_effects=mapping.side_effects,  # type: ignore[arg-type]
                permission_scope=mapping.permission_scope,
                idempotency_key_required=mapping.idempotency_key_required,
                rollback_supported=mapping.rollback_supported,
                audit_required=mapping.audit_required,
                timeout_seconds=mapping.timeout_seconds,
                max_retries=mapping.max_retries,
                retry_backoff_seconds=mapping.retry_backoff_seconds,
                rate_limit_per_minute=mapping.rate_limit_per_minute,
                allowed_domains=mapping.allowed_domains,
            ),
            "mcp": {
                "server_id": server.server_id,
                "remote_name": mapping.remote_name,
                "business_role": mapping.business_role,
                "binding_group_ref": mapping.binding_group_ref,
                "resource_locator_arg": mapping.resource_locator_arg,
                "input_schema": remote.input_schema,
            },
            "mcp_capability": capability.model_dump(mode="json"),
        },
    )


def _mcp_capability(
    *,
    server: MCPServerConfig,
    mapping: MCPToolConfig,
    remote: MCPToolDefinition,
    tool_name: str,
    description: str,
) -> MCPCapability:
    provider = tool_name.split(".", 1)[0] if "." in tool_name else server.server_id
    capability_id = f"mcp:{server.server_id}:{mapping.remote_name}"
    return MCPCapability.from_dimensions(
        capability_id=capability_id,
        provider=provider,
        local_name=tool_name,
        server_id=server.server_id,
        remote_tool_name=mapping.remote_name,
        description=description,
        semantic_domains=mapping.semantic_domains,
        resource_types=mapping.resource_types,
        operations=mapping.operations,  # type: ignore[arg-type]
        risk_level=mapping.risk_level,
        side_effects=mapping.side_effects,
        auth_scope=mapping.permission_scope,
        trust_level=mapping.trust_level,  # type: ignore[arg-type]
        credential_mode=mapping.credential_mode,  # type: ignore[arg-type]
        data_egress_class=mapping.data_egress_class,  # type: ignore[arg-type]
        attestation_status=mapping.attestation_status,  # type: ignore[arg-type]
        freshness_profile=mapping.freshness_profile,  # type: ignore[arg-type]
        output_contract=mapping.output_contract,
        evidence_contract=mapping.evidence_contract,
        failure_semantics=mapping.failure_semantics,
        provider_priority=mapping.provider_priority,
        input_schema=remote.input_schema,
        output_schema=mapping.output_schema,
        examples=mapping.examples,
    )


def _json_schema_to_args_model(tool_name: str, schema: dict[str, Any]):
    properties = schema.get("properties", {})
    required = set(schema.get("required", []) or [])
    additional = bool(schema.get("additionalProperties", False))
    model_name = _safe_model_name(tool_name)
    fields: dict[str, tuple[Any, Any]] = {}
    omit_none_arg_names: set[str] = set()
    if isinstance(properties, dict):
        for name, prop_schema in properties.items():
            if not isinstance(name, str) or not isinstance(prop_schema, dict):
                continue
            annotation = _annotation_from_json_schema(prop_schema)
            is_required = name in required
            if not is_required:
                # An absent JSON property and an explicit JSON null are distinct
                # at the MCP boundary. Pydantic still has to accept ``None`` when
                # a model emits null for an optional tool parameter; the adapter
                # then omits it unless the remote schema explicitly permits null.
                annotation = annotation | None
                if not _json_schema_permits_null(prop_schema):
                    omit_none_arg_names.add(name)
            default_value = ... if is_required else prop_schema.get("default", None)
            fields[name] = (
                annotation,
                Field(
                    default_value,
                    description=prop_schema.get("description"),
                ),
            )
    model = create_model(
        model_name,
        # ToolExecutor.invoke_direct passes execution context values through the
        # same kwargs dict as tool arguments. Allow extras at Pydantic validation
        # time, then strip known context fields and reject unknown business args
        # before the remote MCP call.
        __config__=ConfigDict(extra="allow"),
        **fields,
    )
    return (
        model,
        frozenset(fields.keys()),
        additional,
        frozenset(omit_none_arg_names),
    )


def _remote_arguments(
    kwargs: dict[str, Any],
    *,
    allowed_arg_names: frozenset[str],
    additional_properties: bool,
    omit_none_arg_names: frozenset[str],
) -> dict[str, Any]:
    unknown = set(kwargs) - allowed_arg_names - _GATEWAY_CONTEXT_ARG_NAMES
    if unknown and not additional_properties:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"MCP tool received unsupported argument(s): {joined}")
    if additional_properties:
        return {
            key: value
            for key, value in kwargs.items()
            if key not in _GATEWAY_CONTEXT_ARG_NAMES
            and not (key in omit_none_arg_names and value is None)
        }
    return {
        key: value
        for key, value in kwargs.items()
        if key in allowed_arg_names
        and not (key in omit_none_arg_names and value is None)
    }


def _json_schema_permits_null(schema: dict[str, Any]) -> bool:
    schema_type = schema.get("type")
    if schema_type == "null":
        return True
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    for keyword in ("anyOf", "oneOf"):
        alternatives = schema.get(keyword)
        if isinstance(alternatives, list) and any(
            isinstance(item, dict) and _json_schema_permits_null(item)
            for item in alternatives
        ):
            return True
    return False


def _annotation_from_json_schema(schema: dict[str, Any]) -> Any:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        non_null = [item for item in schema_type if item != "null"]
        schema_type = non_null[0] if non_null else "string"
    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list[Any]
    if schema_type == "object":
        return dict[str, Any]
    return Any


def _safe_model_name(tool_name: str) -> str:
    parts = re.split(r"[^0-9A-Za-z]+", tool_name)
    body = "".join(part[:1].upper() + part[1:] for part in parts if part)
    if not body or body[0].isdigit():
        body = "MCP" + body
    return f"{body}Args"


def _normalize_mcp_result(
    *,
    server_id: str,
    remote_name: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    content = result.get("content")
    text_parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
    return {
        "provider": "mcp",
        "server_id": server_id,
        "remote_name": remote_name,
        "text": "\n".join(text_parts) or None,
        "structured_content": result.get("structuredContent"),
        "content": content,
        "raw": result,
    }


__all__ = ["build_mcp_tool", "build_mcp_tools"]

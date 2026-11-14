from __future__ import annotations

import json
import logging
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for
from langchain_core.tools import BaseTool, StructuredTool

from personal_agent.infra.mcp import MCPError, MCPJsonRpcClient, MCPToolDefinition
from personal_agent.capabilities.contracts.execution import MCPCapability
from personal_agent.kernel.config_models import MCPServerConfig, MCPToolConfig
from personal_agent.tools.base import ToolError, governance_extras, tool_response, tool_success

logger = logging.getLogger(__name__)

def mcp_tool_name(server_id: str, mapping: MCPToolConfig) -> str:
    return mapping.name or f"mcp.{server_id}.{mapping.remote_name}"


def build_mcp_tool(
    client: MCPJsonRpcClient,
    server: MCPServerConfig,
    mapping: MCPToolConfig,
    remote: MCPToolDefinition,
) -> BaseTool:
    tool_name = mcp_tool_name(server.server_id, mapping)
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
    for field in mapping.model_integer_string_fields:
        field_schema = properties.get(field) if isinstance(properties, dict) else None
        if not isinstance(field_schema, dict) or field_schema.get("type") != "integer":
            raise MCPError(f"MCP tool {server.server_id}.{remote.name} cannot read integer strings for {field!r}.")
    input_schema = remote.input_schema
    validator_class = validator_for(input_schema)
    try:
        validator_class.check_schema(input_schema)
    except SchemaError as error:
        raise MCPError(f"MCP tool {tool_name!r} has an invalid input Schema: {error.message}") from error
    input_validator = validator_class(input_schema)

    capability = _mcp_capability(
        server=server,
        mapping=mapping,
        remote=remote,
        tool_name=tool_name,
        description=description,
    )
    output_validator = _output_validator(
        server_id=server.server_id,
        remote_name=mapping.remote_name,
        output_schema=mapping.output_schema,
    )

    def _invoke(**arguments: Any):
        try:
            input_validator.validate(arguments)
        except ValidationError as error:
            raise ValueError(f"Invalid MCP argument at {error.json_path}: {error.message}") from error
        result = client.call_tool(mapping.remote_name, arguments)
        _validate_mcp_result(
            server_id=server.server_id,
            remote_name=mapping.remote_name,
            result=result,
            output_validator=output_validator,
        )
        return tool_response(tool_success(_normalize_mcp_result(
            server_id=server.server_id,
            remote_name=mapping.remote_name,
            result=result,
        )))

    return StructuredTool.from_function(
        func=_invoke,
        name=tool_name,
        description=description,
        args_schema=input_schema,
        infer_schema=False,
        response_format="content_and_artifact",
        extras={
            "strict": False,
            **governance_extras(
                exposure=mapping.exposure,  # type: ignore[arg-type]
                risk_level=mapping.risk_level,  # type: ignore[arg-type]
                requires_confirmation=mapping.requires_confirmation,
                side_effects=mapping.side_effects,  # type: ignore[arg-type]
                permission_scope=mapping.permission_scope,
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
            "model_integer_string_fields": mapping.model_integer_string_fields,
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


def _output_validator(
    *,
    server_id: str,
    remote_name: str,
    output_schema: dict[str, Any] | None,
) -> Draft202012Validator | None:
    if output_schema is None:
        return None
    try:
        Draft202012Validator.check_schema(output_schema)
    except SchemaError as error:
        raise MCPError(
            f"MCP tool {server_id}.{remote_name} has an invalid output schema: "
            f"{error.message}"
        ) from error
    return Draft202012Validator(output_schema)


def _validate_mcp_result(
    *,
    server_id: str,
    remote_name: str,
    result: dict[str, Any],
    output_validator: Draft202012Validator | None,
) -> None:
    tool_identity = f"{server_id}.{remote_name}"
    if result.get("isError") is True:
        raise ToolError(
            f"MCP tool {tool_identity} returned an error result.",
            kind="unrecoverable",
        )
    if output_validator is None:
        return
    structured_content = result.get("structuredContent")
    try:
        output_validator.validate(structured_content)
    except ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ToolError(
            f"MCP tool {tool_identity} result violates its declared output schema "
            f"at {location}: {error.message}",
            kind="unrecoverable",
        ) from error

    serialized_text = _single_json_text_content(result.get("content"))
    if serialized_text is not None and serialized_text != structured_content:
        raise ToolError(
            f"MCP tool {tool_identity} result violates its declared output schema: "
            "structuredContent conflicts with its JSON text content.",
            kind="unrecoverable",
        )


def _single_json_text_content(content: Any) -> Any | None:
    if not isinstance(content, list) or len(content) != 1:
        return None
    item = content[0]
    if not isinstance(item, dict) or item.get("type") != "text":
        return None
    text = item.get("text")
    if not isinstance(text, str):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


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


__all__ = ["build_mcp_tool", "mcp_tool_name"]

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool

from personal_agent.capabilities.contracts.interaction import (
    InteractionToolCallValidation,
    InteractionToolDefinition,
)
from personal_agent.governance.policy import PolicyEngine
from personal_agent.tools.base import ToolExposure, tool_failure, tool_governance, tool_schema
from personal_agent.governance.gateway import IdempotencyStore, ToolAuditSink, ToolGateway, ToolGatewayContext

logger = logging.getLogger(__name__)

class ToolExecutor:
    """Registered LangChain tools and non-graph administrative invocation.

    Agent executions are dispatched by the LangGraph-native ``ToolGateway`` node
    embedded in the orchestration graph. ``invoke_direct`` uses the same gateway
    so non-agent callers share policy and audit behavior.
    """

    def __init__(
        self,
        audit_sink: ToolAuditSink | None = None,
        *,
        idempotency_store: IdempotencyStore | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._gateway = ToolGateway(
            audit_sink=audit_sink,
            idempotency_store=idempotency_store,
            policy_engine=policy_engine,
        )

    def register(self, tool: BaseTool) -> None:
        if tool.name in self:
            logger.warning("Tool %s is already registered, overwriting.", tool.name)
        self._gateway.register(tool)

    def list_tools(self, *, exposures: set[ToolExposure] | None = None) -> list[BaseTool]:
        tools = self._gateway.list_tools()
        if exposures is None:
            return tools
        return [
            tool for tool in tools
            if tool_governance(tool).exposure in exposures
        ]

    def get(self, name: str) -> BaseTool | None:
        return self._gateway.get(name)

    def list_interaction_tools(self) -> tuple[InteractionToolDefinition, ...]:
        definitions: list[InteractionToolDefinition] = []
        for tool in self.list_tools(exposures={"public_agent"}):
            governance = tool_governance(tool)
            side_effects = set(governance.side_effects) - {
                "none", "read_local", "read_longterm",
            }
            definitions.append(InteractionToolDefinition(
                name=tool.name,
                description=tool.description or tool.name,
                input_schema=tool_schema(tool),
                read_only=not side_effects,
                safely_retryable=not side_effects,
            ))
        return tuple(definitions)

    def validate_interaction_call(
        self,
        name: str,
        arguments: dict[str, object],
    ) -> InteractionToolCallValidation:
        tool = self.get(name)
        if tool is None:
            return InteractionToolCallValidation(
                status="capability_missing",
                message=f"Tool {name!r} is not currently available.",
            )
        try:
            if isinstance(tool.args_schema, type):
                tool.args_schema.model_validate(arguments)
        except Exception as exc:
            return InteractionToolCallValidation(
                status="invalid_arguments",
                message=str(exc),
            )
        return InteractionToolCallValidation(status="accepted")

    def interaction_call_is_safe_for_concurrency(self, name: str) -> bool:
        tool = self.get(name)
        if tool is None:
            return False
        governance = tool_governance(tool)
        return not (
            set(governance.side_effects) - {"none", "read_local", "read_longterm"}
        )

    def graph_node(self):
        return self._gateway.invoke_graph

    def invoke_direct(self, name: str, **kwargs: Any) -> dict[str, Any]:
        if name not in self:
            return tool_failure(f"未找到工具：{name}").model_dump(mode="json")
        tool_call_id = f"direct-{name}"
        return self._gateway.invoke(
            name,
            kwargs,
            ToolGatewayContext(
                execution_mode="direct",
                tool_call_id=tool_call_id,
                run_id=kwargs.get("run_id"),
                user_id=kwargs.get("user_id"),
                session_id=kwargs.get("session_id"),
                source_platform=kwargs.get("source_platform"),
            ),
        )

    def invoke_interaction(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        action_id: str,
        run_id: str,
        user_id: str,
        conversation_id: str,
        source_platform: str,
    ) -> dict[str, Any]:
        """Execute an admitted ordinary-interaction action through ToolGateway."""
        return self._gateway.invoke(
            name,
            arguments,
            ToolGatewayContext(
                execution_mode="direct",
                tool_call_id=action_id,
                run_id=run_id,
                user_id=user_id,
                session_id=conversation_id,
                source_platform=source_platform,
            ),
        )

    def __len__(self) -> int:
        return len(self.list_tools())

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

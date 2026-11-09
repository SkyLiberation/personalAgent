"""Compose the workspace use case with a dedicated governed Filesystem binding."""

from __future__ import annotations

from langchain_core.tools import BaseTool

from personal_agent.application.conversation.journal import InMemoryInteractionJournal
from personal_agent.application.conversation.workspace_changes import (
    Outcome, WorkspaceChange, WorkspaceChangeBinding, WorkspaceChangeService,
)
from personal_agent.governance.gateway import ToolAuditSink, ToolGateway
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.derivation import canonical_digest
from personal_agent.kernel.contracts.policy import PolicyEvaluator
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.contracts.tool_runtime import ToolGatewayContext
from personal_agent.kernel.observability import PolicyDecisionRecorder
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.tools.base import tool_governance


class _WorkspaceToolPort:
    def __init__(self, gateway: ToolGateway, tools: dict[str, BaseTool]) -> None:
        self._gateway = gateway
        self._tools = tools

    def permitted(self, kind, scope: ExecutionScope) -> bool:
        tool = self._tools[kind]
        return self._gateway.policy_decision(
            tool, tool_governance(tool), principal=scope.principal, source_platform="web",
        ).effect in {"allow", "require_confirmation"}

    def dispatch(self, change: WorkspaceChange, scope: ExecutionScope) -> Outcome:
        tool = self._tools[change.kind]
        result = self._gateway.invoke_confirmed(
            tool.name, change.model_dump(exclude={"kind"}),
            ToolGatewayContext(execution_scope=scope, execution_mode="direct", source_platform="web",
                               tool_call_id=scope.task_id),
        )
        return "applied" if result.get("ok") else "unknown"


def bind_workspace_changes(
    settings: Settings, mcp_tools: tuple[BaseTool, ...], *,
    policy: PolicyEvaluator, decisions: PolicyDecisionRecorder, audit: ToolAuditSink,
    journal: InMemoryInteractionJournal, prompts: PromptCatalog,
) -> tuple[WorkspaceChangeService | None, tuple[BaseTool, ...]]:
    config = settings.workspace_changes
    if config is None:
        return None, mcp_tools
    if config.principal not in (*settings.web.api_keys.values(), *settings.web.admin_api_keys.values()):
        raise ValueError("工作区授权主体须配置 Web 认证密钥")
    server = next((item for item in settings.mcp.servers
                   if item.server_id == config.server_id and item.enabled), None)
    if server is None or server.transport != "stdio":
        raise ValueError("工作区变更要求独立的 stdio 文件系统 Server")
    registered = {tool.name: tool for tool in mcp_tools}
    names = {"create_directory": config.create_directory_tool, "move_file": config.move_tool}
    gateway = ToolGateway(
        policy_engine=policy, policy_decisions=decisions, audit_sink=audit, prompts=prompts,
        application_owned_tools=frozenset(names.values()),
    )
    tools: dict[str, BaseTool] = {}
    for kind, name in names.items():
        tool = registered.get(name)
        if tool is None:
            raise ValueError(f"工作区映射不存在：{name}")
        mcp = (tool.extras or {}).get("mcp", {})
        governance = tool_governance(tool)
        if (mcp.get("server_id") != server.server_id or mcp.get("remote_name") != kind
                or governance.max_retries != 0 or not governance.requires_confirmation):
            raise ValueError(f"工作区映射须绑定原文件操作、强制确认且关闭重试：{name}")
        gateway.register(tool)
        tools[kind] = tool
    binding = WorkspaceChangeBinding(
        principal=config.principal, conversation_id=config.conversation_id, root=config.root,
        digest=canonical_digest({"workspace": config.model_dump(mode="json"), "provider": server.model_dump(mode="json")}),
    )
    service = WorkspaceChangeService(binding, _WorkspaceToolPort(gateway, tools), journal)
    return service, tuple(tool for tool in mcp_tools if tool.name not in names.values())

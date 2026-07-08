# MCP 与 A2A 当前机制总结

本文总结当前工程中 MCP 与 A2A 的目标架构和已落地状态。核心边界是：

- MCP 是工具协议，具体调用由 ToolGateway 治理。
- A2A 是外部 Agent 协议，委托运行由 AgentGateway 治理。
- WorkflowSpec 决定任务域和执行边界；LLM 不直接自由选择任意 MCP tool 或外部 Agent。

## 当前结论

| 类型 | 当前抽象 | 当前 Gateway | 当前主路径 |
| --- | --- | --- | --- |
| MCP | `MCPCapability` + governed LangChain tool | ToolGateway | task-domain workflow -> CapabilityResolver -> ReAct scoped tool allowlist -> ToolGateway |
| A2A | `AgentDefinition` / `AgentRun` / `AgentArtifact` | AgentGateway | workflow `agent_call` -> AgentGateway -> A2A adapter |

一句话说：**MCP 解决“本次任务可用哪些工具能力”，A2A 解决“本次委托哪个外部 Agent run”。**

## MCP 主路径

MCP provider 不再对应独立 workflow。当前 GitHub / Notion 已从 provider-specific workflow 收敛到 task-domain workflow：

```text
EntryInput
  -> Router
  -> external_codebase_qa / external_workspace_qa / external_project_ops
  -> ReAct step
       -> CapabilityResolver
       -> capability_resolution event
       -> scoped allowed_tools
       -> ToolGateway
       -> tool audit
  -> compose
```

当前任务域：

| Workflow | 任务域 | 当前 provider 示例 |
| --- | --- | --- |
| `external_codebase_qa` | 远程代码库、仓库、文件、README、代码实现问答 | GitHub |
| `external_workspace_qa` | 外部知识空间、页面、文档、会议纪要、PRD 问答 | Notion |
| `external_project_ops` | issue、ticket、项目上下文等项目对象 | 预留给 Jira / Linear / GitHub Issues 等 |

新增同类 MCP provider 时，默认不再新增 workflow。应新增或更新：

1. MCP config / preset。
2. MCP tool 的治理 metadata。
3. `MCPCapability` metadata。
4. `tool_quality` case。
5. `resolver_quality` case。
6. 必要时增加 e2e case，验证完整入口链路。

只有出现新的任务域时才新增 task-domain workflow。

## MCP Capability

每个 MCP tool 会标准化为 `MCPCapability`，关键字段包括：

- `capability_id`
- `provider`
- `semantic_domains`
- `resource_types`
- `operations`
- `risk_level`
- `side_effects`
- `auth_scope`
- `trust_level`
- `credential_mode`
- `data_egress_class`
- `attestation_status`
- `freshness_profile`

`CapabilityResolver` 的职责是把 `UserTask + WorkflowScope + CapabilityRegistry + CapabilitySelectionPolicy` 解析成：

- `selected_capabilities`
- `allowed_tools`
- `denied_capabilities`
- `rationale`
- `confidence`

它不执行工具；执行仍必须进入 ToolGateway。

## A2A 主路径

GPT Researcher A2A 已从 tool wrapper 主路径迁到 AgentGateway：

```text
EntryInput
  -> Router
  -> gpt_researcher_a2a
  -> gptr-a2a-research agent_call(gpt_researcher)
       -> AgentGateway
       -> GPTResearcherA2AAdapter
       -> A2A JSON-RPC
       -> AgentRun / AgentEvent / AgentArtifact(unverified)
  -> gptr-a2a-compose
```

当前 A2A adapter 支持：

- blocking invoke：`message/send` with `blocking=true`
- submit：`message/send` with `blocking=false`
- poll：`tasks/get`
- cancel：`tasks/cancel`
- stream：映射为 `AgentEvent(type="stream_delta")`

AgentGateway 支持多 Agent 注册与 definition 查询。Router 仍只选择 intent，不直接选择任意 Agent；当前 `gpt_researcher_a2a` workflow 显式引用 `agent_id="gpt_researcher"`。

## A2A 治理边界

A2A 不再由 ToolGateway 的 tool audit 作为成功标准。AgentGateway 负责：

- `AgentDefinition`
- `AgentGovernance`
- `AgentTask`
- `AgentRun`
- `AgentEvent`
- `AgentArtifact`
- `PolicyEngine(action="agent_call")`

外部 Agent 返回的 artifact 默认是 `unverified`。它不能直接冒充已验证证据；后续如果要进入长期知识或答案证据，应再经过 Evidence / Claim / Citation 相关验证链路。

## 质量门禁

当前评估分层：

| Gate | 验证对象 | 主要断言 |
| --- | --- | --- |
| `tool_quality` | MCP governed tools | risk、side effects、permission scope、timeout、retry、rate limit、capability metadata |
| `resolver_quality` | CapabilityResolver | selected / denied capabilities、local-first、read-only clamp、跨 provider composition |
| `agent_gateway_quality` | AgentGateway / A2A | AgentDefinition、AgentGovernance、AgentRun、AgentEvent、AgentArtifact、submit/poll/cancel/stream、多 Agent registry |
| `e2e_quality.github_mcp` | MCP 完整入口链路 | task-domain workflow、capability_resolution、ToolGateway audit |
| `e2e_quality.notion_mcp` | MCP 完整入口链路 | task-domain workflow、capability_resolution、ToolGateway audit、写请求边界 |
| `e2e_quality.gpt_researcher_a2a` | A2A 完整入口链路 | `agent_call`、AgentGateway、AgentRun、unverified AgentArtifact |

## 当前边界

- 不把 MCP 迁到 AgentGateway。
- 不让 A2A 通过 ToolGateway 执行。
- 不为每个 MCP provider 新增 workflow。
- 不让 LLM 直接自由选择 MCP tool。
- 不让 LLM 直接自由选择外部 Agent。
- 不让外部 Agent artifact 自动写入长期知识。

## 相关文档

- `docs/workflow/github-mcp-workflow.md`
- `docs/workflow/gpt-researcher-a2a-workflow.md`
- `docs/future/agent-gateway-a2a-mcp-design.md`
- `docs/golden-set-design.md`

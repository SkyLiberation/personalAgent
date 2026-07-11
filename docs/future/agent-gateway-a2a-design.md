# AgentGateway / A2A 设计

本文只定义外部 Agent 委托边界。MCP、CapabilityRegistry、Resolver、EvidenceSource、workflow scope 与评估门禁见 [全局 Capability Scoping 目标设计](global-capability-scoping-design.md)，不在本文重复定义。

## 目标边界

```text
Workflow step
  -> CapabilityResolver(kind=agent)  # 仅当该任务域存在候选 Agent 时
  -> AgentGateway
  -> A2A adapter / future agent protocol
  -> AgentRun + AgentEvent + AgentArtifact
```

外部 Agent 是长任务委托边界，不是 ToolGateway 的一种 tool call：

| 对象 | MCP / HTTP tool | A2A Agent |
| --- | --- | --- |
| 执行单元 | ToolInvocation | AgentRun |
| Gateway | ToolGateway | AgentGateway |
| 主要产物 | ToolArtifact | AgentEvent / AgentArtifact |
| 生命周期 | 单次调用、重试、幂等 | submit、poll、stream、cancel、状态转换 |

两个 Gateway 共享 PolicyEngine、审计、限流、凭证与 artifact 基础设施，但 A2A transport 不经过 ToolGateway。

## 当前实现

`gpt_researcher_a2a` workflow 显式使用 `agent_id="gpt_researcher"`。这是当前只有一个满足该任务域的外部 Agent 时的正确策略：Router 选择 intent，WorkflowSpec 选择 Agent，AgentGateway 执行委托。

GPT Researcher adapter 已支持：

- `invoke`：blocking `message/send`。
- `submit`：non-blocking `message/send`。
- `poll`：`tasks/get`。
- `cancel`：`tasks/cancel`。
- `stream`：映射为 `AgentEvent(type="stream_delta")`。

workflow 当前没有通用 waiting state，因此主路径只使用 blocking invoke；submit/poll/stream/cancel 是 AgentGateway API，不代表 workflow 已具备异步等待编排。

## 治理与证据

`AgentDefinition` 的 governance metadata 进入 PolicyEngine；调用前需通过 workflow scope、CapabilityResolver preflight（如启用）、PolicyEngine 与 AgentGateway。

Agent 返回的 `AgentArtifact` 默认 `unverified`。它只能作为 candidate output：

```text
AgentArtifact
  -> stored candidate output
  -> Evidence / Citation / Claim verification
  -> compose or knowledge admission
```

外部 Agent 不得直接写长期知识，也不得凭自身声明变成已验证 evidence。

## 多 Agent 选择

当同一任务域存在多个已注册 Agent 时，才启用 `CapabilityResolver(kind="agent")` 或专用 `AgentSelectionPolicy`。选择信号包括任务域、trust / attestation、data egress、成本、timeout、long-running 支持和 artifact 输出模式。

Resolver 只返回 `allowed_agents`，不能改 workflow 或自行委托 Agent；Workflow 的 `agent_call` step 与 AgentGateway 仍是唯一执行入口。

## 验收

- `agent_gateway_quality`：definition、governance、invoke / submit / poll / cancel / stream、AgentRun 与 AgentArtifact 状态。
- workflow E2E：`agent_call`、capability resolution（如适用）、AgentGateway 与 AgentRun trace 全链路存在。
- 负例：未注册 Agent、scope 外 Agent、未经授权的数据外流、未验证 artifact 直接入库必须拒绝。

## 不做什么

- 不把 MCP 迁入 AgentGateway。
- 不把 A2A transport 包装为 ToolGateway tool。
- 不让 LLM 直接自由选择未注册的外部 Agent。
- 不把 AgentArtifact 自动提升为可信 evidence 或长期知识。


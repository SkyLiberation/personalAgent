# Capability Scoping、MCP 与 A2A 当前状态

本文是当前实现摘要，不承载目标架构推演。平台级 contract、策略与评估规则以 [全局 Capability Scoping 目标设计](../future/global-capability-scoping-design.md) 为准；A2A 专项设计以 [AgentGateway / A2A 设计](../future/agent-gateway-a2a-design.md) 为准。

## 已落地边界

| 能力类别 | 发现 / 选择 | 执行边界 | 当前主路径 |
| --- | --- | --- | --- |
| MCP tool | `MCPCapability` 适配为通用 `Capability(kind="mcp_tool")` | ToolGateway | task-domain ReAct -> CapabilityResolver -> ResolutionValidator -> scoped tools -> ToolGateway |
| 内部 tool | ToolExecutor 投影为 `Capability(kind="local_tool")` | ToolGateway | deterministic tool step -> capability preflight -> ToolGateway |
| Ask evidence source | `EvidenceSourceCapability(kind="retriever")` | Retrieval pipeline；底层可由 Retriever / ToolGateway / AgentGateway 提供 | ask-retrieve -> RetrievalCapabilityPlan -> retrieval -> compose / verify / repair |
| 外部 Agent | `AgentDefinition` 投影为 `Capability(kind="agent")` | AgentGateway | explicit `agent_call` -> AgentGateway -> A2A adapter -> AgentRun / AgentArtifact |
| Workflow action | `Capability(kind="workflow_action")` | Workflow runtime | 默认只进入 registry / trace，不可由 Resolver 自由选择 |

`MCPCapability` 仍是 MCP discovery payload，不再是 Resolver 的专用输入 contract。Resolver 只接受通用 `CapabilityRegistry`。

## MCP 当前主路径

```text
EntryInput
  -> Router
  -> TaskSpec / evidence_answer pattern
  -> explore MetaStep (bounded ReAct)
       -> CapabilityResolver
       -> ResolutionValidator + PolicyEngine clamp
       -> capability_resolution event
       -> ToolGateway
       -> capability_execution event + tool audit
       -> EvidencePack
  -> compose
```

`external_codebase_qa`、`external_workspace_qa`、`external_project_ops` 当前只保留为 Router / eval 的语义标签，执行统一由 `evidence_answer` pattern 编译。GitHub 与 Notion 是当前已验证 provider。新增同类 provider 默认只补 MCP preset、governance metadata、capability metadata 与分层 eval；只有新增事务状态机时才增加 workflow。

## Ask 与 Capture

- ask 已在 retrieval stage 生成 `CapabilityResolution` 和 `RetrievalCapabilityPlan`，记录 selected / denied source、`scope_id`、`resolution_id`、lifecycle 与 escalation hint。
- 内置 local / graph / workspace / web source 已作为 `EvidenceSourceCapability` 参与选择。
- capture、维护、删除、research 等确定性 tool step 在执行前解析预期 capability；未被 resolution 放行的 tool / agent 不得执行。
- CapabilityResolver 只决定候选能力；长期写入仍受 ClaimAdmissionPolicy、DecisionPolicy、ToolGateway 与确认流程约束。

当前尚未把任意 MCP read/search 自动适配成 ask 的 evidence-source executor；该 contract 已定义，但 provider-specific source adapter 应与 citation / freshness contract 一起落地，不能只把完整 MCP toolset 暴露给 ask。

## A2A 当前主路径

```text
EntryInput
  -> Router
  -> delegated_research pattern
  -> delegate(gpt_researcher)
       -> CapabilityResolver(kind=agent) preflight
       -> AgentGateway
       -> GPTResearcherA2AAdapter
       -> A2A JSON-RPC
       -> AgentRun / AgentEvent / AgentArtifact(unverified)
  -> structural artifact verify
  -> transform
```

当前 GPT Researcher adapter 支持 blocking invoke、submit、poll、cancel 与 stream。workflow 主路径仍使用 blocking `invoke()`；若需要等待外部 Agent 的长任务，WorkflowRuntime 应显式进入 waiting state，而不是在 step 内轮询。

外部 Agent artifact 默认进入 `untrusted_observations`。当前主路径会先做结构完整性验证，再进入 transform；结构验证不等同于事实真实性，artifact 仍不能直接成为长期知识或已验证事实证据。

## 运行时不变量

- Resolver 不改变 workflow、step、allowed kinds 或 allowed operations。
- ResolutionValidator 拒绝 metadata 不可信的高风险 capability、scope 扩张和 selected / denied 重叠。
- PolicyEngine 负责授权与风险裁决；Gateway 负责具体执行和审计。
- `EscalationHint` 只是证据不足 / freshness 等信号；只有 Runtime / RePlanner 能创建新 step 或新 scope。
- MCP 不进入 AgentGateway；A2A transport 不经过 ToolGateway。

## 评估与文档所有权

| 主题 | 唯一设计文档 | 当前验证 |
| --- | --- | --- |
| Capability contract、Resolver、MCP、ask/capture scope | [global-capability-scoping-design.md](../future/global-capability-scoping-design.md) | capability / resolver / workflow execution eval |
| A2A AgentRun 与 AgentGateway | [agent-gateway-a2a-design.md](../future/agent-gateway-a2a-design.md) | agent gateway / A2A E2E eval |
| 完整入口行为 | [e2e-quality-cases.md](../evals/e2e-quality-cases.md) | GitHub MCP、Notion MCP、GPT Researcher A2A cases |

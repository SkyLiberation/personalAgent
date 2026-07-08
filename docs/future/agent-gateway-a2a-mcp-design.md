# AgentGateway / A2A / MCP 目标设计

本文设计并记录一个不考虑向后兼容的目标形态：在现有 `ToolGateway` 之外引入 `AgentGateway`，把外部 Agent 委托从“受治理工具调用”提升为一等运行边界。当前 GitHub / Notion MCP 已走 capability-first task-domain workflow；GPT Researcher A2A 已通过 AgentGateway 接入。

## 当前状态

当前外部能力分两类：

```text
MCP Server
  -> MCPJsonRpcClient
  -> governed LangChain tools
  -> ToolExecutor / ToolGateway
  -> workflow / ReAct / audit

A2A Agent
  -> A2A JSON-RPC client
  -> AgentGateway
  -> AgentRun / AgentEvent / AgentArtifact
  -> workflow / deterministic agent_call / audit
```

已经落地的实例：

| 外部能力 | 当前接入方式 | Workflow | Gateway |
| --- | --- | --- | --- |
| GitHub MCP | MCP tools + `MCPCapability` | `external_codebase_qa` | ToolGateway |
| Notion MCP | MCP tools + `MCPCapability` | `external_workspace_qa` | ToolGateway |
| GPT Researcher A2A | Agent adapter: `gpt_researcher` | `gpt_researcher_a2a` | AgentGateway |

因此，当前答案是：**A2A 已接入独立 AgentGateway；MCP 仍由 ToolGateway 执行具体工具调用。**

## 当前 MCP 问题

演进前 GitHub MCP、Notion MCP 的接入方式已经走完整链路，也受到 ToolGateway 治理；问题不在“能不能用”，而在抽象层级：

```text
github MCP -> github_repository_qa workflow
notion MCP -> notion_workspace_qa workflow
future slack MCP -> slack_workspace_qa workflow
future jira MCP -> jira_project_qa workflow
```

这种 provider-workflow coupling 会导致每接入一个 MCP provider 就新增一个 workflow。短期利于验证，但长期会把 workflow 退化成“某个工具集合的固定入口”，不够 Agentic：

- Router 过早决定 provider，而不是先理解用户任务；
- workflow 绑定外部服务，而不是绑定任务领域；
- ReAct 只能在固定 allowlist 内选择工具，无法跨 MCP server 组合能力；
- golden set 容易验证“是否走了某个 workflow”，但难以验证“是否选择了合适能力”；
- 新 MCP server 的接入成本变成新增 workflow、router 分支、e2e 分支和文档，而不是注册能力。

因此，后续 MCP 优化的重点不是继续写更多 provider-specific workflow，而是把 MCP 接入升级为 capability-first。

## 为什么需要 AgentGateway

ToolGateway 很适合治理“工具调用”：

- 参数 schema 校验
- policy / risk / confirmation
- timeout / retry / rate limit
- idempotency
- audit
- ToolArtifact 归一

但外部 Agent 与普通工具不同。A2A 这类协议天然包含：

- agent card / capability discovery
- long-running task
- async polling
- streaming event
- cancellation
- task state transition
- artifact negotiation
- cross-agent context / memory boundary
- agent selection / routing
- cost and concurrency budget

如果继续全部压进 ToolGateway，短期可行，但长期会让工具治理层承担“外部 Agent 生命周期管理”的职责，边界会变浑。

## 目标边界

目标不是替代 ToolGateway，而是分层：

```text
WorkflowRuntime
  -> Activity / Step
  -> ToolGateway       # 本地/远端工具治理
  -> AgentGateway      # 外部 Agent 委托治理
  -> ModelGateway      # LLM 调用治理
  -> HumanGate         # HITL / review
```

更具体：

```text
Entry
  -> Router
  -> WorkflowSpec
  -> StepExecutionGraph
  -> Agent Activity
       AgentGateway.invoke(agent_id, task, context)
       -> A2A / future protocols
       -> AgentRun / AgentEvent / AgentArtifact
  -> Compose
```

ToolGateway 仍然存在。AgentGateway 与 ToolGateway 应共享 `PolicyEngine`、Audit、RateLimiter、CredentialBroker、ArtifactStore 等治理基础设施，但不应通过 ToolGateway 执行 A2A transport。核心原则是：**外部 Agent 作为 AgentRun 被治理，外部工具作为 ToolInvocation 被治理。**

```text
              PolicyEngine / Audit / RateLimit
                CredentialBroker / ArtifactStore
                    ^                    ^
                    |                    |
              ToolGateway          AgentGateway
           ToolInvocation            AgentRun
```

## 概念模型

### AgentDefinition

```python
class AgentDefinition:
    agent_id: str
    provider: str              # gpt_researcher, custom_a2a, internal_agent
    protocol: str              # a2a_jsonrpc, local, http
    endpoint: str
    agent_card_url: str | None
    capabilities: list[str]
    input_modes: list[str]
    output_modes: list[str]
    governance: AgentGovernance
```

### AgentGovernance

```python
class AgentGovernance:
    exposure: str              # public_agent / scoped_agent / internal
    risk_level: str            # low / medium / high
    side_effects: tuple[str, ...]
    permission_scope: str
    trust_level: str           # internal / trusted / scoped / external / untrusted
    credential_mode: str       # delegated_token / service_token / user_token / none
    data_egress_class: str     # none / metadata / content / sensitive
    attestation_status: str    # verified / pinned / self_claimed / unknown
    allowed_domains: tuple[str, ...]
    timeout_seconds: float
    max_retries: int
    rate_limit_per_minute: int | None
    max_concurrent_tasks: int
    max_cost_usd: float | None
    audit_required: bool
    requires_confirmation: bool
```

### AgentRun

```python
class AgentRun:
    run_id: str
    workflow_run_id: str
    step_id: str
    agent_id: str
    protocol_task_id: str | None
    status: str                # submitted / working / completed / failed / canceled
    input_summary: str
    input_artifact_ids: list[str]
    output_summary: str
    output_artifact_ids: list[str]
    context_policy: dict
    trust_level: str
    data_egress_class: str
    cost_estimate: float | None
    actual_cost: float | None
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None
```

### AgentEvent

```python
class AgentEvent:
    event_id: str
    agent_run_id: str
    type: str                  # submitted / status_changed / stream_delta / artifact_created / failed
    payload: dict
    created_at: datetime
```

### AgentArtifact

外部 Agent 返回的 artifact 默认不是可信 evidence，而是 candidate output。它必须先被保存、标注来源和验证状态，再由本工程的 Evidence / Claim / Compose 链路决定能否进入最终答案。

```python
class AgentArtifact:
    artifact_id: str
    agent_run_id: str
    source_agent_id: str
    artifact_type: str          # report / citation / table / file / structured_data
    storage_uri: str
    trust_level: str            # unverified / verified / rejected
    verification_status: str    # pending / passed / failed / not_applicable
    citation_coverage: float | None
    normalized_evidence_ids: list[str]
    metadata: dict
```

目标处理链路：

```text
AgentArtifact
  -> CandidateEvidence
  -> EvidenceNormalizer
  -> ClaimVerifier / CitationChecker
  -> Compose
```

## AgentGateway API

第一阶段 API 可以很小：

```python
class AgentGateway:
    def register(self, definition: AgentDefinition) -> None: ...

    def invoke(
        self,
        agent_id: str,
        task: AgentTask,
        context: AgentGatewayContext,
    ) -> AgentRunResult: ...

    def get_run(self, agent_run_id: str) -> AgentRun: ...

    def cancel(self, agent_run_id: str, context: AgentGatewayContext) -> AgentRun: ...
```

第二阶段再扩展 streaming / async：

```python
class AgentGateway:
    def submit(self, agent_id: str, task: AgentTask, context: AgentGatewayContext) -> AgentRun: ...
    def poll(self, agent_run_id: str, context: AgentGatewayContext) -> AgentRun: ...
    def stream(self, agent_run_id: str, context: AgentGatewayContext) -> Iterator[AgentEvent]: ...
```

## A2A Adapter

GPT Researcher 的当前 A2A 调用可以迁移为 adapter：

```text
AgentGateway.invoke("gpt_researcher", task)
  -> A2AAdapter.message_send(blocking=true)
  -> normalize A2A task
  -> AgentRunResult(report, artifacts, metadata)
```

A2A adapter 负责：

- 读取 agent card；
- 校验 protocol version / capability；
- 构造 `message/send`；
- 支持 `tasks/get` polling；
- 支持 `tasks/cancel`；
- 把 A2A task status 映射为 AgentRun status；
- 把 A2A artifact 映射为 AgentArtifact；
- 把 stream event 映射为 AgentEvent。
- 发送前按 `context_policy` 做 context minimization，只发送任务必要上下文；
- 返回后标记 AgentArtifact 为 `unverified`，并触发 citation / schema / claim verification。

## MCP 与 AgentGateway 的关系

MCP 不应被强行塞进 AgentGateway。MCP 是工具协议，主要产物是 tool definition 和 tool call；A2A 是 Agent 协议，主要产物是 task / run / artifact。

目标分工：

| 协议 | 抽象 | Gateway |
| --- | --- | --- |
| MCP | ToolDefinition / ToolInvocation | ToolGateway |
| A2A | AgentDefinition / AgentRun | AgentGateway |
| HTTP API tool | ToolDefinition / ToolInvocation | ToolGateway |
| Internal worker agent | AgentDefinition / AgentRun | AgentGateway |

但二者可以组合。例如未来某个 A2A Agent 自身暴露 MCP 工具，应该表示为：

```text
AgentGateway manages agent run
  -> remote agent internally uses MCP
  -> personalAgent only audits external AgentRun boundary
```

如果 personalAgent 直接调用 MCP server，则仍走 ToolGateway。

## MCP Capability Fabric

目标形态是让 MCP 成为工具能力织网，而不是 workflow 数量的放大器：

```text
MCP Server Discovery
  -> MCP Tool Introspection
  -> MCPCapabilityRegistry
  -> Capability Index
  -> CapabilityResolver
  -> scoped allowed_tools
  -> task-domain workflow
  -> ReAct / deterministic tool_call
  -> ToolGateway
  -> audit
```

核心变化：

1. MCP server 接入只负责发现、标准化、注册能力。
2. Router 识别任务 intent / domain，不直接选择 GitHub、Notion、Slack 这类 provider。
3. Workflow 按任务领域定义，例如 `external_codebase_qa`、`external_workspace_qa`、`external_project_ops`。
4. CapabilityResolver 根据用户问题、workflow scope、policy 和权限，生成本次运行的 scoped tool allowlist。
5. ReAct 在受约束的 allowlist 内选择具体 MCP tool。
6. ToolGateway 仍负责 schema 校验、policy、执行、artifact 归一和 audit。

这不是让 LLM 自由调用任何外部工具，而是把“工具选择”从硬编码 workflow 分支提升为受治理的运行时能力解析。

## MCP Capability Metadata

MCP 工具注册时不应只保存 `name` 和 JSON schema。为了支持 Agentic 选择，需要将每个 remote tool 标准化为 capability metadata：

```python
class MCPCapability:
    capability_id: str
    provider: str               # github, notion, slack, jira
    server_id: str
    remote_tool_name: str
    local_tool_name: str         # github.search_code
    description: str
    semantic_domains: tuple[str, ...]      # codebase, docs, project, issue, knowledge
    resource_types: tuple[str, ...]        # repository, file, page, database, issue
    operations: tuple[str, ...]            # search, read, list, create, update, delete
    risk_level: str
    side_effects: tuple[str, ...]
    auth_scope: str
    trust_level: str             # trusted / scoped / external / untrusted
    credential_mode: str         # user_token / delegated_token / service_token / none
    data_egress_class: str       # none / metadata / content / sensitive
    attestation_status: str      # verified / pinned / self_claimed / unknown
    freshness_profile: str       # realtime / near_realtime / static / unknown
    provider_priority: int | None
    input_schema: dict
    output_schema: dict | None
    examples: tuple[dict, ...]
```

其中 `semantic_domains`、`resource_types`、`operations` 是 CapabilityResolver 的主要索引维度。`risk_level`、`side_effects`、`auth_scope`、`trust_level`、`credential_mode`、`data_egress_class`、`attestation_status` 则进入 ToolGateway / PolicyEngine 的治理决策。

## CapabilityResolver

CapabilityResolver 是 MCP Agentic 化的关键组件。它不执行工具，只负责把“任务需求”解析成“本次允许的工具集合”：

```python
class CapabilityResolver:
    def resolve(
        self,
        task: UserTask,
        workflow_scope: WorkflowScope,
        user_context: UserContext,
        policy_context: PolicyContext,
    ) -> CapabilityResolution:
        ...
```

输出应包含：

```python
class CapabilityResolution:
    selected_capabilities: list[MCPCapability]
    allowed_tools: tuple[str, ...]
    denied_capabilities: list[DeniedCapability]
    rationale: str
    confidence: float
```

解析依据包括：

- 用户问题里的对象类型：仓库、文件、页面、数据库、issue、项目等；
- 用户意图：搜索、读取、比较、总结、创建、更新、删除；
- workflow 允许的任务领域；
- 当前用户授权的 provider / workspace / repository scope；
- 工具风险等级与 side effects；
- e2e golden set 中定义的期望工具调用行为。

对于只读问答，Resolver 可以给 ReAct 多个 search / read 工具；对于写操作，Resolver 必须把高风险能力限制到显式 workflow step，并触发确认或 HITL。

### CapabilitySelectionPolicy

CapabilityResolver 还需要一个显式 selection policy，避免当多个 provider 都可满足任务时退化为不稳定的语义猜测：

```python
class CapabilitySelectionPolicy:
    local_first: bool
    freshness_required: bool
    explicit_provider_precedence: bool
    max_capabilities_per_step: int
    max_providers_per_step: int
    cross_provider_requires_reason: bool
    sensitive_egress_requires_confirmation: bool
    default_provider_preferences: list[str]
```

默认策略：

1. 用户显式指定 provider 时，优先对应 provider 的 capability。
2. 未指定 provider 且本地知识足够时，优先 local-first。
3. 问题包含 repo / file / code / PR / issue 时，优先 codebase / project provider。
4. 问题包含方案页 / 文档 / 知识库时，优先 workspace / doc provider。
5. 需要最新状态时，允许外部 realtime / near-realtime capability 覆盖本地旧知识。
6. 跨 provider 组合必须记录 rationale，并记录未选 provider 的原因。
7. 写能力必须来自显式 workflow step 和 policy confirmation，不能被 read-only Resolver 放出。

## Workflow 从 Provider 转向 Task Domain

目标 workflow 不再按 provider 命名，而按任务领域命名：

| 当前 provider workflow | 目标 task-domain workflow | 说明 |
| --- | --- | --- |
| `github_repository_qa` | `external_codebase_qa` | 面向远程代码库问答，可解析 GitHub、GitLab、Bitbucket 等 MCP 能力 |
| `notion_workspace_qa` | `external_workspace_qa` | 面向外部知识空间问答，可解析 Notion、Confluence、Google Drive 等能力 |
| future `jira_issue_qa` | `external_project_ops` | 面向项目管理对象，可解析 Jira、Linear、GitHub Issues 等能力 |
| future `slack_search_qa` | `external_conversation_qa` | 面向外部会话记录，可解析 Slack、Teams、飞书等能力 |

workflow 仍然是确定性边界，但它描述的是“这类任务允许怎样执行”，而不是“这次只能用某个 provider”：

```text
external_workspace_qa
  -> resolve_capabilities(domain=workspace_knowledge, operations=(search, read))
  -> react_with_scoped_tools
  -> compose_answer_with_sources
```

如果用户问“结合 GitHub issue 和 Notion 方案页总结当前项目风险”，目标链路应该能够解析出 GitHub issue read/search 与 Notion page search/read，并在同一个受治理 ReAct step 中组合使用，而不是提前选择其中一个 provider workflow。

第一层 task-domain workflow 不应长期变成新的大筐。后续应继续按任务策略细分：

| Workflow | 执行策略 |
| --- | --- |
| `external_codebase_qa` | search / read -> answer with citation |
| `external_codebase_analysis` | search / read multiple sources -> evidence grouping -> conclusion |
| `external_workspace_qa` | workspace search / read -> answer with citation |
| `external_workspace_compare` | source A + source B -> normalize -> diff -> conclusion |
| `external_project_risk_analysis` | issues / docs / conversations -> cluster -> severity -> mitigation |
| `external_conversation_qa` | conversation search / read -> answer with source boundaries |
| `external_release_context_analysis` | release notes / issues / docs -> timeline -> impact summary |

## Agentic 不等于无边界

MCP Capability Fabric 的目标是提升工具选择的灵活性，但边界仍然由工程系统控制：

- WorkflowScope 限制任务类型；
- CapabilityResolver 只返回当前 workflow 允许的能力；
- PolicyEngine 根据风险、授权、side effects 做 allow / deny / confirm；
- ToolGateway 对每次具体调用做 schema、timeout、retry、audit；
- 高风险写操作不能只靠 ReAct 自由决定，必须有显式 step 和确认；
- e2e_quality 验证完整入口链路是否选中了正确 capability；
- tool_quality 验证 capability metadata 和 ToolGateway 治理契约。

换句话说，Agentic 的部分是“在任务边界内选择和组合能力”；非 Agentic 的部分是“权限、风险、执行、审计和副作用控制”。

## 当前评估是否合理

结论：Phase 0 评估作为接入验收是合理的，但不能作为目标架构验收；当前 GitHub / Notion MCP e2e 已迁移到 task-domain + CapabilityResolver 验收口径。

当前 `tool_quality` 与 `e2e_quality` 覆盖了两类真实问题：

| 评估层 | 当前验证内容 | 合理性 |
| --- | --- | --- |
| `tool_quality` | GitHub / Notion / GPT Researcher 工具的 exposure、risk、side effects、permission scope、timeout、retry、rate limit、audit | 合理。它验证工具治理 metadata 是否能被 ToolGateway 正确理解 |
| `e2e_quality.github_mcp` | `execute_entry -> router -> external_codebase_qa -> capability_resolution -> ReAct -> ToolGateway -> audit trace`，并断言 `mcp:github:*` capability 与 `github.*` 工具实际进入链路 | 合理。它证明 GitHub MCP 接入不是只注册了工具名，而是走了任务域 workflow、Resolver、ToolGateway 完整链路 |
| `e2e_quality.notion_mcp` | `execute_entry -> router -> external_workspace_qa -> capability_resolution -> ReAct -> ToolGateway -> audit trace`，并验证只读 Notion 工具调用与写请求边界 | 合理。它证明 Notion MCP 读能力在 task-domain workflow 中可用，且写请求不会误走只读 workflow |
| `e2e_quality.gpt_researcher_a2a` | `execute_entry -> router -> gpt_researcher_a2a -> agent_call(gpt_researcher) -> AgentGateway -> AgentRun / AgentArtifact` | 合理。它证明当前 A2A 作为外部 Agent 的主链路可执行 |

这些 case 的价值是“接入完整链路验证”，不是“Agentic 能力选择验证”。它们仍有明确边界：

- MCP case 使用 fake MCP tool，不验证真实 MCP server discovery、transport、鉴权或远端 schema 漂移；
- MCP case 中 ReAct 选择被 deterministic mock 固定，主要验证 capability-derived allowlist、workflow、ToolGateway 和 audit，不评估 LLM 是否能自主选对工具；
- case 断言 `expected_workflow_id` 是 `external_codebase_qa` / `external_workspace_qa`，provider 只出现在 capability resolution 中；
- case 断言 `expected_tool_names` 与 `expected_capability_ids`，并要求至少一次 `capability_resolution` 事件；
- 跨 provider 组合问题已进入 `resolver_quality`，完整 e2e 可在后续需要真实跨工具回答时补充；
- A2A case 已以 AgentRun / AgentEvent / AgentArtifact 为成功信号；
- 负向 case 已覆盖“本地记忆问题不应误走 GitHub”“Notion 写请求不应误走只读工具”；`resolver_quality` 已覆盖 local-first 与 read-only policy clamp，权限拒绝、候选冲突和降级策略可继续扩展。

因此，当前评估应被明确标记为 transitional full-chain plumbing gate。它们可以保留为迁移前后的回归保护，但不能继续指导未来 MCP / A2A 新能力的验收口径。

## 目标评估分层

目标架构需要把外部能力评估拆成四层，避免一个 e2e case 同时背负注册、选择、执行、治理、答案质量和生命周期判断：

| 目标评估 | 评测单元 | 主要问题 | 不负责什么 |
| --- | --- | --- | --- |
| `capability_quality` | 单个 MCP capability / Agent definition | capability metadata 是否准确：domain、resource type、operation、risk、side effects、auth scope、schema、trust、credential、data egress | 不判断某次用户问题是否应该选择它 |
| `resolver_quality` | `UserTask + WorkflowScope + CapabilityRegistry -> CapabilityResolution` | CapabilityResolver 是否选对、拒绝对、解释清楚，是否遵守 deterministic filter + semantic rank + policy clamp | 不执行工具，不评估最终答案 |
| `workflow_e2e_quality` | 一次 `execute_entry` 完整运行 | Router 是否进入 task-domain workflow，workflow 是否产生 capability resolution，ReAct 是否在 scoped allowlist 内实际调用 ToolGateway，答案是否引用可审计 artifact | 不检查每个 capability 的静态 metadata 全量正确性 |
| `agent_gateway_quality` | 一次 external Agent 委托 | AgentDefinition、AgentGovernance、AgentRun、AgentEvent、AgentArtifact、policy decision、cancel/timeout 是否完整 | 不把外部 Agent 当普通 tool audit 验收 |

对于 MCP，新的主路径应该是：

```text
capability_quality
  -> resolver_quality
  -> workflow_e2e_quality
  -> AgentRun audit / artifact / answer grounding
```

对于 A2A，新的主路径应该是：

```text
agent_gateway_quality
  -> workflow_e2e_quality
  -> AgentRun audit / artifact / answer grounding
```

真实 MCP server / A2A backend 的连通性可以有 live smoke test，但它不应替代 golden set。live smoke test 只回答“今天环境和远端可达吗”；golden set 回答“系统在稳定输入和明确期望下是否保持能力边界”。

## Resolver Golden Set

CapabilityResolver 必须单独建金标，否则它会变成第二个 Router，问题很难定位。建议 case 形状如下：

```json
{
  "id": "resolver-mcp-001",
  "user_task": "结合 GitHub issue 和 Notion 方案页总结 Orion 项目风险",
  "workflow_scope": "external_project_ops",
  "available_capabilities": [
    "github.search_issues",
    "github.get_issue",
    "notion.search",
    "notion.retrieve_page_markdown",
    "github.create_issue"
  ],
  "expected_selected_capabilities": [
    "github.search_issues",
    "notion.search",
    "notion.retrieve_page_markdown"
  ],
  "expected_denied_capabilities": [
    {
      "capability": "github.create_issue",
      "reason": "write_not_allowed_in_readonly_analysis"
    }
  ],
  "forbidden_selected_capabilities": [
    "github.create_issue"
  ],
  "expected_operations": ["search", "read"],
  "expected_resource_types": ["issue", "page"],
  "min_confidence": 0.7
}
```

关键指标：

- `selected_capability_recall`：应该选的能力是否被选中；
- `selected_capability_precision`：是否过度选择无关能力；
- `denied_capability_accuracy`：应拒绝能力是否被拒绝，并记录原因；
- `operation_scope_exact`：search/read/write/delete 是否符合 workflow scope；
- `risk_clamp_accuracy`：中高风险或写操作是否被 policy clamp；
- `provider_composition_accuracy`：跨 provider 任务是否能同时选出多个 provider；
- `local_first_accuracy`：本地知识问题是否避免误选外部 MCP；
- `rationale_contains_policy_reason`：拒绝和降级是否有可审计解释。

CapabilityResolver 的实现和评估都不应是纯 LLM。目标顺序是：

```text
deterministic filter
  -> semantic rank
  -> policy clamp
  -> auditable CapabilityResolution
```

LLM 或 embedding 只在候选集内排序和解释，不负责突破 workflow scope、授权、风险和 side effect 约束。

## E2E Golden Set 迁移口径

现有 MCP e2e case 可以保留为 Phase 0 回归样本，但迁移到 task-domain workflow 后，断言口径需要改变：

| 当前断言 | 目标断言 |
| --- | --- |
| `workflow_id == github_repository_qa` | `workflow_id == external_codebase_qa`，provider 只出现在 capability resolution 中 |
| `workflow_id == notion_workspace_qa` | `workflow_id == external_workspace_qa` |
| `expected_tool_names == ("github.search_code",)` | `expected_selected_capabilities` 包含 code search capability，且 ToolGateway audit 中出现被解析后的 local tool |
| `forbidden_tool_names == ("graph_search",)` | 同时断言 `forbidden_selected_capabilities` / `denied_capabilities`，区分“未选择”和“被 policy 拒绝” |
| fake ReAct 固定工具选择 | 只 mock 非评估焦点；当评估 resolver 时固定模型，当评估 ReAct 工具选择时固定 capability resolution |
| A2A tool audit 作为成功 | AgentRun / AgentEvent / AgentArtifact 作为成功，tool audit 只用于底层兼容期 |

新增 e2e 必须覆盖：

- 单 provider 只读：远程代码库问答、外部知识库问答；
- 跨 provider 只读：GitHub issue + Notion 方案页联合总结；
- provider 冲突：用户未指定 provider 时按 selection policy 选择，且记录未选原因；
- local-first：本地知识问题不应因为存在 GitHub/Notion MCP 就访问外部；
- 写操作拒绝：只读 workflow 中出现 create/update/delete 能力时必须拒绝；
- 风险升级：跨 provider 或敏感数据外发时触发确认或降级；
- A2A lifecycle：外部 Agent 委托必须产生 AgentRun，而不是只留下 ToolInvocation。

最新评估结论是合理的：当前四层评估已经比 provider workflow 断言成熟，但仍需在落地顺序上提前 AgentGateway minimal，并把 selection policy、trust / credential / data egress、AgentArtifact verification 纳入可测试契约。

## Workflow 接入方式

迁移前 `gpt_researcher_a2a` workflow：

```text
gptr-a2a-research tool_call(gpt_researcher.a2a_research)
```

目标形态：

```text
gptr-a2a-research agent_call(gpt_researcher)
```

对应 `WorkflowStepSpec` 可以新增：

```python
WorkflowStepSpec(
    step_id="gptr-a2a-research",
    action_type="agent_call",
    agent_id="gpt_researcher",
    side_effects=("external_network",),
    risk_level="medium",
)
```

`StepProjectionValidator` 需要新增 agent capability 校验：

- `agent_id` 是否注册；
- workflow 声明的 side effects 是否覆盖 agent governance；
- confirmation / HITL 是否与 risk 对齐；
- timeout / async / streaming 是否被当前执行器支持；
- agent output mode 是否可被下游 compose 消费。

## 存储与审计

AgentGateway 需要独立存储：

```text
agent_definitions
agent_runs
agent_events
agent_artifacts
agent_policy_decisions
```

`tool_audit_events` 不应承载完整 AgentRun，因为两者生命周期不同：

- ToolInvocation 通常是短调用，一次输入一次输出。
- AgentRun 可能长时间运行，有状态变化、stream delta、多个 artifact、cancel/resume。

但审计查询 API 可以聚合展示：

```text
workflow run
  -> step events
  -> tool invocations
  -> agent runs
  -> model calls
  -> human gates
```

## Policy 设计

Agent policy 应复用现有 PolicyEngine 的核心规则，但输入对象不同：

```python
PolicyInput(
    action="agent_call",
    agent_id="gpt_researcher",
    risk_level="medium",
    side_effects=("external_network",),
    permission_scope="a2a:gpt_researcher:research",
    execution_mode="workflow_activity",
)
```

新增策略维度：

- agent allow / deny list；
- protocol allow / deny list；
- trust level / attestation status；
- credential mode / delegated token boundary；
- data egress class；
- max concurrent runs per user；
- max running time；
- max estimated cost；
- allowed output modes；
- whether remote agent may persist memory；
- whether remote agent may call external web。

## 分阶段路线

### Phase 0：当前已完成（已落地）

- GPT Researcher A2A 已通过 `gpt_researcher` Agent adapter 接入。
- `gpt_researcher_a2a` workflow 走 `execute_entry -> router -> workflow -> AgentGateway -> AgentRun / AgentArtifact`。
- GitHub MCP / Notion MCP provider workflow 保留为过渡期 plumbing baseline。
- e2e_quality 验证 GitHub MCP、Notion MCP、GPT Researcher A2A 的完整入口链路。
- tool_quality 验证治理 metadata。

### Phase 1：MCP Capability Registry（已落地）

- 保留当前 GitHub / Notion provider workflow 作为基线验证样本。
- 新增 `MCPCapability` 契约和 `MCPCapabilityRegistry`，从 MCP server discovery / tool listing 生成 capability metadata。
- 将 `github.search_code`、`github.get_file_contents`、`github.search_repositories`、`notion.search`、`notion.retrieve_page_markdown` 注册为 capability，而不是只作为静态 tool name。
- `build_mcp_tool()` 会把标准化 capability 写入 tool 的 `extras["mcp_capability"]`。
- GitHub / Notion preset 声明 `semantic_domains`、`resource_types`、`operations`、`trust_level`、`credential_mode`、`data_egress_class`、`attestation_status`、`freshness_profile`。
- tool_quality 从“某个工具可被调用”升级为“capability metadata、risk、side effects、schema、auth scope、trust、credential、data egress、attestation 正确”。

### Phase 1.5：AgentGateway 最小抽象（已落地）

- 已新增 `AgentDefinition / AgentGovernance / AgentTask / AgentRun / AgentEvent / AgentArtifact / AgentRunResult`。
- 已新增 `AgentGateway.invoke()` blocking API，并通过 `PolicyEngine(action="agent_call")` 治理外部 Agent 委托。
- GPT Researcher A2A 已从 runtime tool wrapper 迁移到 `GPTResearcherA2AAdapter`。
- workflow 已新增 `agent_call` action type，`gpt_researcher_a2a` 使用 `agent_call(gpt_researcher)`。
- e2e_quality 已改为验证 `AgentRun` / `AgentArtifact(unverified)`，不再用 `tool_audit_events` 作为 A2A 成功信号。

### Phase 2：CapabilityResolver 与 Resolver Golden Set（已落地）

- 已新增 `CapabilityResolver` 与 `CapabilitySelectionPolicy`。
- 已落地 `deterministic filter -> semantic rank -> policy clamp -> auditable CapabilityResolution`。
- `CapabilityResolution` 输出 `selected_capabilities`、`allowed_tools`、`denied_capabilities`、`rationale`、`confidence`。
- 已新增 `evals/resolver_quality`，覆盖 GitHub code search / file read / repository discovery、Notion search / page read、local-first 拒绝、read-only 写请求拒绝、GitHub + Notion 跨 provider composition。
- ReAct 入口会写 `capability_resolution` 事件，e2e 可审计 resolver 是否真实参与完整链路。

### Phase 3：Task-domain Workflow（已落地）

- 已新增 `external_codebase_qa`、`external_workspace_qa`、`external_project_ops` task-domain workflow。
- Router 对 GitHub 仓库/代码问题返回 `external_codebase_qa`，对 Notion 页面/工作区问题返回 `external_workspace_qa`；provider 不再作为 workflow identity。
- task-domain ReAct step 不声明 provider-specific `allowed_tools`，而是在执行前由 `CapabilityResolver` 从 MCP capability registry 解析 scoped allowlist。
- e2e_quality 的 GitHub / Notion MCP 分支已迁移为 `execute_entry -> router -> external_* workflow -> capability_resolution -> ReAct -> ToolGateway -> audit trace`。
- e2e 同时断言 `expected_capability_ids` 和实际 `expected_tool_names`，避免只验证工具名而绕过 resolver。

### Phase 4：收敛 provider-specific workflow（已完成 MCP 主路径收敛）

- `github_repository_qa`、`notion_workspace_qa` 已从运行时主路径移除。
- Router 不再返回 provider workflow，而返回 task intent / domain / constraints。
- provider 选择仅作为 CapabilityResolver 的输出，不作为 workflow identity。

### Phase 5：异步任务和取消（已落地 Gateway API）

- `AgentGateway` 已支持 `submit / poll / cancel`。
- `GPTResearcherA2AClient` 已支持 A2A `message/send blocking=false`、`tasks/get`、`tasks/cancel` 映射。
- `agent_gateway_quality` 已覆盖 submit/poll/cancel。
- Workflow 当前主路径仍使用 blocking `invoke()`，异步 AgentRun 可通过 Gateway API 管理；后续如需“工作流暂停等待外部 Agent 完成”，可在现有 `agent_call` step 上增加 waiting state。

### Phase 6：Streaming 与前端事件（已落地 Gateway event 映射）

- `AgentGateway.stream()` 已支持 AgentEvent iterator。
- `GPTResearcherA2AAdapter.stream()` 将 A2A stream/task output 映射为 `AgentEvent(type="stream_delta")`。
- `agent_call` step 会把 stream delta 写成 orchestration `agent_run_event`，现有 entry SSE 可直接转发。
- `agent_gateway_quality` 已覆盖 stream event。

### Phase 7：多 Agent 注册与选择（已落地 Registry 基线）

- `AgentGateway` 支持多个 Agent adapter 注册与 definition 查询。
- Router 仍只选择 intent；当前 `gpt_researcher_a2a` workflow 通过 `agent_id="gpt_researcher"` 显式引用 Agent。
- `agent_gateway_quality` 覆盖多 Agent 注册、指定 Agent 调用和禁止误选其他 Agent。
- 后续如出现同一 task-domain 多 Agent 竞争，再引入独立 `AgentSelectionPolicy`；当前没有让 LLM 自由挑选 Agent。

## 不做什么

- 不把 MCP 迁到 AgentGateway；MCP 仍是 ToolGateway 的协议来源。
- 不再为每个 MCP provider 长期维护一个独立 workflow；provider-specific workflow 只能作为过渡期验证基线。
- 不让 LLM 直接自由选择任意外部 Agent；必须经过 workflow / allowlist / policy。
- 不让 LLM 直接自由选择任意 MCP tool；必须经过 CapabilityResolver / ToolGateway / policy。
- 不把 AgentGateway 做成绕过 ToolGateway 的 HTTP 客户端集合。
- 不让 AgentGateway 通过 ToolGateway 执行 A2A 调用；二者共享治理基础设施，但执行抽象分离。
- 不让外部 Agent 自动写入长期知识；写入仍必须走本工程 capture / workspace lifecycle。
- 不把外部 Agent 返回的 report / artifact 直接当作 verified evidence。

## 判断标准

引入 AgentGateway 后，一个外部 Agent 接入应同时满足：

1. 有 `AgentDefinition` 和治理 metadata。
2. 有 workflow intent 或 workflow step 显式引用。
3. 有 PolicyEngine 决策记录。
4. 有 durable AgentRun / AgentEvent / AgentArtifact。
5. AgentArtifact 默认 `unverified`，并进入 EvidenceNormalizer / ClaimVerifier / CitationChecker。
6. 可取消、可超时、可限流。
7. e2e_quality 能证明用户请求会走完整入口链路并产生 AgentRun。
8. tool_quality 不再替 AgentRun 背书；改由 agent_quality 或 workflow_quality 验证。

一句话目标：**ToolGateway 治理工具，AgentGateway 治理外部 Agent；WorkflowSpec 决定什么时候调用谁，PolicyEngine 决定是否允许，event/audit 证明实际发生了什么。**

对于 MCP 的一句话目标：**MCP server 只负责提供能力，CapabilityResolver 决定本次任务可用哪些能力，ToolGateway 证明每一次具体工具调用被治理。**

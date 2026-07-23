# Knowledge Agent Capability-first 目标设计

## 文档定位

本文是知识 Agent 产品能力、MCP/A2A 扩展边界、Agent 主循环和运行时治理的目标设计 owner。它描述破坏性目标态，不代表当前代码已经具备全部能力。当前实现事实和已通过的 release 证据仍以
[当前核心架构](../summary/core-architecture-current-state.md)、
[Phase 0 能力目录与发布基线](../summary/phase0-capability-release-baseline.md)、
[当前 E2E 审计](../summary/core-architecture-e2e-audit.md) 和
[正式环境核心用户结果 E2E](../evals/e2e-quality-cases.md) 为准。

本文不再从 Runtime Model、Result Contract 或 E2E 编号开始设计。顺序固定为：

```text
知识 Agent 的产品责任
  -> 原生能力范围
  -> MCP / A2A 可扩展能力范围
  -> 当前部署实际可用的能力集合
  -> 模型如何在能力集合内行动
  -> Runtime 能机械管控的边界
  -> 用户旅程和 Release E2E
  -> 为这些结果必需的最小协议与持久化
```

能力尚未定义、Provider 尚不存在或用户结果尚未闭合时，不得先创建 Proposal、Contract、Command、Event、Projection 或 E2E 来证明框架对象存在。

目标态不考虑旧调用方兼容性。每个事实只有一个 owner 和一个写入口；派生的有效能力集合、候选排名和上下文物化默认不持久化。

## 1. 从成熟 Agent 设计吸收什么

### 1.1 共同结构

当前成熟 Agent SDK 和协议的共同结构不是“先分类最优路径”，而是：

```text
Model
  + instructions
  + current context
  + currently available tools / agents
  -> FinalMessage | ToolCall | AgentDelegation

Runtime
  -> permission / scope / approval / execution / recovery
  -> ToolResult | Agent status / Artifact
  -> return to Model
```

模型负责开放世界中的语义判断，包括是否直接回答、调用哪个语义不同的 Tool、是否委托远程 Agent、如何根据 Observation 调整下一步。Runtime 不承诺模型选择“最优路径”，只承诺被执行的动作存在、获准、参数未被静默改写，且执行事实可恢复和审计。

### 1.2 参考与采纳边界

| 参考 | 采纳 | 不采纳 |
| --- | --- | --- |
| [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) | Agent 由 instructions、tools、handoffs/agent-as-tool、guardrails、sessions 和 tracing 组成 | 不为普通回答强制创建 Task、GoalGraph 或结果合同 |
| [OpenAI Agent Orchestration](https://openai.github.io/openai-agents-python/multi_agent/) | 开放语义由模型编排，稳定顺序、并行、预算和验收循环可由代码控制；manager 保持最终答复 owner，handoff 只在 specialist 应接管交互时使用 | 不让确定性代码决定语义路径，也不让 specialist completion 自动成为父结果 |
| [OpenAI Deep Research](https://openai.com/index/introducing-deep-research/) | 通过多轮搜索、浏览、分析、修正方向、综合和引用组合研究能力 | 不把一次搜索 Receipt 或单一 Research ToolResult 冒充完整研究结果 |
| [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview) | 模型循环、明确工具集合、权限、Hooks、Session、MCP 和隔离 Subagent | 不用确定性分类器替模型选择直接回答或工具 |
| [Claude Agent Loop](https://platform.claude.com/docs/en/agent-sdk/agent-loop) | 模型产生文本或 ToolCall，应用执行后把 ToolResult 返回模型，直到无 ToolCall | 不把模型 ToolCall 当权限或完成证明 |
| [Claude Subagents](https://platform.claude.com/docs/en/agent-sdk/subagents) | 用独立上下文、受限工具和专门 instructions 处理聚焦子任务 | 不因并行或上下文隔离自动创建业务 Task |
| [Anthropic Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) | 从 retrieval、tools、memory 增强的 LLM 出发，按需要组合 chaining、parallel、orchestrator-workers 和 evaluator-optimizer | 不把所有模式固化成一张通用业务 Workflow，也不在简单请求上强加 Agent 复杂度 |
| [Codex Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md) | 让窄职责 Agent 并行探索、测试或审查，向主 Agent 返回摘要并由主 Agent 汇总 | 不共享可写业务状态，不把并行本身当成质量或完成证明 |
| [Codex Execution Plans](https://developers.openai.com/cookbook/articles/codex_exec_plans) | 复杂工作先形成简明可检查的工作计划，执行中根据发现更新，并以验证结果收尾 | 不把工作计划升级为权限、不可变业务定义或 Completion 事实 |
| [MCP Architecture](https://modelcontextprotocol.io/specification/2025-06-18/architecture) | Server 暴露聚焦 resources/tools/prompts；Host 管理上下文、授权、安全隔离和能力协商 | 不信任远端自述的语义、风险或可信度，也不允许 Server 看到完整会话 |
| [A2A Core Concepts](https://a2a-protocol.org/latest/topics/key-concepts/) | Agent Card 声明 skills；简单交互返回 Message；长时工作使用 Task、status 和 Artifact | 不把远程 Agent 内部 Plan/Tool 暴露为本地事实，不把远程成功自动当父目标成功 |
| [LangGraph Overview](https://docs.langchain.com/oss/python/langgraph/overview) | durable execution、streaming、HITL、memory 和长时状态恢复 | 不让编排 Runtime 定义知识 Agent 的业务能力 |

这些参考只提供设计原则。是否属于本产品能力，仍由下文的知识 Agent 产品责任决定。

## 2. 必须区分的四种“能力”

### 2.1 产品能力

产品能力是用户能够稳定依赖的结果，由知识 Agent 自己负责端到端闭合。它不能因为某个可选 MCP Server 暂时离线就从产品定义中消失。

例如：

- 保存用户提供的资料；
- 在用户个人知识范围内检索；
- 根据指定资料回答并给出可解析引用；
- 管理知识的更新、删除、恢复和演进；
- 生成复习、知识缺口和研究简报。

产品能力可以使用不同 Provider 实现，但产品语义、资源身份、长期状态和用户结果由本应用拥有。

### 2.2 Tool / Connector 能力

Tool 能力是一个有界操作：给定 typed input，执行一次 read/list/search/create/update/delete 等动作，返回 ToolResult 或 typed failure。

Tool 可以来自：

- 本地 Tool；
- MCP Server；
- 受控 HTTP/API adapter；
- Retriever。

Tool 扩展的是“能读取什么、能操作什么”，不是新的自治 Agent。天气、GitHub、Notion、日历、邮件、数据库和浏览器都优先属于这一层。

### 2.3 Agent Delegation 能力

Agent Delegation 是把一个开放式子目标委托给具有独立循环、工具、上下文和任务生命周期的远程或本地 Agent。

适合委托的能力包括：

- 深度网页研究；
- 代码库调查；
- 合同审查；
- 安全审计；
- 数据分析；
- 其他需要多轮自主行动并产生 Artifact 的专业任务。

只有真实注册并可发现的 Agent Card/Profile 才构成可用委托能力。模型描述“我可以做安全审计”不构成能力；没有安全审计 Agent 时，系统不得创建安全审计成功用例。

### 2.4 Runtime 性质

以下是执行性质，不是业务能力：

- checkpoint；
- interrupt/resume；
- approval；
- immutable command；
- idempotency；
- Journal/reconciliation；
- tracing；
- context isolation；
- streaming；
- durable queue；
- Task status。

这些性质保障某项产品能力或扩展能力可靠执行，但不能独立证明用户获得了有价值的结果。

## 3. 知识 Agent 的原生产品能力

### 3.1 原生能力目录

| 能力 | 用户结果 | Canonical owner |
| --- | --- | --- |
| Conversation | 直接回答、澄清和连续对话 | Session / InteractionRun |
| Capture | 文本、网页、文件和明确会话结论进入个人知识 | Workspace/Knowledge aggregate |
| Grounded Ask | 基于个人知识或明确选择的资料回答并返回引用 | ResourceStore + Evidence store |
| Knowledge Lifecycle | 更新、supersede、冲突标记、删除和恢复 | Knowledge aggregate |
| Review | 生成复习内容并接收反馈 | Review aggregate |
| Knowledge Maintenance | 整理同主题知识、发现孤岛、薄弱连接和潜在冲突 | Knowledge aggregate |
| Research | 围绕主题检索外部资料、生成带来源的研究简报 | ResearchRun aggregate |
| Scheduled Intelligence | 周期运行研究、投递简报和接收偏好反馈 | ResearchSubscription / ResearchRun / Delivery |

本表只定义目标产品责任。最低 E 系列映射及其唯一机器写入口已经收敛到
`evals/e2e_quality/release_gate.py`；当前状态只在
[Phase 0 能力目录与发布基线](../summary/phase0-capability-release-baseline.md) 中报告。

### 3.2 原生不等于全部本地实现

Research 是产品能力，但搜索 Provider 可以是本地 `web_search`、MCP 搜索工具或 A2A Research Agent。产品必须统一资源身份、来源、运行状态和最终简报；Provider 只负责其声明的子能力。

Grounded Ask 是产品能力，但来源可以来自 Workspace、用户选择的 Artifact、Notion MCP 或企业知识库。产品必须保证 scope、citation identity 和 Ask 不隐式写入；外部 Connector 不拥有这些产品规则。

### 3.3 明确不属于基础能力

以下专业能力不是知识 Agent 基础能力，除非产品以后明确承诺并接入对应 Provider：

- 天气实况；
- 合同法律审查；
- 安全审计；
- 医疗诊断；
- 财务投资判断；
- 任意代码库修改。

模型可以讨论一般知识，但不能把一般语言能力包装成已执行的专业 Tool/Agent 结果。

### 3.4 基础能力组合成强能力

成熟 Agent 的强能力不是来自一个预定义的巨大 Workflow，而是来自少量能力在
`Model -> Proposal -> Admission/Execution -> Observation -> Model` 循环中的动态组合。
本产品的原生能力可以形成以下目标产品结果：

| 强能力发布声明 | 基础能力组合 | 持久事实 owner |
| --- | --- | --- |
| Personal Research Analyst | Conversation + Grounded Ask + Research + Capture + Knowledge Lifecycle | InteractionRun、ResearchRun、Workspace/Knowledge |
| Continuous Knowledge Steward | Scheduled Intelligence + Research + Grounded Ask + Knowledge Maintenance + Knowledge Lifecycle | ResearchSubscription、ResearchRun、Knowledge、Delivery |
| Personalized Learning Agent | Grounded Ask + Review + Research + Capture | Review、ResearchRun、Workspace/Knowledge |
| Expert Collaboration Agent | Conversation + A2A + Grounded Ask + Research synthesis | InteractionRun、ChildAgentRun、Artifact、ResearchRun |

“强能力”是产品发布声明和用户旅程，不是新的 Aggregate。表中各事实继续由自己的领域
owner 写入，不新增 `CompositeTask`、`CompositeCapabilityState`、统一 Plan 或把各领域
结果复制到父状态。普通同步组合只存在于一个 `InteractionRun` 的临时模型循环中；跨
审批、恢复或长时执行边界时，只持久化相应领域 Command/Aggregate/ref。

模型拥有每个语义分叉，例如是否需要外部研究、哪些资料相关、是否委托专业 Agent、如何
综合证据以及是否建议保存。确定性 Runtime 只能根据 accepted fields、policy 和已提交
事实完成 capability availability、scope、approval、dispatch、replay 和唯一状态转换，
不得把“证据不足”机械编译成 Research，不得把 Research 结果自动 Capture，也不得把
Review feedback 自动扩写成新的研究目标。

基础能力和 C01–C04 的机器映射由 release gate 独占；基础证据不能替代组合证据。

## 4. MCP 能力扩展

### 4.1 MCP 的职责

MCP Server 可以声明 resources、tools 和 prompts。Host 必须独占：

- Server 安装和启用；
- capability negotiation；
- credential 和用户授权；
- Tool allowlist；
- Resource scope；
- 数据出域策略；
- 高风险动作审批；
- ToolResult 标准化；
- 远端 annotation 的信任降级。

### 4.2 MCP 能力的权威来源

| 事实 | owner |
| --- | --- |
| 远端 Tool 名称和远端 input schema | MCP Server discovery response |
| 本地暴露名称 | Host approved mapping |
| permission、risk、side effect、data egress | Host policy |
| credential 是否可用 | Credential/connection runtime |
| 本次会话是否允许调用 | Host admission |
| Tool 实际返回 | MCP invocation result |

不得把远端 Tool annotation 直接复制为可信的风险、freshness、evidence 或业务完成声明。

### 4.3 不做语义伪等价

`semantic_domains`、description、examples 和 model-generated requirement 只能帮助发现候选，不能机械证明两个 Provider 可替换。

例如 `web_search` 与天气 Provider 都可能具有 `read + web + fresh` 标签，但它们不能因此被确定性代码判定为等价。前者返回网页摘要，后者可能返回带观测时间和站点的结构化气象数据。

只有 Host 明确配置了同一个版本化 binding group，且 input/output、authority、scope、side effect、failure 和 evidence contract 完全一致时，Runtime 才能在组内按 availability、固定 priority 或成本选择 Provider。否则由模型在候选描述中做语义选择。

### 4.4 MCP 缺失时

当模型需要当前不可用的 Connector 时，允许：

- 直接说明能力不可用；
- 请求用户启用/授权已知 Connector；
- 返回 typed capability acquisition pending interaction；
- 在用户允许的情况下选择语义不同但可接受的替代方案。

Runtime 不得自动生成替代查询、替代写入或业务答案。

## 5. A2A 与 Subagent 扩展

### 5.1 A2A 的职责

A2A Agent 通过 Agent Card/Profile 声明 identity、skills、endpoint、auth 和交互能力。Host 可以据此向模型暴露可委托 Agent，但 Agent Card 是远端自述，不是成功证明。

本地只接受三类远端事实：

- Task identity/status；
- Message；
- Artifact。

远端 Plan、内部 ToolCall、memory 和自我验证不是本地 canonical state。

### 5.2 何时用 Tool，何时用 Agent

| 问题 | Tool / MCP | A2A / Subagent |
| --- | --- | --- |
| 输入输出是否一次调用可界定 | 是 | 通常否 |
| 是否需要独立多轮循环 | 否 | 是 |
| 是否需要独立上下文 | 通常否 | 是 |
| 是否产生长时 Task/Artifact | 可选 | 常见 |
| 调用方是否需要理解内部步骤 | 不需要 | 不需要，远端是黑盒 |
| 示例 | 查天气、搜 GitHub、读 Notion 页面 | 深度研究、代码调查、合同审查 |

不得为了统一接口把长时 A2A Task 压扁成阻塞 ToolCall；也不得把普通一次查询包装成远程 Task。

### 5.3 父 Agent 的责任

父 Agent 必须：

- 决定是否委托和委托什么 bounded sub-goal；
- 只下放必要 Context；
- 限制远程 Agent 可用权限和数据出域；
- 跟踪 submit/poll/stream/cancel；
- 接收 Artifact 但不自动相信其语义；
- 根据用户问题和其他证据决定如何使用 Artifact；
- 不把远程 Task completed 自动映射为父任务 completed。

## 6. 有效能力、分层规划与 Agent 主循环

### 6.1 有效能力集合

每个 InteractionRun 在当前 revision 临时物化有效能力集合：

```text
EffectiveCapabilities
  = enabled native tools
  + connected and approved MCP tools
  + registered and available Agent profiles
  - policy denied capabilities
  - unavailable credentials/providers
  - capabilities outside current resource/user scope
```

它是从 canonical definition、connection state、policy 和 authority 确定性计算的 Runtime Projection，不是新的数据库 Model，也不进入 checkpoint 成为第二写入口。Checkpoint 只保存重建所需 revision/ref。

### 6.2 分层规划，不删除模型规划能力

复杂任务需要规划，但不同层次的“计划”不能混成一个可写业务 Model：

| 层次 | owner / 唯一写入口 | 生命周期 | 权威边界 |
| --- | --- | --- | --- |
| 模型内部推理 | Model provider | 单次模型调用 | 不请求、不持久化、不作为审计或执行依据 |
| `WorkingPlanSnapshot` | Model adapter 接收的模型输出 | 当前 InteractionRun 的临时 Context；可进入 append-only LLM trace | 非权威、可完全修订，不授予权限、不证明完成 |
| `ToolCallProposal` / `AgentDelegationProposal` | Model adapter | 当前 turn 的候选动作 | Admission 只能接受或拒绝 |
| ResearchRunDefinition 等领域 Definition | 相应领域 command intake | 领域 Aggregate 生命周期 | 只包含用户明确输入、澄清回答或版本化 ProductMode |
| Procedure route | 版本化 policy / Procedure registry | 某个已接受 Command 的执行期 | 只实现稳定事务不变量，不新增业务 intent |

`WorkingPlanSnapshot` 是简明、可展示的工作计划，不是 chain-of-thought。它只允许引用当前
用户输入或已接受领域 Definition，列出具有 provenance 的约束、剩余工作和开放问题，
以及本次修订原因，例如 `initial`、`observation`、`decision_feedback`、`user_input` 或
`context_rebuild`。它不得携带可执行 payload、authority、approval、Command digest 或
“步骤已完成”事实；完成过什么只能从 ToolResult、Receipt、Artifact 和领域状态读取。

简单问题可以不产生 `WorkingPlanSnapshot`。是否需要工作计划、如何分解以及何时修订由
模型根据开放语义决定，Runtime 不重新引入 `complexity` 分类器。用户可以明确要求先展示
计划；模型也可以在复杂任务中主动给出计划。计划变化可以按 model/turn/input/output
digest 进入 trace 供调试和 E2E 检查，但不进入业务数据库或 checkpoint 成为恢复 owner。

### 6.3 AgentTurnDecision 与 ReAct 主循环

模型每一轮只返回一个临时 envelope：

```text
AgentTurnDecision
  = FinalMessage
  | ContinueTurnProposal {
      working_plan?: WorkingPlanSnapshot
      actions: non-empty tuple[
        ToolCallProposal | AgentDelegationProposal
      ]
    }
```

`actions` 是唯一可写动作集合，不同时保留 `action`/`actions`。`WorkingPlanSnapshot` 只
解释当前方向；真正可执行的 target、payload 和 bounded sub-goal 必须且只能出现在对应
Action Proposal 中。只更新计划但没有动作的 `ContinueTurnProposal` 无法推进执行，应被
schema 拒绝；需要用户输入时返回澄清 `FinalMessage`。

如果用户明确要求“只给计划、不要执行”或“等我确认再开始”，模型使用 `FinalMessage`
返回简明 plan preview，且本次 turn 没有 actions、Tool invocation 或副作用。该 preview
是 Conversation 中的展示内容，不是 `WorkingPlanSnapshot`、待批准 Command 或权限事实；
用户后续“开始执行”是新的用户输入，模型再从当前目标和上下文物化 WorkingPlan/actions。

主循环固定为：

```text
accepted user input / domain Definition
  + materialized Context
  + EffectiveCapabilities
  + remaining budget
  -> Model AgentTurnDecision
  -> FinalMessage
     or Admission(actions)
       -> accepted action execution
       -> ToolResult / Agent status / Artifact
       -> Model
     + rejected action DecisionFeedback
       -> Model revision / clarification / fail closed
```

这是完整 ReAct，而不是一次 ToolCall。每次真实 Observation、DecisionFeedback、外部用户
输入或 capability availability 变化都可以触发模型修订 WorkingPlan 和下一组 actions。
Admission rejection 仍是 `DecisionFeedback`，不是 Observation；Runtime 不通过修改计划
或补 action 来“帮助”模型继续。

`FinalMessage` 可以是答案、澄清、能力不足、预算耗尽或失败说明。直接回答不得伪造
Task、Command、Receipt 或 Completion。

`ToolCallProposal` 必须引用当前有效 Tool 并提供 typed arguments。普通只读且可安全重试
的调用在 Admission 后直接执行；需要审批、副作用治理、不可安全重试或 durable dispatch
的调用才冻结为 immutable `ExecutableCall`。

`AgentDelegationProposal` 必须引用当前有效 Agent profile，提供 bounded sub-goal、最小
Context refs、预算和期望 Artifact 类型。它不授予远程 Agent 权限，也不代表远程 Agent
能完成父目标。

同一 turn 可以提出多个互不依赖的 actions。依赖另一个 action 结果的动作必须等待下一轮
Observation 后重新提出，不能在同一 batch 中猜测 payload。Runtime 只有在 policy 能
机械证明所有已接受 action 均为只读/可安全重试，或为无共享可写状态的独立 bounded
delegation 时才能并发执行；否则按模型输出的 tuple 顺序逐个进入各自准入、审批和
dispatch 边界。需要业务原子性的多步写入必须使用领域 Procedure，不新增通用 atomic
action batch。

### 6.4 不设计路径分类器

Runtime 不先计算 `selected_path`、`complexity`、`needs_tool`、`needs_task` 或 `ProposedResultKind`。模型直接在当前能力集合中产生下一步。

Runtime 只处理：

- schema 是否有效；
- capability 是否存在且当前可用；
- ResourceRef 是否属于当前 authority；
- operation 是否在 allowlist；
- 是否需要 approval；
- 参数是否与批准 digest 一致；
- dispatch 是否发生、是否可安全重试；
- ToolResult/Agent status 是否绑定当前 invocation。

Runtime 不能判断模型是否“理解对了”、WorkingPlan 是否语义最优、是否选择了最合适的
Tool/Agent，或 Artifact 是否真正回答了用户问题。

### 6.5 身份与运行引用

旧版本 E2E 示例曾使用 `session_ref`，但没有说明它是用户会话、模型上下文线程还是一次执行。该字段从目标输入中删除，不保留一个含义不清的通用字符串。

目标输入只保留以下不同 owner 的 typed identity：

| 引用 | 来源与 owner | 作用 | 是否由模型产生 |
| --- | --- | --- | --- |
| `actor_ref` | Auth/identity boundary | 确定用户、组织和授权范围 | 否 |
| `conversation_ref` | Transport 或 Conversation service | 把多次用户消息归入同一个用户可见对话，读取会话历史和对话级偏好 | 否 |
| `interaction_run_ref` | Interaction runtime | 标识一次请求的执行、暂停、恢复和最终结果 | 否，由 Runtime 创建 |
| `checkpoint_thread_ref` | Checkpoint adapter | 标识底层图执行恢复所需的线程键 | 否，由 Runtime/adapter 创建 |
| `child_agent_run_ref` | AgentGateway | 标识一次远程 Agent 委托及其 status/artifact | 否，由 AgentGateway 创建 |

这些引用不能互相替代：

- `conversation_ref` 可以跨多个 `interaction_run_ref`；
- 一个 `interaction_run_ref` 只能有一个执行生命周期，但可能经历多次 suspend/resume；
- `checkpoint_thread_ref` 是技术恢复键，不是用户业务会话；
- `child_agent_run_ref` 是被委托 Agent 的生命周期，不是父交互的生命周期。

当前工程中的 `EntryInput.session_id` 承担了部分 `conversation_ref` 的作用；入口会为每次请求生成 `run_id`，并由 Runtime 根据用户和会话生成 checkpoint `thread_id`，可见 [entry_orchestrator.py](../../src/personal_agent/orchestration/entry_orchestrator.py:368)。目标态应将这一层次改成 typed refs，而不是继续扩散 `session_id`、`thread_id`、`run_id` 的同义或可写副本。

设计 `conversation_ref` 的唯一理由是跨请求延续用户明确选择的对话上下文；它不用于决定 Tool、证明事实、授予权限或表示任务完成。如果产品不提供跨请求对话，输入就不应携带该引用。

### 6.6 组合循环与 typed 交接

普通组合沿用同一个主循环，不新增通用 Orchestrator Model：

```text
AgentTurnDecision
  -> actions[]
  -> ToolResult / typed failure / DecisionFeedback / Agent status / ArtifactRef
  -> revised WorkingPlanSnapshot + next actions[]
  -> FinalMessage
```

每项能力拥有自己的 input/output contract。组合只传递 owner 已提交的 typed ref、typed
result、EvidenceRef、ArtifactRef、Receipt 或 typed limitation/failure：

- Grounded Ask 返回可解析 EvidenceRef、检索范围和 typed retrieval limitation/failure；
  Evidence 是否语义充分仍由模型或外部权威判断，不返回模型自述 grounding；
- Research 返回 ResearchRun ref、来源引用、Digest 或领域 limitation/failure；
- Capture 返回 application-owned ResourceRef 和 ingestion 结果；
- Knowledge Lifecycle 返回目标 ResourceRef、revision 关系和 mutation Receipt；
- Review 返回 Review 内容引用和 feedback intake 结果；
- A2A 返回 ChildAgentRun status、Message 或 ArtifactRef。

不得新增一个字段并集式 `CapabilityResult`、raw dict `shared_context` 或字符串 summary
作为能力间身份和事实交接。现有领域结果若尚未携带上述 typed ref，应修改该领域契约和
全部调用方，而不是在组合层补 converter 或镜像 Model。

同一 `InteractionRun` 内的 ToolResult 可以作为下一轮临时 Observation。长时
ResearchRun、ChildAgentRun 或 Scheduled Intelligence 恢复时，父上下文只保存重建所需
ref/digest；恢复后从 canonical owner 重新读取受 scope 和预算约束的内容，不把完整结果
复制进 checkpoint。Context 仍按 visibility、requirement、model semantic selection 和
budget materialization 处理。

写操作必须保持独立入口。模型可以在回答后建议 Capture、supersede 或 maintenance
mutation，但只有用户显式选择或已接受的版本化 ProductMode 才能形成相应 Proposal；
Admission 不得把只读 Observation 升级为写 intent。Tool Receipt、Agent completed、
semantic verification 和组合产品结果继续分别成立，任何一个都不能单独结束组合旅程。

### 6.7 复杂任务的三种执行形态

复杂度不是 Runtime 分类字段，而是模型结合用户目标、Observation 和能力集合后自然形成
的执行形态：

1. 普通复杂 Interaction：模型维护临时 WorkingPlan，经多轮 read Tool、受治理 Action 和
   Observation 动态修订，最终返回 FinalMessage；不创建通用 Task。
2. 长时领域任务：模型澄清后创建 ResearchRunDefinition、ResearchSubscription 等领域
   Definition；领域 Aggregate 拥有恢复和终态，内部仍可运行 ReAct，WorkingPlan 不替代
   Aggregate。
3. Manager + specialists：父模型维护用户目标和最终答复责任，把独立、bounded sub-goal
   作为 actions 委托给专业 Agent；子 Agent 使用独立 Context/权限/预算并返回
   Message/Artifact，父模型综合。子 Agent 不共享父 Agent 可写状态。

当用户或领域 Definition 已提供可检查的结果要求时，模型可以调用语义 verifier、Review
Agent 或其他只读检查能力，并根据 typed `SemanticVerificationReport` 修订 WorkingPlan
和答案。这是
evaluator-optimizer 循环；Verifier 不得创造 success criteria、推翻 Receipt 或直接把
任务标为完成。普通请求不为了使用该模式伪造 ResultContract。

### 6.8 预算、停止与恢复

Runtime 可以从版本化 policy 和 accepted Definition 机械计算 max turns、Tool/Agent call
数量、token/cost、wall-clock、并发数和 delegation depth。预算只限制循环，不决定业务
替代路径。达到边界时只能返回当前已提交结果和 limitation、请求外部输入/追加预算、
暂停 durable run 或 fail closed，不得生成简化版业务答案。

主循环只在以下条件停止：

- 模型返回无 actions 的 `FinalMessage`；
- 模型请求外部用户输入，当前 InteractionRun 进入明确等待；
- 领域 Aggregate 根据自己的 Definition 和事实进入终态或等待态；
- authority/policy 明确终止；
- 预算耗尽并返回 limitation/failure。

恢复不读取“上次计划说做到哪一步”来决定执行。Checkpoint 保存用户输入/显式选择、
accepted Definition、已提交 ToolResult/Receipt/Artifact refs、DecisionFeedback、冻结
Command、committed usage event refs/digests 和重建所需 revision/ref；remaining budget
始终从版本化 policy 与 usage facts 重新计算，不保存第二份计数。重启后模型以
`revision_reason=context_rebuild` 重新物化 WorkingPlan；已冻结 Command 和 Provider
effect 必须复用原 digest，未冻结的语义下一步允许根据最新事实重新规划。Context
compaction 同样只保留或引用 canonical facts，不把摘要或 WorkingPlan 升级为事实 owner。

Phase 1 主循环能力的最低 Release 证据为：

| 主循环能力声明 | 最低 Release E2E |
| --- | --- |
| WorkingPlan + Observation 驱动的 ReAct 修订 | L01 |
| 同一 turn 的独立 actions 和受控并发 | L02 |
| 崩溃后从 canonical facts 重建计划并继续 | L03 |
| Manager + bounded specialist 并行委托和父级综合 | L04 |
| 预算限制、停止条件和无业务 fallback | L05 |
| Evaluator feedback 驱动修订且不改写执行事实 | L06 |

### 6.9 Decision Ownership Taxonomy

Phase 1 新增或保留的每个分支必须按以下 owner 执行：

| 分支 | Decision owner | 唯一性来源 | 唯一允许结果 |
| --- | --- | --- | --- |
| 是否需要 WorkingPlan、如何分解、Observation 后如何修订 | Model | 用户输入、可见 Context、EffectiveCapabilities、typed results/feedback | 模型产生新的 transient WorkingPlan/actions，或 FinalMessage |
| `AgentTurnDecision` envelope 是否有效 | Deterministic protocol validation | schema version、模型实际输出、`actions` 非空约束 | accept envelope 或返回 schema DecisionFeedback；不补 Plan/action |
| 单个 action 是否准入 | Deterministic Admission | accepted typed Proposal、capability snapshot、authority/scope、versioned policy | accepted 或 denied DecisionFeedback |
| 同 turn actions 是否并发 | Deterministic execution control | accepted action tuple/order、Tool/Agent definition 中的 read-only/safe-retry/side-effect contract、typed Resource refs、versioned concurrency policy | policy 唯一允许时并发；否则按模型给定 tuple 顺序进入独立准入/执行边界，不猜测依赖 |
| 是否冻结 ExecutableCall/请求 approval | Deterministic governance | accepted Proposal、risk/side-effect/idempotency policy、authority facts | 直接只读执行，或生成唯一 immutable Command/approval boundary |
| 是否因 budget 停止 | Deterministic loop control | versioned budget policy、committed Model/Tool/Agent usage facts | remaining budget 大于零则继续准入；否则 stop/wait/fail closed |
| crash/replay 后执行什么 | Deterministic recovery | accepted Definition、ExecutionCommandDigest、Journal/Receipt、committed usage/ref facts | 复用冻结 Command/已提交事实；未冻结语义下一步返回模型重算 |
| Artifact/Evidence 是否语义支持用户结果 | Model verifier / external authority | accepted result requirements、可见 Evidence/Artifact、verifier model/version | typed SemanticVerificationReport；不得改写执行事实或直接 Completion |
| 领域 Aggregate 是否进入终态 | Deterministic domain state machine | accepted domain Definition、versioned transition policy、已提交 domain events | 唯一状态转换；不得从 WorkingPlan 推导完成 |

任何确定性分支都不得新增 intent、target、payload、requested result 或 semantic success。
若 concurrency、retry、terminal transition 等无法由表中 accepted fields、policy 和 facts
唯一决定，Runtime 必须停止自动选择并把现状交回模型或外部权威。

## 7. 结果义务与完成边界

### 7.1 删除通用 ResultContractProposal

模型不得通过 `ResultContractProposal` 为系统创造新的产品义务。该对象没有独立产品价值，并会诱导模型同时定义验收标准和按该标准自我完成。

需要长期业务结果时，采用产品拥有的 typed command：

- `CreateResearchRun`；
- `CreateResearchSubscription`；
- 未来其他明确产品能力的 Command。

Command 字段来自用户明确输入、用户对模型澄清问题的回答或版本化 ProductMode。Admission 只接受或拒绝，不补写 topic、target、required results 或 success criteria。

### 7.2 普通 Interaction 不需要结果合同

直接回答、普通检索和多轮只读/受治理 ReAct loop 以 `FinalMessage`、协议安全、真实
ToolResult/Receipt 和必要的语义验证闭环，不创建 AcceptedResultContract、Goal、
CompletionReport 或通用 DurableTask。复杂 Interaction 可以有临时
`WorkingPlanSnapshot`；它不是结果合同，也不定义新的产品义务。

如果用户只说“完整研究一下”，模型可以询问范围、时限和输出形式；用户回答后创建具体 `ResearchRunDefinition`。系统不保存模型自拟的通用结果合同。

### 7.3 使用领域 Aggregate，而不是先造通用 DurableTask

当前已有长生命周期业务只有 ResearchRun、ResearchSubscription、Delivery、Review 等领域 Aggregate。它们拥有各自 definition、projection 和 terminal states。

目标态不先引入通用 `DurableTask` 作为所有长时工作的父模型：

- Research 使用 `ResearchRun`；
- A2A 委托使用 `ChildAgentRun`；
- 普通会话使用 `InteractionRun`；
- 工具 dispatch 使用 `InvocationJournal`。

只有两个以上领域证明存在完全相同、且不能由组合基础设施解决的业务 lifecycle 时，才重新评估是否抽取通用 Task aggregate。

### 7.4 执行事实不等于语义成功

```text
ToolResult / Receipt
  = 某个 Provider 调用实际发生并返回什么

Agent Task completed
  = 远程 Agent 声称其 Task 已结束

Semantic verification
  = 模型或外部权威对答案与证据支持关系的判断

Product completion
  = 领域 Aggregate 根据自己的 definition 和已接受事实进入终态
```

四者不得互相替代。Semantic verifier 不得推翻 Receipt，Receipt 或远程 Task completed 也不得冒充用户目标成功。

## 8. E2E 设计规则

### 8.1 先声明 Capability Profile

每个 Release E2E 必须声明部署前提：

```text
baseline
baseline + web_reader
baseline + web_search
baseline + github_mcp
baseline + notion_mcp
baseline + gpt_researcher_a2a
baseline + web_search + delivery
```

只有 Profile 中真实配置、可发现、可授权并能在测试环境执行的能力，才能写成功分支。未接入天气 Provider 时，不存在“成功获得当天气温”的 Release E2E；未接入安全审计 Agent 时，不存在“完成安全审计”的 Release E2E。

未来期望能力只能写成 capability acceptance scenario，不能计入 release catalog，不能用 Fake Provider 冒充端到端完成。

### 8.2 E2E 只证明用户旅程

E2E 必须从真实 transport、真实模型、真实 PostgreSQL 和该 Profile 要求的真实 Provider 进入，并断言：

- 原始用户输入；
- 用户可见终态；
- 可解析的引用/Artifact/Receipt；
- 外部 effect 及次数；
- 权限拒绝和能力缺失时的用户结果；
- 重启恢复后的同一业务结果。

Schema validator、字段 immutable、digest 计算、候选过滤和单个状态转移优先使用单元或集成测试，不为每个内部对象单独创建 E2E。

### 8.3 原生能力证据闭环

Phase 0 已将 E01–E13、C01–C04 的声明映射收敛到 `release_gate.py`，并以
`evidence_catalog.py` 和同 revision trace archive 的交集 fail closed。该投影不持久化，
也不读取 Runtime availability 来证明发布可信。L01–L06 仍是 Phase 1 目标，待主循环
落地时再进入同一机器门禁。

“代码已有”、对象存在、旧架构用例、Capability Profile、专项 suite、skip、dirty
revision 或 Fake Provider 均不能产生发布声明。组合证据不能替代基础证据，基础证据也
不能替代组合证据。当前实现与实际基线见 Phase 0 总结。

### 8.4 最小 Release E2E 集合

#### E01：Conversation

Profile：`baseline`。

至少包含三个真实连续会话变体：

1. 明确问题直接返回非空 `FinalMessage`；
2. 关键输入缺失时返回澄清问题，不臆造 target、payload 或完成事实；
3. 用户在同一 conversation 中补充信息或追问时，只使用该 conversation 的可见历史继续回答。

结果：直接回答不创建 ToolCall、ExecutableCall、ResearchRun、ChildAgentRun、Receipt
或 CompletionReport；澄清和追问保持同一 conversation identity，不读取其他会话。

证明：Conversation 的直接回答、澄清和连续对话均真实可用；Runtime 不要求所有请求
进入 Task/Goal/Plan。

#### E02：原生只读知识问答

Profile：`baseline`。

前置：用户 Workspace 已有带 EvidenceSpan 的资料。

输入：“根据我的资料解释 X，并给出引用。”

结果：只读取当前用户 Workspace；引用可以解析回 canonical EvidenceSpan；无知识写入。

能力不足分支：证据不足时明确说明不足或继续询问，不引用其他用户、互联网或模型记忆冒充个人资料。

证明：普通只读能力、Resource scope、Evidence identity 和 Ask 不写入。

#### E03：指定上传 Artifact 问答

Profile：`baseline`，但只有 Artifact ResourceRef、scope admission 和 citation binding 落地后才能进入 release catalog。

步骤：上传文件，获得 application-owned ArtifactRef；用户明确选择该 Artifact 提问。

结果：最终引用只来自所选 Artifact；`inspect_artifact` 不接收模型任意生成的服务器 `file_path`；Ask 不保存长期 Claim。

当前状态：capability acceptance scenario，不是当前 release E2E。

证明：这是知识 Agent 原生能力缺口，而不是 MCP/A2A 能力。

#### E04：受治理的知识删除

Profile：`baseline`。

步骤：

1. 模糊目标时请求用户选择 typed NoteRef，零副作用；
2. 精确 NoteRef 形成 `ToolCallProposal`；
3. Runtime 冻结 `ExecutableCall`，AuthorizationDigest 与 ExecutionCommandDigest 分离；
4. 用户拒绝时零副作用；
5. 用户批准时执行一次删除并返回 Receipt；
6. approval 等待或 dispatch 后重启，恢复同一 InteractionRun/Invocation，不重新调用模型生成参数；
7. replay 不重算或覆盖已冻结 Command。

证明：accepted、denied、外部用户输入、双 digest、Journal recovery、Proposal 未被管控层静默改写和 Provider effect 恰好一次。

#### E05：ResearchRun 产品旅程

Profile：`baseline + web_search`。

输入：“研究 Agent 工具协议最近的发展，生成 5 条带来源简报。”

结果：创建具体 `ResearchRun`；展示运行状态；生成带来源 Digest；搜索或证据不足时进入领域定义的 limitation/failure 状态，不伪造 verified；重启后从 ResearchRun/queue 状态继续。

证明：真实领域 Durable lifecycle，而不是为了框架存在而创建通用 DurableTask。

#### E06：MCP 只读扩展

Profile：`baseline + github_mcp` 或 `baseline + notion_mcp`。

输入必须使用当前 Connector 真正支持的 read/search 场景。

结果：模型根据当前 Tool 描述提出 MCP ToolCall；Host 检查 scope、credential 和 data egress；返回真实 ToolResult；普通只读调用不创建持久 ExecutableCall 或业务 Task。

缺失分支：移除 Connector 或 credential 后返回 capability unavailable/acquisition，不让 Runtime 生成替代业务答案。

证明：MCP 扩展可调用资源，但不接管产品语义和权限。

#### E07：A2A 深度研究委托

Profile：`baseline + gpt_researcher_a2a`。

输入：“委托深度研究 Agent 调研 X，并把报告返回给我。”

结果：发现真实 Agent profile；模型提出 bounded delegation；通过 AgentGateway submit/poll/stream；长时工作保存 `ChildAgentRun`；最终返回真实 Artifact；支持 cancel、timeout 和恢复。

失败分支：Agent 不可用或 skill 不匹配时明确失败/获取能力，不回退成伪造 A2A Artifact。远程 Task completed 只证明远端结束，父 Agent 仍决定如何向用户说明结果。

证明：A2A 扩展的是自治专业工作，不是普通 Tool；远端 Artifact 不冒充父目标确定性成功。

#### E08：Ask 与 Save 分离

Profile：`baseline`。

步骤：先基于资料回答，再检查长期知识没有新增 Claim；用户明确选择保存内容和 Workspace 后，才进入 Capture/ingestion 治理路径。

结果：Ask 不隐式保存模型回答或 Subagent summary；保存失败不改变历史回答事实；assistant inference 不自动成为长期知识。

证明：Query、临时 Context 和 Indexing/Knowledge mutation 边界分离。

#### E09：多来源 Capture

Profile：文本、文件和会话结论使用 `baseline`；网页变体使用
`baseline + web_reader`，其中必须存在产品批准的真实网页读取 Provider。

使用参数化用户旅程分别从真实入口提交：

1. 用户直接提供的文本；
2. 用户提供的网页 URL；
3. 用户上传的文件；
4. 用户明确选择保存的会话结论。

结果：每种输入只通过 governed ingestion 写入一次；创建 application-owned ResourceRef
和对应 Workspace/Knowledge 事实；文件路径、网页抓取临时结果和对话临时 Context
不成为跨边界 identity。重试不重复写入，解析或 Provider 失败时返回可见失败且不产生
半完成知识。随后从用户入口检索可解析回同一 canonical Resource。

证明：Capture 的全部声明输入类型、身份边界、失败原子性和最终可检索结果，而不是只
证明内部 ingestion service 可调用。

#### E10：完整 Knowledge Lifecycle

Profile：`baseline`。

步骤：

1. 从用户入口创建一条隔离知识并记录 canonical ResourceRef；
2. 更新内容产生新 revision，旧 revision 被 supersede 而不是原地覆盖；
3. 输入与当前事实冲突的资料，形成可见冲突状态而不是 validator 静默选边；
4. 删除需要 E04 的治理边界，删除后普通检索不可见；
5. 恢复同一 canonical identity，历史 revision 和冲突事实仍可审计，当前检索结果唯一。

结果：每一步都从真实 transport 进入并断言用户可见结果、canonical identity、revision
关系和检索反事实；在更新、删除或恢复等待期间重启，恢复消费既有事实，不重新生成
业务 payload。

证明：Knowledge Lifecycle 的 update、supersede、conflict、delete 和 restore 全部闭合；
只通过删除 E2E 不得把整个能力标记为已交付。

#### E11：Review

Profile：`baseline`。

前置：用户 Workspace 中存在可生成复习内容且已到期的真实知识。

步骤：用户请求复习；系统返回可解析到来源知识的 Review 内容；用户提交 typed feedback；
重启后再次进入复习。

结果：Review aggregate 记录生成、展示和 feedback 事实；feedback 只通过唯一入口写入，
后续复习投影由这些事实计算；不得把模型生成文本直接写成长期知识，也不得用 Review
Receipt 冒充用户已经掌握。

证明：用户确实获得复习内容且反馈影响后续复习，而不是只证明 Review Model 或 scheduler
对象存在。

#### E12：Knowledge Maintenance

Profile：`baseline`。

前置：隔离 Workspace 包含同主题重复资料、一个知识孤岛、一个薄弱连接和一组冲突资料，
全部具有 canonical ResourceRef。

步骤：用户请求知识维护；模型基于当前 Workspace 产生维护建议；用户拒绝一个写操作并
批准另一个精确写操作；随后重新查询维护结果。

结果：建议中的对象引用可解析且不跨 Workspace；拒绝分支零副作用；批准分支只执行已
冻结的精确变更一次；重新查询能观察到该变更，未批准的重复、孤岛、薄弱连接或冲突仍
保持原状。语义建议质量由带 model/version/input/output digest 的 verifier 或外部权威
评估，确定性 Runtime 只验证身份、scope、授权和执行事实。

证明：Knowledge Maintenance 产生可行动的用户结果，同时不让确定性代码发明维护策略
或把“生成了建议对象”当作能力成功。

#### E13：Scheduled Intelligence

Profile：`baseline + web_search + delivery`，并启用真实 scheduler、worker 和
Delivery Provider。

步骤：用户从真实入口创建 ResearchSubscription；到达调度窗口后创建一次
ResearchRun，生成带来源 Digest 并投递；在 enqueue、research dispatch 或 delivery
边界终止并重启真实进程；用户从真实投递入口提交偏好 feedback。

结果：同一订阅窗口至多产生一个 ResearchRun 和一次外部投递；恢复不重新生成订阅参数、
不重复 Provider effect；Delivery 引用可解析到对应 ResearchRun/Digest；feedback 写入
唯一偏好入口并影响下一窗口，不能反向改写历史 Digest 或 Delivery。

能力不足分支：搜索、scheduler、credential 或 Delivery Provider 不可用时进入明确的
等待/失败状态，不生成简报、投递成功或偏好已应用的假事实。

证明：Scheduled Intelligence 的订阅、周期执行、研究、幂等投递、恢复和反馈形成完整
用户旅程；scheduler、queue、Delivery Model 的单独测试不构成 Release 证据。

### 8.5 组合强能力 Release E2E

#### C01：Personal Research Analyst

Profile：`baseline + web_search`。

输入：“先根据我的资料回答 X；如果资料不足，补充外部研究并给出引用。不要自动保存，
等我确认后再保存结论。”

步骤：

1. Grounded Ask 只读取当前 Workspace，返回可解析 EvidenceRef、检索范围以及无结果、
   截断或权限拒绝等 typed retrieval limitation；是否覆盖用户问题由模型判断；
2. 模型根据用户目标、Evidence 和 limitation 判断是否需要 Research，不由 Runtime 按
   “结果数”“字符串包含”或分数阈值强制路由；
3. 若需要，模型创建具体 ResearchRun，Research 结果作为 Observation 返回；
4. 模型综合个人资料与外部来源，明确区分二者并返回可解析引用；
5. 首次答案后长期知识零写入；用户明确确认内容和 Workspace 后才形成 Capture Proposal；
6. Capture 完成后从用户入口重新 Grounded Ask，可解析回同一 canonical Resource。

结果：用户获得比单独 Grounded Ask 或 Research 更完整的有依据答复；外部事实不会冒充
个人知识，回答不会隐式保存，保存失败也不改写历史回答事实。

能力不足分支：搜索 Provider 不可用或研究证据仍不足时，模型明确 limitation 或请求
外部输入，不由 Runtime 生成替代查询、替代内容或虚假引用。

#### C02：Continuous Knowledge Steward

Profile：`baseline + web_search + delivery`。

前置：用户从真实入口创建明确 topic、scope、schedule、Delivery target 和允许结果类型
的 ResearchSubscription；Workspace 中存在可比较的历史知识。

步骤：

1. scheduler 只按已接受 Subscription definition 和时间事实创建 ResearchRun，不新增
   topic、维护目标或写入 intent；
2. 模型基于新 Research Evidence 与当前 Workspace 判断变化、冲突和缺口，生成带
   ResourceRef/EvidenceRef 的维护建议；
3. Delivery 展示新证据、与已有知识的关系、limitation 和建议动作；
4. 用户拒绝一个 mutation、批准另一个精确 mutation；
5. Knowledge Lifecycle 只执行批准动作一次，形成 revision/supersede/conflict 事实；
6. 下一调度窗口和重启恢复继续消费 canonical Subscription、cursor、ResearchRun 和
   Delivery，不重新生成历史业务参数。

结果：系统能够持续发现并解释变化，但 scheduler、validator 或 Procedure 不替用户决定
业务 payload；未批准建议不改变长期知识；同一窗口最多一个 ResearchRun 和一次投递。

能力不足分支：搜索、Delivery、credential 或用户批准缺失时进入明确等待/失败状态，
不得把旧 Digest 重发成新结果或静默更新知识。

#### C03：Personalized Learning Agent

Profile：`baseline + web_search`。

步骤：

1. Grounded Ask 和 Review 从同一 Workspace 的 canonical knowledge 生成带来源的复习内容；
2. 用户通过 typed feedback 明确“不理解”、已掌握或需要补充的知识点；
3. Review aggregate 独占 feedback 事实和后续复习投影；
4. 只有用户进一步明确要求补充研究时，模型才创建有界 ResearchRun；feedback 本身不被
   Runtime 扩写成研究目标；
5. Research 结果先作为带来源答复展示，用户确认后才 Capture；
6. 下一次 Review 从 canonical Review feedback 和新增 Resource 物化上下文，产生可验证
   的内容变化，历史 Review 和 feedback 不被覆盖。

结果：用户反馈能够影响后续复习，补充研究和长期保存仍保持独立 intent、独立写入口和
可见确认；Research Receipt 不冒充用户已掌握。

能力不足分支：用户未授权研究、Provider 不可用或结果证据不足时，保持原 Review 状态并
明确说明，不自动生成替代教材或写入模型推断。

#### C04：Expert Collaboration Agent

Profile：`baseline + gpt_researcher_a2a`。

输入：“结合我的资料，委托深度研究 Agent 调研 X，并给出最终带引用结论。”

步骤：

1. Grounded Ask 取得当前 Workspace 中与 X 相关的最小 Evidence refs；
2. 模型提出 bounded AgentDelegationProposal，只下放必要 Context refs、预算和期望
   Artifact 类型；
3. AgentGateway 返回 ChildAgentRun status 和真实 ArtifactRef，长时等待与重启恢复不
   重新生成 delegation payload；
4. 父模型读取 Artifact 和个人 Evidence，判断其是否支持用户问题，并负责最终综合；
5. 远程 Task completed、Artifact 存在、semantic verification 和最终用户答复分别记录，
   互不冒充；未经用户明确确认不 Capture 远程报告或父模型 summary。

结果：专业 Agent 扩展开放式研究能力，父 Agent 保持 conversation、scope、证据综合和
最终答复责任；远程 Agent 看不到完整会话或无关 Workspace。

能力不足分支：Agent profile 不可用、skill 不匹配、timeout、Artifact 缺失或语义上不
足以回答时，父 Agent 明确 limitation 或请求用户决定，确定性 Runtime 不回退到
`web_search`、伪造 Artifact 或宣布父目标完成。

### 8.6 复杂任务主循环 Release E2E

#### L01：Observation 驱动 WorkingPlan 修订

Profile：`baseline`。

前置：隔离 Workspace 中存在用户明确选择的 Resource A 和 Resource B；A 的 EvidenceRef
已经由 canonical lifecycle 标记为 stale，B 包含完成问题所需的有效 EvidenceSpan。

输入：“先给出简明工作计划，再检查 A 和 B，根据实际证据调整计划，最后只用有效引用
回答 X。”

结果：

1. 模型先返回带 `WorkingPlanSnapshot` 和 read actions 的 `ContinueTurnProposal`；
2. inspect A 返回 typed stale limitation，inspect B 返回可解析 EvidenceRef；
3. 后续模型 turn 基于该结果产生 `revision_reason=observation` 的新 WorkingPlan，并改变
   剩余工作或下一 actions，不把 A 当作有效证据；
4. 最终答复只引用 B，并向用户说明 A 的限制；如果忽略 Observation 或不重新决策，就
   无法满足“只用有效引用”的用户结果；
5. WorkingPlan 原样存在于 append-only model trace，但业务数据库和 checkpoint 中没有
   Plan aggregate、步骤完成状态或由 Runtime 补写的计划字段。

拒绝分支：模型继续引用 stale A，或 Admission/Runtime 修改 WorkingPlan、补建替代查询时，
用例失败。不能只断言出现两个 Plan 对象。

Plan-only 变体：用户先要求“只展示计划并等待”，第一轮必须用 `FinalMessage` 返回 plan
preview，且零 Tool/Agent invocation；用户随后明确要求执行，模型才产生
WorkingPlan/actions。Runtime 不把 plan preview 或“看起来合理”解释成执行授权。

#### L02：多 action 与安全并发

Profile：`baseline`。

前置：用户明确选择三个相互独立、属于同一 Workspace 且真实可读的 ArtifactRef；测试
Provider 不是 Fake，每次读取都产生真实 invocation timing 和 typed result。

输入：“并行读取这三份资料，比较它们对 X 的不同结论，并给出逐项引用。”

结果：

1. 模型返回一个 `ContinueTurnProposal.actions`，包含至少两个无依赖 read proposals；
2. Admission 分别接受每个 Proposal，不合并 payload、不生成 `action`/`actions` 双轨状态；
3. Runtime 根据 read-only、safe-retry 和无共享写状态并发执行，invocation 时间窗口实际
   重叠；每个结果分别绑定自己的 invocation/ref；
4. 模型在下一 turn 综合全部 Observation，最终比较结果覆盖三份资料且引用可解析；
5. 普通读取不创建 ExecutableCall、通用 Task、Plan aggregate 或 CompletionReport。

Scope 拒绝变体：其中一个 ArtifactRef 属于另一 Workspace 时，该 action 只得到 typed
DecisionFeedback，零越权读取；模型明确说明缺失资料。Runtime 不把被拒 action 替换为
其他资料，也不把 DecisionFeedback 伪装成 ToolResult。

#### L03：崩溃后计划重建与 ReAct 继续

Profile：`baseline + web_search`。

输入：“先检查我的资料，再补充外部来源，最后生成带个人资料和外部来源引用的比较。”

步骤：

1. 模型形成 WorkingPlan，完成至少一个真实 read ToolCall，ToolResult/ref 已提交；
2. 在该 Observation 已提交、下一次模型调用尚未发生的窗口终止真实服务进程，不使用
   进程内 hook；
3. 新进程恢复同一 InteractionRun，从用户输入、已提交 Observation refs、capability
   revision 和剩余预算重新物化 Context；
4. 模型产生 `revision_reason=context_rebuild` 的新 WorkingPlan，继续后续 Research/读取；
5. 最终答复同时包含个人资料和真实外部来源的可解析引用。

结果：恢复不读取或覆盖旧 WorkingPlan，不丢失已提交 Observation，也不把安全 read
重试冒充新的业务事实。新旧 WorkingPlan 可以不同，但 accepted user intent、已提交事实
和最终用户结果保持一致。冻结 Command 与不可安全重试 effect 的恢复仍由 E04 证明，
不能用本用例的对象存在顺带宣称覆盖。

#### L04：Manager + bounded specialists

Profile：`baseline + gpt_researcher_a2a`；Provider 必须支持两个独立真实 ChildAgentRun。

输入：“分别调研协议标准演进和生产实现案例，再由你综合两者的共同点、差异和来源。”

结果：

1. 父模型的 WorkingPlan 将问题分解为两个 bounded sub-goal，并在同一 actions 集合提出
   两个无共享写状态的 AgentDelegationProposal；
2. AgentGateway 建立两个独立 ChildAgentRun，可并行 submit/poll，不下放完整会话或无关
   Workspace；
3. 每个 specialist 返回自己的 Message/ArtifactRef，不能写父 Agent Workspace 或替父
   Agent 返回 FinalMessage；
4. 父模型读取两个结果并生成真正同时使用二者的综合答复，引用可解析；只返回两个
   specialist summary 的拼接不算通过；
5. 一个 specialist timeout 的变体必须返回有边界的部分结果和 limitation，不伪造缺失
   Artifact，不让成功 specialist 自动完成整个父目标。

证明：专业分工、独立 Context、并行执行和父级综合共同改善用户结果，而不是只证明创建
了两个 ChildAgentRun。

#### L05：预算耗尽时 fail closed

Profile：`baseline + web_search`，使用版本化生产 budget policy，将本 InteractionRun
限制为少于完成用户明确要求所需的 Tool/Agent calls；不得 monkeypatch 主循环。

输入要求读取五个指定真实来源并逐一比较，当前 policy 只允许两个外部 read calls。

结果：

1. 模型可以形成 WorkingPlan 并执行预算内 actions；
2. Runtime 只根据已接受 policy 和实际 usage 计算 remaining budget，不改写目标、不选择
   “简化为两个来源”的业务 fallback；
3. 预算耗尽后不再 dispatch，返回已完成范围、缺失来源和可选的外部输入/追加预算请求；
4. 不生成声称覆盖五个来源的答案、CompletionReport、替代引用或虚假成功；
5. 重启后 remaining budget 连续，不通过重建 WorkingPlan 重置 usage。

证明：复杂循环有确定停止边界，失败结果对用户仍然真实可解释；`max_turns` 字段存在或
循环恰好停止本身不构成用户结果证据。

#### L06：Evaluator feedback 驱动结果修订

Profile：`baseline`，启用真实 semantic verifier model/profile。

前置：用户明确选择具有 canonical EvidenceRef 的资料，并提供一份待核查草稿；草稿包含
一个被资料支持的 Claim 和一个资料不支持或明确冲突的 Claim。该反例来自用户原始输入，
不通过测试 hook 篡改模型输出。

输入：“核查这份草稿是否被所选资料支持；根据核查反馈修订，最终每个事实性结论都要有
可解析引用，不支持的内容必须删除或明确标为不确定。”

结果：

1. 模型的 WorkingPlan 包含核查和修订工作，并调用只读 semantic verifier；
2. `SemanticVerificationReport` 绑定 verifier/model/version、draft/evidence/input
   digest 和不确定性，
   明确指出 unsupported/conflicting Claim；它不改写草稿、不生成替代答案；
3. 报告作为 typed feedback 返回模型，后续 WorkingPlan 使用
   `revision_reason=observation`，最终答复保留有依据 Claim，删除或限定无依据 Claim；
4. 最终引用全部解析回用户所选 EvidenceRef，确定性 citation identity 检查通过；
5. `SemanticVerificationReport` 不推翻 ToolResult/Receipt，也不直接创建 Completion。若模型连续修订仍
   未通过且预算耗尽，则返回 limitation，不由 Runtime 拼接“通过版”答案。

证明：用户得到的最终结果因 evaluator feedback 发生可验证改善；只断言
`SemanticVerificationReport` 存在、分数变化或模型多调用一次不算通过。

### 8.7 明确删除的旧场景

- 删除“纯自然语言天气问题”与“typed 天气结果合同”的成对框架场景。天气只在真实天气 MCP Capability Profile 存在后增加 Connector E2E；当前通用 `web_search` 不冒充天气能力。
- 删除“模型提出完整安全审计结果合同”。没有安全审计 Tool/Agent 时，这既不是产品能力，也不是可执行 E2E。
- 删除“分别研究 A/B/C 三家公司并生成通用 DurableTask”的假想场景。当前先用真实 `ResearchRun` 验证产品 lifecycle；多独立交付物只有在产品 UX 和领域 Model 明确后再设计。
- 删除单独的“semantic verifier 不通过”业务 E2E。Verifier 的 model/version/digest binding、失败预算和 fail-closed 主要由集成测试覆盖；只有它改变具体用户旅程时才进入相应用例。
- 删除只断言 ResultContractProposal、GoalGraph、持久 Plan、WorkingPlanSnapshot、
  CompletionReport 或某个 Model 存在的用例。

## 9. 最小事实与所有权

| 事实 | canonical owner | 唯一写入口 |
| --- | --- | --- |
| 用户消息和显式选择 | Interaction transport | request/decision intake |
| Workspace/Note/Artifact identity | ResourceStore | application resource creation |
| 本地 Tool definition | Tool registry | application assembly |
| MCP 远端声明 | MCP connection snapshot | MCP discovery |
| MCP Host 风险和权限 | Host approved mapping/policy | configuration/policy deployment |
| A2A Agent 自述 skill | Agent Card/Profile snapshot | Agent discovery/registration |
| 当前 capability availability | Runtime projection | discovery + credential + health materialization |
| 模型输出的 WorkingPlanSnapshot | LLM trace（observability owner，非业务状态） | model adapter append |
| 模型候选工具动作 | ToolCallProposal | model adapter |
| 模型候选委托 | AgentDelegationProposal | model adapter |
| loop budget policy | Versioned runtime policy | policy deployment |
| Model token/cost usage | Model invocation trace | model adapter |
| Tool/Agent call usage | Invocation trace / InvocationJournal / AgentGateway | invocation runtime |
| remaining loop budget | Runtime projection | budget policy + committed usage materialization |
| typed SemanticVerificationReport | Semantic verifier invocation result | semantic verifier adapter |
| 调用准入 | CallAdmissionDecision | Admission |
| 冻结副作用参数 | ExecutableCall | deterministic compiler from accepted Proposal |
| 用户批准/拒绝 | ApprovalDecision | authority decision endpoint |
| Provider dispatch | InvocationJournal | invocation runtime |
| Tool 返回 | ToolResult/Receipt | Gateway/adapter |
| 远程 Agent lifecycle | ChildAgentRun | AgentGateway/adapter |
| 研究业务 lifecycle | ResearchRun | Research service/worker |
| 长期知识 | Workspace/Knowledge aggregate | governed ingestion/lifecycle service |

不得新增统一 Capability 数据库副本去镜像 Tool registry、MCP discovery 和 Agent Card。有效能力目录按 revision 临时组合。

## 10. Admission、Verification 与确定性边界

### 10.1 Admission

Admission 只接受或拒绝 Proposal，不得：

- 替模型选择语义不同的 Tool/Agent；
- 补 target、payload、topic 或结果要求；
- 把 unavailable Tool 替换成 `web_search`；
- 把 ToolCall 改成 AgentDelegation；
- 生成 Plan 或业务 fallback。

拒绝返回 typed `DecisionFeedback`，说明 rejected fields、immutable fields、required repairs 和 remaining budget。

### 10.2 Verification

确定性代码可以证明：

- identity/scope 是否匹配；
- schema 是否有效；
- capability 是否在当前 snapshot；
- approval 是否绑定 AuthorizationDigest；
- dispatch/Receipt 是否绑定 ExecutionCommandDigest；
- required Artifact/Report ref 是否存在且 digest 正确；
- 领域状态机是否满足唯一转换条件。

模型或外部权威才能判断：

- Tool/Agent 是否语义上最适合问题；
- 回答是否充分覆盖用户意图；
- Evidence 是否真正支持自然语言 Claim；
- 研究报告质量是否足够；
- 远程 Artifact 是否解决父目标。

语义 verifier 的报告必须标注 verifier/model/version、answer/input/evidence digest 和不确定性；它是概率判断，不是确定性 Admission 事实。

## 11. Gateway、Journal 与持久化

| 调用类型 | Immutable ExecutableCall | Journal | 业务 Aggregate |
| --- | --- | --- | --- |
| 普通本地只读 Tool，可安全重试 | 否 | 默认否 | 否 |
| 普通 MCP 只读 Tool，可安全重试 | 否 | 仅在远端调用需要恢复时 | 否 |
| 具有副作用或需要审批 | 是 | 是 | 仅当产品能力本身需要 |
| 不可安全重试或结果可能 unknown | 是 | 是 | 仅当产品能力本身需要 |
| A2A 简单 Message | 否 | AgentGateway invocation trace | ChildAgentRun 可省略或短期记录 |
| A2A 长时 Task | 委托参数需冻结 | AgentGateway dispatch state | ChildAgentRun |
| Research | 具体 ToolCall 按自身风险决定 | 按 invocation 决定 | ResearchRun |

Journal 是 dispatch canonical owner。恢复消费冻结调用，不重新请求模型生成业务参数。技术 durability 不自动产生通用业务 Task。

## 12. 破坏性落地顺序

### Phase 1：收敛模型输出和主循环

1. 模型每轮输出收敛为 `FinalMessage | ContinueTurnProposal`，后者只含可选
   `WorkingPlanSnapshot` 和唯一复数 `actions`；
2. `actions` 的业务动作只保留 `ToolCallProposal | AgentDelegationProposal`，删除
   `action`/`actions` 双轨和把 Plan step 直接当执行指令的分支；
3. 引入非权威 WorkingPlan：由模型生成和修订，只进入当前 Context 与 append-only trace，
   不进入业务数据库/checkpoint，不携带权限、payload、完成状态或 Command digest；
4. 主循环恢复完整 ReAct：每轮把 typed ToolResult/Artifact/status 和
   `DecisionFeedback` 返回模型，允许基于 Observation、外部输入和能力变化重新规划；
5. 删除 `ProposedResultKind`、`selected_path`、复杂度分类、通用
   `ResultContractProposal` 和普通请求的强制 Task/GoalGraph/Completion；
6. 同 turn 多 actions 只表达无结果依赖的工作；Runtime 只并发执行 policy 可机械证明为
   safe read 或无共享写状态的 bounded delegation；
7. 长时工作使用领域 Definition/Aggregate，manager + specialists 保持 bounded sub-goal、
   独立 Context 和父模型最终答复 owner；
8. 用临时 EffectiveCapabilities 给模型提供真实可用能力，Admission 不静默改写 Proposal
   或 WorkingPlan；
9. budget policy 与 committed invocation usage 分开拥有，remaining budget 临时推导；
   重启从 canonical facts 重建 WorkingPlan，不覆盖冻结 Command 或重置 usage；
10. 完成 L01–L06 真实复杂任务 E2E 后，才声明 Phase 1 的
    Plan/ReAct/并发/恢复/evaluator-optimizer 能力可信。

### Phase 2：闭合原生知识能力

1. Artifact upload 创建 application-owned ResourceRef，不向模型暴露服务器裸 `file_path`；
2. `inspect_artifact` 按 ArtifactRef 解析并返回可引用 Evidence；
3. Grounded Ask 绑定 Resource scope 和 citation identity；
4. Ask 与 Save 保持两个写入口；
5. 删除重复 Evidence、Claim、ContextPack 状态；
6. Capture 闭合文本、网页、文件和显式会话结论的统一 Resource identity、唯一 ingestion 写入口和失败原子性；
7. Knowledge Lifecycle 闭合 revision、supersede、conflict、delete 和 restore，禁止原地覆盖或用 validator 选边；
8. Review 分离内容生成、feedback 事实和后续复习投影，Knowledge Maintenance 分离模型建议与受治理写动作；
9. Scheduled Intelligence 分离 ResearchSubscription definition、ResearchRun、Delivery 和 preference feedback，并保证每个事实只有一个写入口；
10. 各领域 output contract 返回自己的 typed ref/result/limitation，删除 `AskResult.evidence: list`、raw dict shared context 和组合层 converter，不新增字段并集式 `CapabilityResult`。

### Phase 3：收敛 MCP

1. MCP discovery 声明与 Host approved mapping 分离；
2. 远端 schema 由 Server 拥有，风险/权限/数据出域由 Host 拥有；
3. 删除从 semantic tags 推导 Provider 等价的分支；
4. 只对 Host 明确声明的 binding group 做确定性选择；
5. 完成 GitHub/Notion 真实 Profile E2E 和 capability unavailable 分支。

### Phase 4：A2A 一等化

1. 长时 GPT Researcher 调用从阻塞 Tool wrapper 迁移到 AgentGateway submit/poll/stream/cancel；
2. Agent Card/Profile、ChildAgentRun 和 Artifact 分清 Definition、Projection、Event 与结果；
3. 父 Agent 只持有 bounded delegation 和最小 Context refs；
4. 远程 completion 不自动完成父目标；
5. 完成真实 A2A Profile E2E。

### Phase 5：重建测试层级

1. 基础能力 Release E2E 只保留 E01–E13，组合强能力只保留 C01–C04，复杂任务主循环只
   保留 L01–L06，每条都必须证明用户可见结果；
2. Capability Profile 是每个外部能力成功用例的前置声明；
3. Validator、digest、状态转换和候选过滤下沉为单元/集成测试；
4. E04 覆盖 accepted、denied、外部输入、replay、双 digest、无静默改写和 crash recovery；
5. E09–E13 分别为 Capture、完整 Knowledge Lifecycle、Review、Knowledge Maintenance 和 Scheduled Intelligence 形成 Release 证据；
6. C01–C04 分别证明 Personal Research Analyst、Continuous Knowledge Steward、Personalized Learning Agent 和 Expert Collaboration Agent 的真实组合结果；
7. L01–L06 分别证明 Observation 后重新规划、安全并发、崩溃重建、
   manager-specialists、budget fail-closed 和 evaluator feedback 修订；
8. release gate 从机器声明目录反查 E/C 系列，并在 Phase 1 落地时加入 L 系列；
9. 任一依赖用例缺失、skip、使用 Fake Provider 或不是当前 revision 通过时，对应基础、
   组合或主循环能力声明不得发布；
10. 不用“多个内部对象都存在”、WorkingPlan 数量、ChildAgentRun 数量或测试代码预置
    中间结果代替用户结果反事实。

每个 Phase 必须在同一 revision 修改 owner、Model、调用方、存储、文档和测试；删除旧字段、旧分支和旧用例，不保留 alias、fallback、双写或 deprecated 路径。

## 13. 完成定义

目标设计完成必须同时满足：

1. 文档先定义知识 Agent 原生能力，再定义扩展协议和 E2E；
2. 机器声明目录中的每项原生能力都映射最低 Release E2E，E01–E13 在同一 revision 完整执行且通过；
3. 机器声明目录中的每项强能力发布声明都映射最低组合 E2E，C01–C04 在同一 revision 使用真实依赖执行且通过；
4. 章节 6.8 的每项主循环声明都映射最低 L 系列，L01–L06 在同一 revision 使用真实
   Model/Provider/进程边界执行且通过；
5. 缺失、skip、Fake Provider、内部 Service 直调、预置中间结果或只有专项 suite 的用例不产生能力可信声明；
6. 每个 Release E2E 都声明真实 Capability Profile；
7. 不存在天气、安全审计、合同审查等无 Provider 的成功 E2E；
8. 模型根据当前有效工具和 Agent 自主产生 WorkingPlan 和语义下一步，Runtime 不预判复杂度或组合路径；
9. `AgentTurnDecision` 只有 `FinalMessage | ContinueTurnProposal`，Continue 使用唯一
   `actions` 集合，不存在 singular/plural 双轨或 Plan step 直接执行；
10. WorkingPlan 是 model-owned transient projection，只进入当前 Context 和 append-only
    trace；它不是 chain-of-thought、权限、业务 Definition、执行事实或完成证明；
11. Runtime 不从 description、semantic domain、相似度、ranking、结果数量或字符串规则决定 Research、Capture、Maintenance 或 A2A；
12. 能力之间只交接 owner 提交的 typed ref/result/failure，不存在字段并集式 `CapabilityResult`、raw dict shared context 或字符串 identity；
13. 普通组合留在 InteractionRun 临时循环中，不创建通用 Task、ResultContract、CompositeTask、持久 Plan 或 CompletionReport；
14. 模型不能通过 ResultContractProposal 或 WorkingPlan 创造产品义务；
15. ResearchRun、ChildAgentRun、InteractionRun 和 InvocationJournal 各自拥有独立事实边界；
16. MCP 扩展资源/动作，A2A 扩展开放式专业委托，Runtime 性质不冒充产品能力；
17. Proposal 是候选动作，不是权限、执行事实或完成证明；
18. Admission 不改写 Proposal/WorkingPlan，拒绝时产生 typed feedback；
19. approval、AuthorizationDigest、ExecutionCommandDigest、Journal 和 Receipt 绑定关系可机械验证；
20. replay/recovery 不重新生成或覆盖已冻结 Command，不重复 Provider effect；WorkingPlan
    从 canonical facts 重建且不重置 committed usage；
21. Agent Artifact、Tool Receipt、semantic verification 和产品完成互不冒充；
22. Ask、Research、Review 和 A2A 结果不隐式写长期知识，Artifact/Note/Workspace scope 有唯一 owner；
23. Review feedback、Research limitation 和 Delivery result 只能通过模型或已接受 ProductMode 影响后续语义动作，确定性代码不扩写新 intent；
24. 每个持久对象都能由至少一个用户结果、安全、恢复或长期业务 lifecycle 反事实证明必要；
25. 当前事实文档只在代码和真实 Provider E2E 落地后更新。

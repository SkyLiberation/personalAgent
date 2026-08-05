# personalAgent 当前核心架构

本文记录截至 2026-08-03 已落地的生产架构事实。尚未落地的设计只进入
[future 索引](../future/README.md)，不能反向定义当前架构；产品能力、E2E 和发布可信度的当前事实由
[`phase0-capability-release-baseline.md`](phase0-capability-release-baseline.md) 拥有。
[`core-architecture-e2e-audit.md`](core-architecture-e2e-audit.md) 只保存已删除旧架构的历史诊断
证据，不再描述当前主链。

上一版工程矩阵 E01–E13、C01–C04、L01–L06 共 23/23 passed，archive 为
`data/e2e_traces/20260726T011631.187395Z-20684-4a62da6a`。L01–L06 与 E16–E19 现已改为
不泄漏内部 Tool、Agent、Artifact、verdict 或执行顺序的自然用户场景；当前定向证据见
`phase0-capability-release-baseline.md`。旧完整 archive 不再匹配当前 catalog，当前完整矩阵
和 clean-revision 发布资格都尚未建立。

Conversation governed save 的 pre-change B01 archive 为
`data/e2e_traces/20260728T083321.588087Z-48120-2ce6f484`。B02 semantic baseline
`data/e2e_traces/20260729T031804.415533Z-15972-214cb81c` 证明整条 user message 会把保存/确认
控制语义写成 Claim；修复后 E14 archive
`data/e2e_traces/20260729T033339.065714Z-22692-16415241` 证明 exact-span Command、精确结论
Claim、控制语义反事实、恢复和 replay。它们均来自 dirty worktree，只是定向工程证据，不建立
发布资格。

目标入口改造使用相同自然输入先后执行 baseline 与 target：读取 baseline
`20260803T142413.474927Z-4864-39fedcf5`、删除 baseline
`20260803T142932.564456Z-23720-19ba8517`、Project baseline
`20260803T143007.354551Z-26256-84d0bf1d` 均证明旧 Conversation 缺少相应能力；改造后 L01
`20260803T152242.957743Z-388-d0850c85`、E22
`20260803T152242.957743Z-388-d0850c85`、E23
`20260803T151935.921382Z-27308-be5eadbf` 通过。Research paired baseline
`20260803T143230.864789Z-6460-dbd005fd` 未证明 ResearchRun 对开放调查优于 Conversation 或
Project，因此 ResearchRun 保持 Scheduled Intelligence 边界。以上仍是 dirty revision 的定向证据。

## 0. 框架命题：可信 Agent Runtime

personalAgent 的顶层目标不是让模型“多调用几个 Tool”，也不是把自然语言机械转换成 JSON，
而是建立一套能够长期承载知识、外部能力和真实副作用的可信 Agent Runtime：

> 模型负责开放世界的语义判断；确定性系统负责准入、权限、状态迁移和执行；执行系统产生事实；
> Verifier 判断语义结果；Completion Gate 依据 required result contract 判断用户目标是否关闭。

主链可以压缩为一个稳定协议：

```text
User Goal + Visible Context + Committed Observation
  -> Semantic Model proposes a typed Decision
  -> Admission / Policy accepts or rejects
  -> Gateway / Executor produces an Execution Fact
  -> Verifier assesses evidence-backed outcome
  -> Completion Gate closes or keeps the obligation open
```

这里的 typed JSON 是模型与 Runtime 之间的 wire representation，不是架构本身。object-root、
Pydantic、OpenAI-compatible transport、手写 loop 或 LangGraph 都可以替换；以下权力边界不能
随实现替换而改变：

1. **Proposal 不是权限**：模型可以选择业务能力和参数，不能给自己授权；
2. **Proposal 不是执行事实**：模型声称“已经完成”不能替代 Tool、Command、Journal 或 Receipt；
3. **Admission 只裁决，不创作语义**：它可以拒绝并返回 typed feedback，不能补业务参数、换目标
   或生成替代答案；
4. **Execution、Verification、Completion 分离**：Tool `ok=true`、Agent `completed`、数据库新增
   记录和 Verifier 通过分别只证明各自事实；
5. **一个业务事实只有一个 owner 和写入口**：索引、Graph、Runtime projection 与 View 不成为
   第二写源；
6. **复杂度由生命周期而不是 Agent 术语准入**：固定事务不交给 Planner，短请求不承担 durable
   Project 成本，没有失败 E2E 的新机制不进入主链。

### 0.1 一套目标责任链，按需选择执行语义

普通用户只面对 Conversation 这一目标入口，不需要先判断 Tool、Workflow 或 Project。模型基于
目标、约束和已提交 Observation 提出粗粒度能力；确定性系统再把已准入的能力交给唯一业务 owner。
下面是框架内部的执行语义，不是三种产品模式或三个并列入口：

| 目标约束 | 下一步 owner | 内部执行语义 | 为什么 |
| --- | --- | --- | --- |
| 短、动态、无需跨请求维持交付义务 | 模型逐轮提出下一步 | Conversation Interaction loop | Observation 会改变下一步，但不需要持久化 Plan |
| 拓扑和事务不变量固定 | Application / Domain | 具体 Use Case / 领域 Workflow | 模型不能重排确认、写入、Receipt 或补偿顺序 |
| 路径动态且跨进程、用户轮次或审批边界 | 模型提出 Project 创建参数；Project 内 Planner 提出 Plan | Investigation Project | accepted Plan、ready set、journal 和 Completion obligation 都有生产消费者 |

这些语义共享 Proposal、Admission、Execution Fact 和 Completion 的权力观，但不共享一个 God
Task、God State 或统一 Planner。`Workflow` 只表示具体业务 owner 的稳定事务不变量；它不是
用户可选择的运行模式，也没有全局 Workflow Registry。专用 UI、自动化和管理 API 可以直达同一
Application Use Case，但多个协议入口不能制造第二事实 owner。

### 0.2 现实故障如何支撑框架

| 已观察问题 | 执行证据 | 支撑的框架原则 |
| --- | --- | --- |
| 模糊新请求被旧答案冒充完成 | E01 baseline `20260729T033100.290836Z-35328-02db4988` | 生成文本不等于完成；澄清是显式终态 |
| 整条保存请求把“请保存、先确认”等控制语义写成 Claim | B02 `20260729T031804.415533Z-15972-214cb81c` | 模型语义选择、用户授权和 canonical write 必须分离 |
| exact-span 保存需要确认、恢复、scope 拒绝和 replay | E14 `20260729T033339.065714Z-22692-16415241` | Proposal、Command、Receipt 与知识写入口各自拥有事实 |
| terra 在顶层 union structured schema 上 retry 超时 | Phase 0 Provider probe/E17 记录 | Provider transport 是可替换能力边界，不能污染业务 contract |
| 子 Agent 返回 Artifact 后仍被重复委托，或 child terminal 被误当父完成 | E17/C04/L04 定向 archive | child execution fact 与父级综合、完成分离 |
| live Investigation 有搜索结果却因 repair lineage 不闭合而无法交付报告 | B03 到 IP01 的同输入 archive 链 | Evidence Admission、Plan revision 和 Completion obligation 必须由 durable owner 维护 |
| Workspace 回答并列互斥事实却宣称 supported | B04 `20260731T063040.820774Z-16696-c3646c8a` 到 E20 `20260731T064446.108938Z-8804-52b29d3c` | 回答组装与 answer-level Semantic Verification 必须由不同 owner 负责 |

这些 archive 证明的是对应工作树和输入上的工程事实，不自动建立 clean-revision 发布资格。
框架的可信度来自“问题—owner—最小改动—目标 E2E”链路，而不是来自“对齐优秀 Agent”的类图。

### 0.3 当前实现与框架原则的边界

| 层次 | 当前选择 | 稳定性 |
| --- | --- | --- |
| 框架不变量 | Proposal → Admission → Execution Fact → Verification → Completion | 稳定，改变需 ADR 与产品 E2E |
| 普通用户入口 | Conversation goal entry | 稳定；内部执行语义不暴露为模式选择 |
| 模型协议 | `AgentTurnDecision` object-root envelope | 当前 Provider 约束下的实现，可由同等 contract 替换 |
| Schema/transport | Pydantic + strict JSON Schema 或 JSON Object Adapter | deployment capability，集中在 Model Adapter |
| 编排技术 | 显式 Python loop、领域状态机、worker queue | 可替换，但不能改变 canonical owner |
| 外部能力 | Tool、MCP、A2A Adapter | 可扩展，必须先通过 visibility、Admission、Gateway 与 E2E |

## 1. 架构边界与依赖方向

当前生产代码按以下稳定方向协作：

```text
Interface / Infrastructure
  -> AgentService / AgentRuntime composition root
  -> Application use cases and orchestration
  -> Domain models, state machines and Ports
```

- Interface 负责协议转换、身份解析和输入校验，不决定业务语义；
- `AgentService` 是 Web、CLI、飞书使用的 facade；
- `AgentRuntime` 集中装配 Store、Model、Tool、Agent 和 Application service，不成为业务事实 owner；
- Application 协调模型、Port、Policy 和领域服务；
- 外部 Provider 通过 Adapter 接入，不能创造 intent、授权或完成事实；
- PostgreSQL、Artifact Store、Graph/Retrieval Index 分别保存其契约允许的事实或投影。

核心模型仍区分：

```text
Definition  不可变定义
Command     请求执行一次有界变更
Event       已经发生的事实
Projection  从事实得到的运行视图
View / DTO  读取时组合，不成为新事实 owner
```

同一事实只能有一个 canonical owner 和一个合法写入口。可确定性重建的值默认不持久化，
禁止用 alias、双写、converter 或 fallback 维护新旧事实副本。

包依赖由 `scripts/check_layers.py` 的显式 DAG 检查。2026-07-31 在当前工作树实际执行结果为：

```text
packages=14 edges=53
unknown_packages=none
missing_packages=none
cycles=none
forbidden_edges=0
OK: explicit package DAG satisfied
```

package discovery 只识别真实 Python package；空迁移目录不再制造未知 package。

## 2. 正式入口与 Composition Root

普通对话的正式入口统一为：

- Web：`POST /api/conversation/turn`；
- CLI：`personal-agent entry`；
- 飞书：消息事件进入 `FeishuService`；
- 三者最终都调用 `AgentService.converse()`。

产品能力也保留各自明确的 Application/API 入口。例如 Workspace ingest/ask、Knowledge
Lifecycle、Research subscription/run、Review feedback 和 Artifact 操作不必伪装成一次通用
Conversation Task。固定、稳定的产品流程优先直接调用相应 Use Case。

路径动态且需要跨进程、用户轮次或审批边界维持交付契约的任务，可以由普通 Conversation 的
`start_durable_investigation` 粗粒度能力创建，也可以由已明确知道业务动作的 UI/自动化通过
`POST /api/investigation-projects` 直接创建。两者复用 `InvestigationProjectService.create`；创建
先持久化 immutable definition，再异步入队。查询只读取 projection，不调用模型或推进状态。该能力的
当前事实与发布证据边界由
[`durable-investigation-project-current-state.md`](durable-investigation-project-current-state.md)
记录。

装配关系为：

```text
WebAppContext / CLI / Feishu
  -> AgentService
  -> AgentRuntime
     -> ConversationService
     -> WorkspaceService
     -> KnowledgeLifecycleService
     -> InvestigationProjectService
     -> ResearchService
     -> Review / KnowledgeGap use cases
     -> ToolExecutor / ToolGateway
     -> AgentGateway
     -> Model Ports and persistence adapters
```

Investigation Project 使用 PostgreSQL append-only journal 和现有 worker queue；AgentGateway
的生产 run store 为 PostgreSQL。Conversation 只在用户明确需要跨交互持续、进度查询、暂停或
steering 时创建 Project，并且只持久化 `ProjectReference`，不拥有 Project definition、Plan、
状态或 `WorkingPlanSnapshot`。

`AgentRuntime` 是唯一集中装配点，但 Workspace、Research、Interaction、Tool audit 等事实仍由
各自 Store/Service 拥有；Composition Root 不通过字段镜像成为第二事实源。

## 3. 普通 Interaction 主循环

普通用户对话由 `application/conversation/ConversationService` 拥有。它不是旧
Task/GoalGraph 的轻量包装，也不为直接回答强制创建 Task、Goal、Command、Receipt 或
CompletionReport。

```text
ConversationMessage[]
  -> materialize EffectiveCapabilities
  -> Model returns AgentTurnDecision
     -> FinalMessage
     -> ContinueTurnProposal
        -> actions[]
           -> ToolCallProposal | AgentDelegationProposal
  -> deterministic admission and budget checks
  -> execute accepted actions through Ports/Gateways
  -> ActionObservation | DecisionFeedback
  -> next model turn
  -> FinalMessage
```

### 3.1 决策所有权

- 模型负责开放语义：是否直接回答、是否需要计划、选择哪个语义能力、委托什么 bounded
  sub-goal、如何根据 Observation 修订下一步；
- Runtime 负责 schema、重复 action、预算、并发安全、scope 和能力存在性等机械判断；
- Admission 只能接受或返回 typed `DecisionFeedback`，不得补业务参数、改写 plan 或替换目标；
- Tool/Agent 执行产生 execution fact；模型或领域 Verifier 判断语义结果；领域状态机判断完成。

`AgentTurnDecision` 使用唯一 object-root envelope：

```text
AgentTurnDecision
└─ decision: FinalMessage | ContinueTurnProposal
   └─ actions: ToolCallProposal | AgentDelegationProposal []
```

不存在 `.root` 兼容入口、`action/actions` 双轨、Plan step 直接执行或确定性业务 fallback。

### 3.2 预算、并发与恢复

`LoopBudgetPolicy` 限制 model turns、Tool calls、Agent calls、token 和并发数。预算耗尽返回
明确 limitation/failure，不拼接替代业务答案。

同一 turn 只有全部 action 都可机械证明为安全并发时才使用 bounded thread pool；具有共享
写状态、审批或结果依赖的动作保持串行，并把 Observation 返回下一模型轮。

`InteractionTrace` 保存输入消息、能力 revision、已提交 Observation/Feedback、usage、执行
顺序、并发批次和最终消息。恢复后模型直接读取 committed typed inputs；恢复不会重复已提交
action，也不要求生成一个没有生产调度消费者的中间 Plan。

Conversation 当前额外暴露四个粗粒度 Application capability，而不是领域内部步骤：

- `list_workspace_knowledge`：只读当前 principal/workspace 的 active/conflicted canonical KnowledgeItem 引用；
- `prepare_conversation_knowledge_save`：冻结 user-authored exact span，等待确认；
- `prepare_knowledge_delete`：只能引用上一 Observation 中同 scope 的 KnowledgeItem，调用
  `KnowledgeLifecycleService.prepare_delete`，确认前不删除；
- `start_durable_investigation`：仅用于用户明确要求跨交互持续、查询进度、暂停或 steering 的目标，
  调用 `InvestigationProjectService.create` 并返回 `ProjectReference`。

显式保存时，参数只能引用现有 user
message 索引并逐字复制其中的知识 `text_span`；Admission 机械证明 span 确实存在且来源角色为
user。Runtime 只冻结 exact span 与 source index 并产生一个 `command_digest`，Interaction journal 保存
`awaiting_confirmation/rejected/executed` 和 Receipt。确认入口重新校验 principal、workspace、
digest，执行时仍复用 `WorkspaceService.solidify_conversation`，不开放 `capture_text`，确认后
也不让模型改写 payload。E14 已覆盖 exact span、确认前零写入、prepare 后重启、跨 scope
拒绝、精确结论 Claim、控制语义零写入、Receipt 和成功 replay。提交知识与 journal Receipt
之间的进程终止故障注入仍未覆盖。删除 operation 和 Project 的 canonical 状态不复制到
Interaction journal；journal 分别只保存 delete command ref 和 `ProjectReference`，恢复时回查
原 Application owner。E22 覆盖确认前零删除、scope 隔离、确认与 replay；E23 覆盖从自然目标
创建一个可查询 Project、trace 引用一致且不把创建冒充 Completion。

## 4. Capability、Tool、MCP 与 A2A

### 4.1 EffectiveCapabilities

Conversation 每次运行从实际 Tool registry 和 Agent profiles 构造临时
`EffectiveCapabilities`，并对 canonical JSON 计算 revision。该对象只说明模型当前可以看到
什么，不证明远端健康，也不产生发布可信度。

管理/API 使用的 `RuntimeCapabilityInventory` 从本地 registry、accepted MCP config 和 A2A
assembly 投影。它明确区分 configuration、discovery 和 availability observation，不把
“配置存在”推断为“Provider 当前健康”。

### 4.2 Tool 执行

```text
ToolCallProposal
  -> ToolExecutor registry/schema validation
  -> deterministic admission
  -> ToolExecutor.invoke_interaction
  -> ToolGateway policy / idempotency / audit
  -> typed Tool result
  -> ActionObservation
```

普通低风险、只读、可安全重试的 ToolCall 不为形式统一持久化 Command。需要审批、外部副
作用、不可安全重试或跨恢复边界的调用，必须使用领域 Command、digest、Journal 和 Receipt。

`ToolExecutor` 拥有本地 Tool registry；`ToolGateway` 拥有最终 policy enforcement、调用和审计
事实。Application 只依赖 `InteractionToolPort`，不直接依赖具体 Tool 或 MCP SDK。

### 4.3 MCP

MCP Server 拥有远端 tool name/schema 和协议响应；Host config 拥有本地映射、风险、权限、
data egress、timeout 和 exposure。只有实际 discovery 与 Host mapping 都满足时，MCP Tool 才
进入 registry。

GitHub/Notion MCP 是当前真实 Connector profile。capability missing 时系统返回 typed
unavailable/feedback，不选择“最像”的 Tool，也不生成替代业务结果。

### 4.4 A2A

```text
AgentDelegationProposal
  -> local profile and scope admission
  -> DelegationGrant
  -> AgentGateway submit / poll / cancel / stream
  -> ChildAgentRunRecord + AgentArtifact
  -> ActionObservation
  -> parent model synthesis
```

`AgentGateway` 拥有 child lifecycle 和 Artifact index；Adapter 只转换远端协议。远端
`completed` 不能自动完成父 Interaction，Artifact 也不能直接冒充父级 FinalMessage。当前
GPT Researcher A2A profile 与主工程使用相同 tokeness Provider 配置。

## 5. 原生产品领域与事实 owner

| 产品能力 | Application owner | Canonical fact / 唯一写入口 |
| --- | --- | --- |
| Conversation | `ConversationService` | `InteractionTrace` / Interaction journal |
| Conversation governed save | `ConversationService` + `WorkspaceService` | journal 拥有 save Command/operation/Receipt；Workspace 固化方法仍是唯一知识写入口 |
| Goal-entry knowledge delete | `ConversationService` 调用 `KnowledgeLifecycleService` | lifecycle service/store 拥有 delete Command/status/Receipt；Interaction 只存 command ref |
| Goal-entry durable investigation | `ConversationService` 调用 `InvestigationProjectService` | Project aggregate/store 拥有 definition/Plan/state/Completion；Interaction 只存 ProjectReference |
| Artifact | `ArtifactService` | application-owned ArtifactRef 和 Artifact Store |
| Capture | `CaptureService` + Workspace ingestion | 原始资源、Artifact、Evidence、Claim ingestion transaction |
| Grounded Ask | `WorkspaceService` | Workspace/Evidence 只读；Answer 不隐式写 Claim |
| Knowledge Lifecycle | `KnowledgeLifecycleService` | immutable delete/restore Command、operation status、Receipt |
| Workspace Knowledge | `WorkspaceService` | Artifact、EvidenceBlock/Span、Claim、Relation、KnowledgeItem |
| Review | `ReviewDigestUseCase` / feedback use case | review content、feedback fact、schedule projection 分离 |
| Knowledge Gap | `KnowledgeGapUseCase` | gap analysis result；不成为知识事实写入口 |
| Research | `ResearchService` | ResearchRun、Event、Digest、Delivery/limitation |
| Scheduled Intelligence | Research/Review scheduler | Subscription definition、Run、Delivery、feedback 分离 |

Workspace 的 PostgreSQL Store 是结构化知识事实 owner。Graphiti 和 embedding index 是检索/图
投影，不是事实权威源；投影失败不能覆盖或删除 Workspace canonical facts。生产 Graph Provider
只接受 `graphiti`、`structural` 和 `hybrid`；旧 Microsoft GraphRAG Adapter 因缺少
source/citation binding 已删除，历史 CLI synthesized answer 不能作为检索事实。
大型正文和上传文件由 Artifact Store 持有，运行状态优先保存 ref 而不是复制内容。

Knowledge delete/restore 不使用通用 Planner 猜测目标。Application 根据明确的
user/scope/note identity 创建 immutable Command；一个 `command_digest` 绑定
confirmation、Operation 和 Receipt，错误 digest 或 replay 不重复副作用。只有 Workspace
Item/Claim 的真实迁移产生状态事件，生命周期本身不复制 Event。

## 6. Model Port 与 Provider 边界

Application 只依赖 `StructuredModelClient` / `StreamingModelClient`，不直接依赖 OpenAI SDK。
`infra/structured_model.py` 是唯一 OpenAI-compatible 生成式边界，共享 SDK 调用与响应归一化，
并按 Provider/model capability profile 在 Composition Root 确定性选择：

- `StrictJsonSchemaAdapter`：Provider 原生 strict `json_schema`；
- `JsonObjectStructuredAdapter`：`json_object` + canonical Pydantic schema instruction；
- tool calling/text：Chat Completions 的统一请求和响应提取；
- streaming：typed `StreamChunk`；
- observation：usage、latency、trace 由 decorator 记录；
- retry：SDK 隐式 retry 关闭，`RetryingStructuredModelClient` 是唯一 retry owner；
- repair：typed validation 失败最多请求同一模型完整重写一次，累计全部调用的 latency/token，
  第二次仍无效则 fail closed；
- timeout：connect/read/write/pool timeout 外，再执行完整 Provider 调用的 wall-clock
  deadline；structured SSE 消费也受该 deadline 约束。

所有生成式 Adapter 从 canonical `STRUCTURED_*` 配置解析；`STRUCTURED_OUTPUT_TRANSPORT`
声明 deployment 的结构化输出能力，禁止根据一次异常在运行中切换协议。当前配置为
`deepseek-v4-flash` + `json_object`；embedding 和 transcription 保持独立契约。Provider
transport compatibility 可以改变传输格式，但不得修改 Prompt 语义、Proposal payload 或
typed output contract。

`StructuredModelRequest.context_projection_ref` 必填。边界明确、完整输入即 messages 的调用
使用 content-addressed `sealed-context`；上下文内容变化会改变 digest。模型调用仍经过
governed model client，配置或凭据本身不构成调用授权与成功事实。

## 7. Execution、Verification 与 Completion

系统明确分离：

```text
Execution Fact
  = Tool、Command 或 Agent 实际执行了什么

Semantic Verification
  = Answer/Artifact 是否被可见证据支持

Domain Completion
  = 对应领域 Aggregate 是否满足其 definition 并进入合法终态
```

审查类 Interaction 的语义验证由 `ConversationService` 拥有，模型只保留「这是不是一次审查请求」
的路由判断。判据由 Runtime 经一次独立结构化调用派生，每条 `criterion` 必须携带逐字出现在用户
消息里的 `source_span`（否则丢弃，并留下 `review_criteria_not_grounded`），派生结果冻结进
`InteractionTrace.review_criteria`。`verify_interaction_draft` 的 `exposure` 是
`workflow_activity`，不出现在模型能力清单里；`ToolExecutor.list_interaction_tools()` 按 exposure
过滤而 `invoke_interaction()` 不过滤，所以 Runtime 仍经同一 ToolGateway 调用，`permission_scope`、
超时、限流、审计与预算记账全部保留。Runtime 在终止前无条件验证，并拒绝审查请求上任何非
`answer` 的 disposition；通过后发出的文本直接取自凭据的 `verified_draft`，模型不参与产物传输
（[ADR 0010](../adr/0010-runtime-owned-interaction-verification.md)）。非审查请求完全跳过验证，
普通问答路径不变，也不为形式统一伪造 VerificationReport 或 CompletionReport。

Research、Knowledge Lifecycle、Review 和 Delivery 使用各自的 typed result/receipt/terminal
state。Tool success、Agent completed、数据库新增记录或模型自述均不能单独证明用户目标完成。

## 8. 持久化、恢复与后台执行

当前不存在覆盖所有请求的通用 Task/GoalGraph/RunCheckpoint 主链。持久化边界按事实类型分开：

| 边界 | 当前实现 | 恢复语义 |
| --- | --- | --- |
| 普通 Interaction | `FileInteractionJournal` | 从 committed inputs/usage 重建 transient context |
| Workspace/Knowledge | `PostgresWorkspaceStore` | 从 canonical Artifact/Evidence/Claim/Event 恢复 |
| Delete/Restore | `PostgresKnowledgeLifecycleStore` | immutable Command/Event/Receipt，digest replay |
| Research | `PostgresResearchStore` + worker queue | ResearchRun/Subscription/Delivery 生命周期 |
| Tool governance | `PostgresToolGovernanceStore` | policy decision、idempotency 和 audit |
| Child Agent | `AgentGateway` run store + trace | child status/event/Artifact 与父结果分离 |
| Background work | `PostgresWorkerQueueStore` | retry/dead/reconcile，不重新创造业务参数 |

`ProcedureRuntime` 只服务具有稳定事务不变量的流程；它不是普通 Interaction 的 Planner，也不
是所有业务 lifecycle 的父 Aggregate。仓库中仍存在部分 Task/Control contract 供受限
Procedure 或迁移代码使用，但它们不是正式 Conversation 入口，不应恢复已删除的通用旧主链。

## 9. Observability 与发布证据

观测层记录 trace、usage、latency、provider、action order、receipt、verification 和错误分类，
不改变业务行为。凭据和不必要的完整敏感内容不得进入 trace。

E2E 分类的唯一 owner 是 `evals/e2e_quality/evidence_catalog.py`：

- E01–E05、E08–E14、E20、IP01：应用能力；
- L01–L06：自然复杂主循环、恢复、fail-closed 和 receipt-reference semantic revision；
- E16–E19、E21：真实外部 Provider/runtime profile，属于 diagnostic。

E06/E07 重复 profile、C01–C04 拼接独立 Use Case、LT09 使用常量代替 paired baseline，均已退出
当前 catalog；B03 保留为历史 archive，不再与 IP01 一起对当前实现断言相反结果。

完整矩阵必须从真实 HTTP 入口进入独立 Web 进程，使用真实模型、PostgreSQL 和场景需要的
真实 Provider，并同时断言用户结果和关键反事实。`release_gate.py` 只接受 catalog、clean
matching revision、passed summary、trace envelope 和 checksum 的交集。

上一完整矩阵与当前定向证据：

```text
previous full matrix = 23 passed, 0 failed, 0 skipped
previous archive = 20260726T011631.187395Z-20684-4a62da6a
natural L01-L05 batch = passed
corrected natural L06 = passed
natural E17/E19 plus L04 = passed
answer-free-prompt E16/E18 = passed
targeted archives = 20260727T163802.147366Z-12512-71873e6b,
                    20260727T164815.081968Z-14456-e1196ad4,
                    20260727T162913.553817Z-9428-c723ad92,
                    20260727T165211.554901Z-17344-3e4bc060
current complete matrix = not rerun
release eligibility = not established (dirty revision)
```

## 10. 当前生产主链

### 10.1 普通对话

```text
Web / CLI / Feishu
  -> AgentService.converse
  -> AgentRuntime.converse
  -> ConversationService.respond
  -> AgentTurnDecision
  -> ToolExecutor or AgentGateway
  -> Observation / Feedback
  -> FinalMessage
```

### 10.2 固定产品流程

```text
Product API / CLI
  -> AgentService facade
  -> explicit Application use case
  -> Domain state transition / Port
  -> persistence adapter
  -> typed user result
```

固定 Capture、Ask、Knowledge Lifecycle、Review、Research 和 Scheduled Intelligence 不为
“更 Agentic”而强制进入 Planner。只有语义下一步无法预定义时才回到模型 Interaction loop。

### 10.3 Conversation 内确认后保存

```text
POST /api/conversation/turn
  -> ToolCallProposal(prepare_conversation_knowledge_save)
  -> immutable Command + awaiting_confirmation
  -> Interaction journal
POST /api/conversation/runs/{run}/knowledge-save-decision
  -> principal/workspace/digest validation
  -> WorkspaceService.solidify_conversation
  -> Receipt / replay same Receipt
```

## 11. 当前架构不变量

- 普通请求不强制创建 Task、GoalGraph、Command、Receipt 或 CompletionReport；
- 模型拥有开放语义和下一步 Proposal，Runtime 不从字符串或相似度猜业务下一步；
- Proposal 不是权限、执行事实或完成证明；
- Admission 只接受/拒绝，不静默修复 Proposal；
- 普通 Conversation 不创建强制 Plan；durable Plan 只属于显式 Investigation Project；
- 普通只读 ToolCall 与 governed side effect 使用不同执行边界；
- Tool 和 Agent 必须经过对应 Gateway，Adapter 不决定授权；
- Agent Artifact、Tool Receipt、Semantic Verification 和 Domain Completion 互不冒充；
- Ask 不隐式保存模型回答，长期知识只有明确 ingestion/write path；
- Conversation 保存只冻结已选 user message；确认前、reject 和 scope denied 均不写知识；
- 远程能力没有实际 discovery/availability 时 fail closed；
- replay 不重新生成或覆盖冻结 Command，不重复副作用；
- retrieval index 和 graph projection 不是知识事实 owner；
- Interface、Application、Domain 与 Adapter 的依赖不得反向或循环；
- release 可信度只能由 clean matching E2E archive 派生。

## 12. 主要代码入口

| 关注点 | 当前路径 |
| --- | --- |
| Composition Root | `orchestration/runtime.py`、`orchestration/service.py` |
| Conversation models / loop | `application/conversation/models.py`、`application/conversation/service.py` |
| Conversation Ports | `application/conversation/ports.py`、`capabilities/contracts/interaction.py` |
| Web conversation entry | `adapters/web/routes/conversation.py` |
| Workspace / Grounded Ask | `application/workspace/`、`adapters/web/routes/workspace.py` |
| Knowledge delete/restore | `application/knowledge_lifecycle/`、`adapters/web/routes/notes.py` |
| Research / Scheduled Intelligence | `application/research/`、`adapters/web/routes/research.py` |
| Review / Knowledge Gap | `application/review/`、`application/insight/` |
| Tool registry / execution | `governance/registry.py`、`governance/gateway.py` |
| Agent lifecycle / A2A | `agents/gateway.py`、`agents/gpt_researcher_a2a.py` |
| Capability inventory / resolution | `orchestration/capability_inventory.py`、`capabilities/` |
| Model Port / Adapter | `capabilities/contracts/model.py`、`infra/structured_model.py` |
| Persistence adapters | `infra/storage/` |
| E2E catalog / gate | `evals/e2e_quality/evidence_catalog.py`、`evals/e2e_quality/release_gate.py` |
| Architecture DAG gate | `scripts/check_layers.py`、`.github/workflows/architecture.yml` |

## 13. 已移除的旧主链

以下对象和入口不再属于当前正式架构：

- `TaskAnalyzer` / `TaskAnalysisAdmission`；
- `GoalGraphCompiler` 统一任务编译；
- 普通请求强制 `TaskContract + TaskRuntimeProjection`；
- `CoordinationMode` / `AdaptivePlanner`；
- `ExecutiveController` / `DecisionValidator` 通用控制链；
- `orchestration_graph.py` 和旧 orchestration nodes；
- `FinalAnswerProposal` / 通用 CompletionReport；
- `action/actions`、旧 API 或 converter 兼容双轨。

历史 contract 文件仍存在不代表这些链路可从正式入口到达。需要 durable execution 的新能力
应首先使用具体领域 Aggregate/Command；不得为了复用残余类型恢复旧通用主链。

## 14. 未闭合风险

1. 旧 23/23 archive 不匹配新版自然 E2E；提交后必须在 clean revision 重跑当前完整矩阵，才能
   建立发布资格；
2. 历史 workflow/topic 与评测归档仍会提及已删除 Task/GoalGraph/LangGraph 或 MS GraphRAG；
   它们必须保持历史状态标记，不能作为当前架构或发布依据；
3. `conversation_id`、`interaction_run_ref` 等部分 Interface/Application identity 仍以受格式
   约束的字符串传递，尚未全部收敛为 Value Object；
4. GPT Researcher PDF 中文字体视觉质量尚未形成自动化 E2E；
5. 仓库中仍有部分旧 Task/Control contract 供 Procedure 等受限消费者使用，需要按实际调用方
   继续删除或重新
   标明受限用途，避免再次被误认为生产主链。

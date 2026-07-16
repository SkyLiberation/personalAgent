# personalAgent 当前核心架构

本文是当前工程 Agent 主链的事实源。阅读顺序是：先认识模块及其边界，再理解模块承载的业务设计，最后通过完整任务观察模块如何协作。

`docs/future` 中已经落地的文档只保留为历史决策记录；尚未闭合的本地并行与运行中语义 Steering 见 [并行 Join 与语义 Steering 后续设计](../future/parallel-steering-runtime-design.md)。

## 1. 系统定位与模块地图

personalAgent 是 Goal-owned Agent runtime，不是按 `ask / capture / research` 选择固定 Workflow 的请求路由器。

用户负责描述期望结果，系统把结果固化成 Goal；Planner 和 Executive 选择短期路径；Capability Resolution 决定当前环境中谁能执行；Verifier 独占完成判断。

### 1.1 核心模块

| 模块 | 主要职责 | 核心产物 |
| --- | --- | --- |
| TaskAnalyzer | 理解用户目标和资源语义 | `TaskAnalysis` |
| GoalGraphCompiler | 把语义提案编译成可信任务契约 | `GoalCompilation` |
| Task/Goal Aggregate | 保存任务定义、运行状态和事件投影 | `TaskContract`、`TaskRuntimeProjection` |
| PlanningMode | 判断当前任务需要何种策略成本 | `PlanningModeAssessment` |
| Adaptive Planning | 维护短 horizon 策略 | `PlanDefinition`、`PlanRuntimeProjection` |
| Executive Control | 每轮提出一个有界决策 | `ControlDecision`、`BoundedAction` |
| Resource/Capability | 将业务资源需求绑定到可执行能力 | `CapabilityResolutionDecision` |
| Governed Procedure | 执行带事务不变量的操作 | `ProcedureOutcome`、`MutationReceipt` |
| Invocation Runtime | 承载一次实际执行及 attempt 状态 | `ExecutableInvocation`、`InvocationAttemptState` |
| Context Gateway | 为不同模型调用投影最小可信上下文 | `ContextProjection` |
| Observation/Verification | 将执行结果转成进展和完成判断 | `Observation`、`VerificationReport` |
| Orchestration/Checkpoint | 组织节点、恢复现场和 interrupt/resume | `RunCheckpoint` |
| Research/A2A | 提供长时研究与 child Agent 能力 | 独立 Definition/Projection/Event |

### 1.2 依赖方向

```text
EntryInput
  -> TaskAnalyzer
  -> GoalGraphCompiler
  -> TaskContract + TaskRuntimeProjection
  -> PlanningMode / AdaptivePlanner / Executive
  -> Capability Resolution or Procedure
  -> ExecutableInvocation
  -> Observation
  -> GoalVerifier / PlanMonitor
  -> CompletionVerifier
```

这张图只表达依赖方向，不表示固定 Workflow。Reactive 任务可以不创建 Plan；Mutation 可以进入 Procedure；执行产生的新 Observation 可以触发 retry、patch、replacement 或 clarification。

### 1.3 统一建模规则

所有核心模块使用同一组 Model 语义：

```text
Definition  不可变业务契约
Command     一次有界变更请求
Event       已经发生的事实
Projection  由事实得到的可恢复当前状态
View        读取时组合多个 owner，不保存新事实
```

全局约束是：同一事实只有一个 owner；模型只能提案；权限只能缩小；Action 成功不等于 Goal 完成；可推导值不作为第二份可写状态。

## 2. TaskAnalyzer 模块

### 2.1 模块定位

`TaskAnalyzer` 位于自然语言入口和正式任务契约之间，负责理解用户表达的结果语义。它不生成执行步骤，也不选择 Tool、MCP server、Agent provider 或 Procedure。

实现位置：`planning/task_analyzer.py`。

### 2.2 输入与输出

输入是 `EntryInput` 中的用户文本及允许的分析上下文；输出是 provider-neutral `TaskAnalysis`：

```text
TaskAnalysis
├─ user_goal
├─ goals[]
│  ├─ goal_id / description / result_contract
│  ├─ resource_hints[]
│  ├─ success_criteria[]
│  └─ evidence_requirement
├─ relations[]
├─ requires_clarification
└─ rejection
```

Analyzer 输出的 `ResourceHint` 表达语义判断，例如资源 domain、type、locator、operation、freshness、provider binding 和 origin。

### 2.3 业务设计

Analyzer 只拥有“理解权”，不拥有“事实确认权”。LLM 输出可能重复 Goal ID、引用不存在的依赖、遗漏成功标准或错误识别副作用，因此 `TaskAnalysis` 是 semantic proposal，不是可执行状态。

旧 Router、`goal_kind` 动作表和固定 Workflow 选择已删除。原因是同一句请求可能同时包含 response、artifact 和 external-state 结果，路由标签无法表达多个独立验收目标及其依赖。

## 3. GoalGraphCompiler 模块

### 3.1 模块定位

`GoalGraphCompiler` 是概率性语义理解与确定性运行时之间的信任边界。它把 `TaskAnalysis` 编译成满足身份、依赖、授权、证据和验证不变量的初始任务契约。

实现位置：`planning/goal_graph.py`。

### 3.2 输入与输出

```text
TaskAnalysis + entry_text
        ↓
GoalCompilation
├─ TaskContract
├─ TaskRuntimeProjection
└─ ContextInventory
```

Compiler 不选择 Planning mode，不生成 Plan，不选择 Capability 或 Procedure，也不负责运行中的状态迁移。

### 3.3 编译职责

#### 身份和拓扑合法化

Compiler 验证 Goal ID 唯一、relation 引用存在、关系不重复、blocking dependency 无环。`ordering_preference` 不阻塞执行；`consumes_output` 和 `requires_completion` 会成为执行门禁。

该步骤保护 Goal 的跨阶段关联：PlanStep、Action、Observation、ProcedureInvocation 和 Verification 都通过 `goal_id` 归属结果。悬空或循环依赖会让 Goal 永久 pending，因此不能进入正式契约。

#### 事实归属固化

每个 Goal 的资源、criterion 和前置依赖写入对应 `GoalDefinition`：

```text
TaskContract
├─ shared_resources
└─ GoalGraphDefinition
   └─ GoalDefinition
      ├─ resources
      ├─ criteria
      └─ dependencies
```

`ResourceRequirement` 不保存 `goal_id`。归属由 `TaskContract.shared_resources` 或 `GoalDefinition.resources` 的嵌套位置表达，避免叶子对象 identity 与外层 Goal identity 冲突。

#### 治理要求派生

Compiler 根据 canonical Mutation taxonomy 识别 `create / update / delete / ingest / repair`，生成 typed `MutationIntent.operations`，把 Task 标记为非只读，并为 Mutation Goal 增加 confirmation 与 `MutationReceipt` 标准。

MutationIntent 只声明任务可能需要写，不表示批准执行。实际写入仍必须经过 Procedure、精确目标、confirmation、commit-time policy 和 receipt。

#### 完成契约生成

用户显式 criteria 标记为 `user_explicit`；缺失时由 Compiler 生成 `contract_derived` criterion。搜索、验证或显式 evidence requirement 生成 evidence policy。

运行输出契约按风险确定：

```text
Mutation            -> MutationReceipt
Evidence required   -> VerifiedAnswer
Ordinary result     -> Answer
```

该设计保证 Planner、Executive 和 Verifier 在执行前就共享同一验收条件，不能根据已经获得的结果降低完成标准。

#### 初始 Definition 和 Runtime 建立

Compiler 创建 revision 为 `1` 的 `TaskContract / GoalGraphDefinition`，并创建对应 `TaskRuntimeProjection`。无 blocking dependency 的 Goal 初始化为 `active`；存在阻塞依赖的 Goal 初始化为 `pending`；需要证据的 Goal带有初始 evidence gap。

Revision 表示定义版本，不表示 Goal 数量。运行中合法 decomposition 会创建新的 Task/GoalGraph revision，旧 projection 因 revision 不匹配而不能参与决策。

### 3.4 模块不变量

- Definition Goal 集合与 runtime `goal_states` 必须完全一致；
- Goal 不能依赖自己，blocking graph 必须无环；
- Definition 树中的 resource、criterion、constraint、dependency 均不可原地修改；
- 未知 Goal 的资源读取必须 fail closed；
- Compiler 不得发明默认业务资源或具体执行能力。

## 4. Task/Goal Aggregate 模块

### 4.1 模块定位

Task/Goal Aggregate 是整个运行时的业务核心，负责区分“用户要求什么”和“当前完成到哪里”。

实现位置：`kernel/contracts/agentic.py`、`planning/ledger.py`。

### 4.2 Definition 所有权

```text
TaskContract
├─ task identity / revision
├─ user_goal / result_contract / constraints
├─ shared_resources
├─ evidence_requirements / mutation_intent
└─ GoalGraphDefinition
   └─ GoalDefinition[]
```

Goal description、resource、criterion、dependency 和 output contract 只存在于 `GoalDefinition`。Task 级聚合属性如全部 resources、requested operations 和 success criteria 通过只读 property 计算，不持久化第二份列表。

`task.resources_for_goal(goal_id)` 是有效资源的唯一读取入口，返回 Task shared resources 与 Goal local resources；未知 Goal 抛出错误。

### 4.3 Runtime 所有权

```text
TaskRuntimeProjection
├─ task/task-graph revision
├─ lifecycle / event cursor
├─ active_skill_ids
└─ goal_states{goal_id -> GoalRuntimeState}
```

`GoalRuntimeState` 只保存 status、attempt、evidence gap、coverage、verification 和 replan reason，不复制 Definition 字段。

`TaskRuntimeProjector` 根据 typed `ExecutionEvent` 更新 projection，并校验 task identity、严格 event sequence 和合法 Goal 状态迁移。

### 4.4 读取模型

`materialize_goals(task, runtime)` 校验 task identity、task revision 和 Definition/Runtime Goal 集合后，返回 `MaterializedGoalView`。Planner、Executive、Procedure applicability 和 Verifier 通过这一入口同时读取 definition 与 runtime，不自行 join 两份状态。

### 4.5 业务设计

Definition/Runtime 分离使用户目标在运行中保持稳定，而 attempt、verification 和 status 可以频繁变化。Revision fencing 防止新定义配旧状态；Materialized View 解决组合读取，但不成为第三个事实 owner。

## 5. PlanningMode 模块

### 5.1 模块定位

PlanningMode 决定当前任务值得支付多少策略成本，而不是决定执行哪种业务 Workflow。

实现位置：`planning/adaptive.py` 中的 `PlanningFactProjector`、`PlanningModePolicy`。

### 5.2 输入与输出

`PlanningFactProjector` 从 TaskContract、Goal runtime、依赖、证据、Mutation、mandatory Procedure 和 provider binding 投影 `PlanningFacts`。`PlanningModePolicy` 输出：

| Mode | 适用状态 |
| --- | --- |
| `reactive` | 一个有界动作可能直接推进 |
| `deliberative` | 多 Goal、依赖、证据或不确定路径需要短期协调 |
| `procedural` | 稳定事务不变量覆盖当前开放 Goal |

### 5.3 业务设计

简单任务强制规划会增加模型调用、延迟和错误面；复杂任务完全不规划会失去依赖与证据协调。因此明确情况由确定性 facts 处理，只有灰区才调用受预算限制的语义 assessor。

模型不可用时不回退到关键词动作表，因为关键词不能维护资源 scope、Goal dependency 和 Mutation authority。

## 6. Adaptive Planning 模块

### 6.1 模块定位

Adaptive Planning 为 deliberative 任务维护短 horizon、provider-neutral 策略。它不拥有用户 Goal，不选择具体 Tool/Provider，也不决定物理并发。

实现位置：`planning/adaptive.py`。

### 6.2 核心模型

```text
PlanDefinition
  immutable steps / dependencies / strategy / planning snapshot

PlanRuntimeProjection
  step statuses / replan signatures / event cursor

PlanEvent
  proposed / selected / running / observed / satisfied / invalidated ...
```

`PlanStep` 声明 Goal、criterion、semantic objective、CapabilityRequirement 或 Procedure、observation contract、failure class 和 replan policy。

### 6.3 子模块

- `AdaptivePlanner`：创建短 horizon `PlanDefinition`；
- `PlanRuntimeProjector`：从 PlanEvent 重建 step 状态；
- `FrontierSelector`：选择语义 ready set；
- `PlanValidator`：校验依赖、revision、权限和 provider-neutral 约束；
- `PlanMonitor`：根据 Observation 决定 keep、retry、patch 或 replacement。

### 6.4 业务设计

Plan 是可替换策略，不是任务真相。Definition、Projection 和 event log 分离，避免 step status 与历史事实不一致。Patch 使用 task、goal graph、plan revision 和 event cursor 做 compare-and-set，只能修改未启动或已失效步骤。

短 horizon 用尽但 Goal 仍开放时创建 replacement definition，旧决策历史留在 append-only event stream。`FrontierSelector` 只负责语义 ready，Scheduler 独占 dispatch 与物理并发。当前生产 profile 的 `max_frontier_width=1`，不宣称本地多 Action 已并行。

## 7. Executive Control 模块

### 7.1 模块定位

Executive 是在线控制器，每轮根据当前事实提出一次有界变化。它不写 Task/Plan projection，不直接调用 Provider，也不拥有 Task 完成权。

实现位置：`planning/executive.py`、`planning/decision_validator.py`。

### 7.2 输入与输出

Executive 读取 `MaterializedGoalView`、ControlState、Plan frontier、Observation、budget 和 Procedure candidates，只能输出 typed decision：

```text
clarify / activate_skill / execute_meta_capability / delegate
invoke_procedure / request_confirmation / finish / stop
```

Reactive 模式可以为 ready Goal 构造 `BoundedAction`；Deliberative 模式只能消费已验证 frontier。

### 7.3 DecisionValidator

`DecisionValidator` 校验：

- decision 的 Goal ownership；
- blocking dependency 和 terminal status；
- provider/model/tool budget；
- mandatory Procedure；
- MutationIntent、write set 和 confirmation；
- delegation scope；
- Action operation 是否超出 Task contract。

### 7.4 业务设计

长链模型计划会同时放大环境过期、语义错误和权限错误。逐轮有界决策让每次变化都基于最新 Observation，并在执行前经过确定性 validator。Terminal Goal 不得获得新 Action；`finish` 只是 CompletionVerifier 的提案。

## 8. Resource/Capability 模块

### 8.1 模块定位

该模块把 Task/Goal 的业务资源需求转换为当前环境可执行的 Capability，并确保选择过程不扩大授权。

实现位置：`kernel/contracts/resource.py`、`kernel/contracts/capability.py`、`planning/capability_resolver.py`、`planning/capability_validation.py`。

### 8.2 三个阶段模型

```text
ResourceRequirement    Task/Goal 需要操作什么资源
CapabilityRequirement  当前 Action 需要什么执行能力
Capability             Provider 实际提供什么能力
```

三个 Model 语义不同，不能合并；它们共享以下值对象和 canonical matcher：

```text
ResourceSelector       domains / resource types / locator
OperationScope         operations / side-effect class
ProviderConstraint     provider / freshness / trust
```

### 8.3 Scope 传播

ResourceRequirement 随 GoalDefinition 传递；进入后续阶段时由外层 aggregate 携带 identity：

```text
GoalDefinition(goal_id)
└─ ResourceRequirement[]
      ↓
PlanStep(goal_id)
└─ CapabilityRequirement
      ↓
BoundedAction(goal_id)
      ↓
CapabilityResolutionRequest(task_id, goal_id, action_id)
```

叶子 requirement 不重复 `goal_id`，避免内外 identity 冲突。

### 8.4 Capability Resolution

Resolver 对 registry 执行 hard eligibility、resource match、operation coverage、policy、provider binding 和 outcome-aware ranking。Resolution contracts 分为：

```text
CapabilityResolutionRequest   immutable scope
ResolutionRunProjection       lifecycle / cursor / failure
CapabilityResolutionDecision  selected/denied / coverage / constraints
ResolutionEvent               audit facts
```

### 8.5 业务设计

Planner 不选择 Provider，因为凭证、trust、data egress 和可用性属于运行环境。Capability 支持写不代表 Action 获得写权限；实际 grant 只能是 request 与 capability operation 的允许交集。

Mutation taxonomy 只有 `resource.py` 一个 owner，Planner、DecisionValidator、Resolver 和 ResolutionValidator 共用，防止同一 operation 在不同阶段获得不同风险解释。

## 9. Governed Procedure 模块

### 9.1 模块定位

Procedure 承载拓扑和事务不变量稳定的业务操作，例如知识写入、删除、知识整理和研究订阅创建。

实现位置：`kernel/contracts/procedure.py`、`planning/procedures.py`。

### 9.2 核心模型

```text
ProcedureDefinition      固定拓扑和不变量
ProcedureInvocation      本次调用及 ProcedureRef
ProcedureRunProjection   当前节点和运行状态
ProcedureEvent           已发生事实
ProcedureOutcome         终态业务结果
```

`ProcedureApplicabilityResolver` 根据当前 Goal 的有效 resource domain/type/operation 生成 candidates；`ProcedureMaterializer` 把选中的 definition 和 invocation 物化为 typed node invocation；projector 从 events 更新 run projection。

### 9.3 业务设计

Mutation 的精确目标、确认、幂等、receipt 和恢复位置不能由开放式 Planner 临时拼接。Planner 只能把 Procedure 当作原子 step，不能展开、跳过或替换内部门禁。

正式 Mutation 路径：

```text
read-only proposal
  -> evidence
  -> mandatory Procedure
  -> exact target
  -> confirmation
  -> commit-time policy
  -> idempotent mutation
  -> MutationReceipt
  -> GoalVerifier
```

## 10. Invocation Runtime 模块

### 10.1 模块定位

Invocation Runtime 是所有实际执行方式的统一边界，负责表达“本次执行什么”和“这次执行到什么状态”。

实现位置：`kernel/contracts/execution.py`、`orchestration/orchestration_nodes/_steps.py`。

### 10.2 核心模型

```text
ExecutableInvocation
└─ tool / react / agent / procedure node / delegated subtask payload

InvocationAttemptState
└─ status / retry / failure / input-output artifact refs
```

Checkpoint 使用 `InvocationBatchState` 保存 canonical invocation collection、cursor、result refs 和 retry counts。

### 10.3 执行边界

- Tool 和 MCP Tool 进入 `ToolGateway`；
- graph-native retriever 在受控 executor 中执行；
- ReAct 只能使用 ResolutionDecision 允许的 tool set；
- A2A 进入 `AgentGateway` 的 submit/poll lifecycle；
- Procedure node 保留 `ProcedureNodeInvocation`，不复制完整 definition。

### 10.4 业务设计

PlanStep、Procedure node 和 attempt 状态不能互相镜像，否则计划修改后仍可能执行旧 step。当前已删除 `ExecutionStep / StepRunState` 镜像，Tool、ReAct、Agent 和 Procedure 统一进入 attempt lifecycle。

ToolGateway 统一执行 schema、policy、idempotency、timeout、HITL 和 audit。Provider 返回成功只结束 attempt，不自动完成 Goal。

## 11. Context Gateway 模块

### 11.1 模块定位

Context Gateway 是所有核心模型调用的输入边界，负责按 purpose、budget、trust 和 admission 选择上下文。

实现位置：`context/projection.py`、`context/gateway.py`。

### 11.2 核心模型

```text
ContextInventory.items      canonical content inventory
        ↓ ContextManager.project
ContextProjection           selected ids / exclusions / snapshot
        ↓ ContextProjectionMaterializer
ModelContextGateway         temporary model payload
```

`ContextProjection` 通过 `RuntimeSnapshotRef` 绑定 Task、GoalGraph、Plan、execution 和 artifact 版本，以 typed exclusion 记录未选择原因。

### 11.3 业务设计

Planner、Executive 和 Verifier需要的信息不同，Tool/provider 输出又不能自动成为 instruction。把整个 checkpoint 拼进 prompt 会扩大数据暴露并产生第二份业务状态。

因此 materialized payload 只存在于一次模型调用，不写入 RunCheckpoint。Runtime/trusted 且 admitted 的 item 才能成为 instruction；工具输出保持 untrusted content。Active skill 只属于 TaskRuntimeProjection。

## 12. Observation、Monitor 与 Verification 模块

### 12.1 模块定位

该模块负责把一次执行结果转换成可引用事实、计划影响和 Goal 完成判断。

实现位置：`planning/verification.py`、`planning/adaptive.py` 中的 `PlanMonitor`，以及 orchestration executive nodes。

### 12.2 三层结果语义

```text
InvocationAttemptState   技术执行是否结束
Observation              执行后获得了什么事实
VerificationReport       事实是否满足 Goal criterion
```

`GoalVerifier` 先执行确定性 evidence、source count、receipt 和 approval 下限，再允许有预算的 semantic verifier 处理开放语义。

`PlanMonitor` 根据 revision、horizon、capability gap、verification gap 和 technical failure 决定 keep、retry、patch 或 replacement；只有未分类 Observation 进入 bounded semantic fallback。

`CompletionVerifier` 检查全部 required Goal、criterion、approval 和 CompletionClaim，独占 Task lifecycle 的 completed 转换。

### 12.3 业务设计

Action success 与 Goal success 分离，避免 Tool 返回 `ok=true` 就完成业务结果。确定性门禁先于语义判断，保证模型不能降低 receipt、approval 或 evidence 下限。Replan signature、patch quota 和 model-call budget 防止策略抖动。

## 13. Orchestration、Checkpoint 与 Persistence 模块

### 13.1 模块定位

Orchestration 使用 LangGraph 组织节点、interrupt/resume、checkpoint 和恢复；它协调领域模块，但不成为所有业务事实的 owner。

实现位置：`orchestration/orchestration_graph.py`、`orchestration/orchestration_models.py`、`orchestration/entry_orchestrator.py`。

### 13.2 RunCheckpoint

`RunCheckpoint` 保存恢复当前执行现场所需的 Task contract/runtime、Plan definition/runtime、control、invocation batch、procedure projection、interaction、presentation refs 和 cursors。

React、invocation batch 和 tool tracking 已使用独立 substate；planning/control 的进一步 owner substate 收敛仍属于当前边界。

以下内容为派生值，不是可写 checkpoint 字段：

- `answer_completed`、`execution_trace`；
- single `current_action`、single `resolved_action_spec`；
- selected plan step ids；
- top-level procedure id/version；
- materialized model context。

Pending confirmation 使用 typed `InteractionRequest`，control route 使用 `ControlPhase`。

### 13.3 三层持久化

```text
RunCheckpoint
  当前可恢复现场

Task/Plan/Procedure/Resolution Event
  append-only 因果和审计

PostgreSQL artifact/replay/run repository
  大对象、长期结果、调试与 replay 引用
```

### 13.4 业务设计

Checkpoint 的生命周期、事件审计和大对象存储需求不同，不能混为一个 Model。Projection 保存当前状态和 cursor，不嵌入完整 event log；artifact 通过引用进入 checkpoint，避免状态无限膨胀。

## 14. Research 与 A2A 模块

### 14.1 Research

Research 是长时、证据驱动的领域能力，不是顶层路由。实现位置：`kernel/contracts/research.py`、`application/research`。

```text
ResearchSubscriptionSpec + SubscriptionCursor
ResearchRunDefinition + ResearchRunProjection
ResearchDecisionIntent + ResearchDecisionOutcome
CanonicalResearchEvent + EventAssessment
ResearchLimits + ResearchUsage
```

静态 topic、窗口、policy 和 limits 与动态计数、timing、评分、decision history 分离，支持定时运行、恢复和审计。

### 14.2 A2A

A2A 是独立 Agent 执行边界。实现位置：`kernel/contracts/agent.py`、`agents/gateway.py`。

```text
ChildAgentRunDefinition
ChildAgentRunProjection
ChildAgentArtifactIndex
ChildAgentRunEvent
ChildAgentRunOutcome
```

Child run 使用 submit/poll/cancel lifecycle，不伪装成 ToolGateway Tool。Child artifact 默认不可信，必须返回父 Goal verification；projection 不内嵌 task、context、artifact 或 event log。

### 14.3 业务设计

Research 和 A2A 都是长生命周期 aggregate，Definition/Projection/Event 混装会让恢复状态与审计历史冲突。因此它们遵循与 Task、Plan、Procedure 相同的所有权规则。

## 15. 跨模块执行示例

用户请求：

> 保存这段资料，然后根据资料回答问题。

### Task 形成

`TaskAnalyzer` 提出 Goal A `external_state`、Goal B `response`，以及 B consumes A。`GoalGraphCompiler` 校验图，固化 A 的 ingest resource 和 MutationReceipt criterion、B 的 evidence policy，初始化 A active、B pending。

这一阶段只确定用户结果、资源 scope、依赖和完成标准，不决定执行工具。

### 策略形成

`PlanningModePolicy` 根据 Mutation 和依赖选择 procedural/deliberative。`ProcedureApplicabilityResolver` 根据 A 的 domain/type/operation 找到 mandatory `knowledge_ingest`。需要短期协调时，AdaptivePlanner 创建 provider-neutral PlanDefinition。

这一阶段只决定策略形态，不授予具体 Provider 权限。

### 有界行动

`Executive` 只能推进 A，`DecisionValidator` 阻止绕过 Procedure 或提前执行 B。Procedure 产生 read-only proposal、精确目标、confirmation、commit 和 MutationReceipt。

这一阶段每次只批准一项有界变化，MutationIntent 本身不等于写入授权。

### 观察与验证

GoalVerifier 使用 receipt 验证 A；Task runtime event 释放 B。Executive 为 B 提出 search/read Action，Capability Resolution 在 local/MCP/A2A 中选择当前允许的能力。执行结果先形成 Observation，再按 evidence policy 验证 B。

工具成功但证据不足时，PlanMonitor 继续探索或 patch，不完成 Goal。

### Task 完成

CompletionVerifier 检查 A、B、全部 required criterion、receipt、approval 和 CompletionClaim，最后更新 Task lifecycle。

这条主链中没有任何单一模块拥有完整权力：Analyzer 不能执行，Planner 不能授权，Resolver 不能扩大 scope，Tool 不能宣布 Goal 完成，Executive 不能绕过 CompletionVerifier。

## 16. 当前边界

以下能力未作为当前事实宣称：

- 本地多个 Action 的真实 worker 并发与 all/any/quorum join；
- 用户运行中修改 `TaskContract / GoalGraphDefinition` 的 semantic steering API；
- Analyzer 自动识别并提升多个 Goal 的公共资源到 `shared_resources`；
- 所有 adapter/provider payload 完成强类型替换，部分边界仍使用 raw dict；
- outcome ranking 的跨进程生产样本闭环；
- RunCheckpoint 中 planning/control 字段全部收敛为独立 owner substate。

这些边界不能用 schema、DI、event type 或 mock 调用冒充已落地能力。

## 17. 验证基线

核心测试覆盖：

- Goal identity、dependency、revision fencing 和 terminal 状态；
- effective resource scope、未知 Goal fail-closed 和 Mutation taxonomy；
- criterion provenance、evidence、receipt 和 Completion gate；
- PlanningMode、Plan CAS、replacement 和 monitor budget；
- Capability matcher、operation coverage 和 Provider policy；
- Procedure confirmation、idempotency 和 recovery；
- Context purpose/trust/admission；
- checkpoint round-trip、event replay 和 artifact refs；
- Research/A2A Definition/Projection 分离。

2026-07-15 本地验证结果：

- `.venv\Scripts\python.exe -m pytest --collect-only -q`：842 tests collected；
- `.venv\Scripts\python.exe -m pytest -q --maxfail=1`：842 passed，39 warnings；
- warnings 来自第三方依赖弃用提示、现有 Neo4j async resource warning 和测试中的 `datetime.utcnow()`，没有测试失败；
- 本轮未重新执行依赖外部模型或服务的 eval/benchmark，未执行结果不记为通过。

后续修改每个模块时，必须先明确该模块的输入、产物、事实所有权和禁止职责，再说明它保护的业务不变量。无法说明业务目的的字段、转换或 fallback，不应通过增加 validator 或兼容副本保留，而应重新确定模块边界。

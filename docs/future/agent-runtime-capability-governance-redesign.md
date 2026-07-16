# Agent Control Plane：Runtime、Capability 与 Deterministic Governance 三控制域重构

## 定位

本文定义 personalAgent 下一阶段的目标架构。目标不是继续增加平级模块，而是让系统直接回答三个稳定问题：

1. Agent 如何运行并持续接近 Goal；
2. Agent 在一次模型调用或 Action 中可以使用哪些能力；
3. 哪些模型提案、能力授权、外部副作用和结果可以成为系统事实。

三个问题共同组成 `Agent Control Plane`：

```text
Agent Control Plane
├─ Runtime Control Domain
├─ Capability Management Domain
└─ Governance & Policy Domain
```

真正调用模型、Tool、MCP、Retriever、Agent 和 Procedure 的部分属于 `Agent Execution Plane`。Checkpoint、Event Store、Artifact Store 以及 Observation/Evidence/VerificationReport 的持久化属于状态与证据基础设施。`GoalVerifier`、`CompletionVerifier` 不是基础设施：它们是组合 Runtime 业务语义、Governance 确定性下限和必要语义判断的应用服务。控制域是兄弟关系，不是三个串行 Manager，也不是三个保存全部状态的大对象。

本文是未来目标态，不把设计描述成当前事实。当前事实仍以
[当前核心架构](../summary/core-architecture-current-state.md) 为准；成功标准详细设计见
[成功标准与验证重构](success-criteria-verification-redesign.md)；本地并行与运行中语义修改见
[并行 Join 与语义 Steering](parallel-steering-runtime-design.md)。

本轮不保留旧接口兼容、双写、历史 checkpoint 迁移或灰度模型。目标模型落地时直接修改所有调用方并删除被替代的类型、字段和路径。

## 1. 外部评估结论

两轮外部评估总体合理。第一轮识别了策略维度混合、Skill 生命周期错误、子授权链不闭合、副作用恢复语义不足、Task 建立前 owner 分散和 Observation 信任语义不准确；最新增量评估进一步发现了 Model invocation 授权缺口、协议顺序循环、通用 Grant/Availability 回吸耦合、ControlPhase 未封闭以及控制事实提交边界不完整。

### 1.1 完整采纳

- `procedural` 与 `reactive/deliberative` 不正交，必须拆为协调模式与执行路由；
- Skill 必须在模型调用前激活，不能复用 Action 后置的 Capability Request/Grant；
- Procedure node 和 delegated child 必须获得从父授权派生的子授权；
- 仅有 checkpoint 和 committed idempotency key 不能解决“远端成功、本地未记账”的崩溃窗口；
- TaskContract 建立前需要独立的 durable intake substate；
- Observation 是外部返回记录，不是可信事实；
- ExecutionGrant 应按相关依赖 fencing，不能因无关 Portfolio 变化全部失效；
- Admission 不得静默修改 Proposal，应显式编译 AcceptedCommand；
- 技术执行结果与验证效果发生在不同时间，必须拆分事件；
- Task 终止必须保存 typed reason；
- Runtime、Capability、Governance 应为兄弟控制域，不能画成链式依赖；
- 所有 LLM 调用必须先经过统一的 Model Invocation Protocol；
- SkillContextGrant 只治理上下文注入，不能代替模型 Provider、数据外发和成本授权；
- 基础 Skill activation 不是业务 ControlDecision；
- ExecutionGrant 必须是封闭的叶子授权类型，而不是一种可执行所有能力的通用 Grant；
- `AcceptedCommand -> ExecutableInvocation -> Journal` 必须形成唯一执行链，删除未定义的 InvocationIntent；
- ControlPhase 必须是封闭恢复状态机，不能是任意字符串；
- Intake、Control 与 Dispatch 都需要明确的原子提交或恢复边界；
- Availability 必须按 contextual/execution 语义分型，并让 revision 有唯一 owner；
- ExecutionRoute 的最终决定必须由显式 Route Admission 产生；
- Evidence admitted 只表示“可为指定目的考虑”，不表示内容为真；
- kernel 只能保存跨领域仍然稳定的 primitive，不能演变为共享类型仓库。

### 1.2 收紧后采纳

#### Invocation Journal / Outbox

副作用、不可安全重试和长时异步调用强制进入 durable journal/outbox。低风险、可安全重试的只读调用可以走轻量直接路径，但仍记录 attempt 和 Observation。禁止为了形式统一让所有内存推理或本地纯函数承担数据库 outbox 成本。

#### TaskIntakeState

`TaskIntakeState` 是 `RunCheckpoint` 中的高内聚 substate，不建立第二套 Event + Projection aggregate。入口 clarification 当前已有 checkpoint 能力，目标重构解决的是 owner 分散，而不是重复实现 durable interrupt。

#### Observation / Evidence

不再创建字段高度重复的 `RawObservation` aggregate。保留唯一 `Observation`，明确其默认不可信，并通过 `EvidenceAdmissionDecision` 生成可用于验证的 EvidenceRef。

#### Capability Portfolio

Portfolio 继续提供统一发现视图，但 Skill 与执行能力使用不同生命周期协议。统一的是目录、信任和可用性观察，不统一 Request、Grant 或执行接口。

#### ControlPhase 与原子提交

ControlPhase 只表示 Orchestration 的 durable resume anchor，不复制 InvocationJournal 的远端执行状态。原子提交也不要求把所有 Projection 变成第二份 canonical state：提交 canonical fact、cursor 和 checkpoint CAS；Projection 可以在同一事务内更新，也可以按 cursor 确定性追平。

## 2. 当前设计需要解决的问题

### 2.1 运行协议仍混合两个维度

当前 `PlanningMode = reactive | deliberative | procedural` 把两个问题放进同一枚举：

- `reactive/deliberative` 描述是否需要显式短期协调；
- `procedural` 描述一个 Action 采用哪种执行路径。

Deliberative plan 本身可以包含 Procedure step，证明三者不能互斥。

### 2.2 能力发现与能力使用生命周期混合

Skill 在 Planner、Executive、Verifier 调用模型前影响语义决策；Tool、Agent、Procedure 在 Action 通过 admission 后承担执行。若统一为一种 Action 后置 Request，Skill 已无法影响当前 Action 的生成。

### 2.3 外层授权没有完整传递到内部执行者

Procedure 外层被允许调用，不代表其任意 node 自动获得 Tool 权限；父 Agent 可以 delegate，也不代表 child Agent继承父任务的完整 resource、context、tool 和预算。

### 2.4 副作用恢复只解决了重复提交的一部分

当前 durable idempotency ledger 能阻止同一个 key 再次执行，但不能区分：

```text
远端未收到请求
远端正在执行
远端成功但本地未 commit
远端结果未知
```

将 `reserved` 永久视为已经执行会阻塞恢复；释放并重试又可能重复副作用。

### 2.5 Intake、Control 和业务 Runtime 的 owner 需要分离

Task 建立前也可能多轮 clarification。入口状态不应散落在 RunCheckpoint 顶层，也不能伪装成半成品 TaskRuntime。

### 2.6 外部返回与可信证据的语义需要分离

Provider、网页、MCP 和 child Agent 返回的是“系统观察到了某个输出”，不是“输出内容为真”。Prompt injection、错误数据、过期信息和 Provider 自述 trust 都不能直接进入模型指令或 Goal verification。

### 2.7 模型调用仍是隐式高权限通道

SkillContextGrant 只回答“注入哪些方法和知识”，没有回答“允许调用哪个模型、向哪个区域外发哪些数据、花费多少 token/cost”。当前实现中 LLM 调用入口仍分散在 Runtime、Planner、Ask、Memory 和 Procedure node；若没有统一协议，Context Gateway 可以被调用方绕过，模型 Provider 也不会受与 Tool 同等级别的 egress、budget 和 audit 控制。

### 2.8 控制事实缺少统一提交边界

Outbox 只覆盖外部 dispatch 还不够。Intake 编译 Task、Admission 建立 AcceptedCommand、Checkpoint 推进 resume phase 都存在“一个事实成功、另一个事实未写入”的崩溃窗口。必须定义 canonical commit record、CAS 和恢复规则，而不是依赖调用顺序。

### 2.9 通用类型正在重新吸收领域语义

未分型的 CapabilityGrant、Availability 以及集中式 `kernel/contracts` 会通过大量可空字段重新耦合 Skill、Model、Tool、Procedure 和 Agent。目标态需要封闭 union、领域内 contract 和极薄 kernel。

## 3. 目标与非目标

### 3.1 目标

- 建立唯一 Runtime Protocol 和明确的 Task 生命周期；
- 将 CoordinationMode 与 ExecutionRoute 拆为正交维度；
- 建立统一能力目录，但分离 Skill activation 与 Action resolution；
- 建立统一 Model Invocation Protocol，并显式授权模型、Provider、上下文外发和成本；
- 建立不可转让、只能收缩权限的 ExecutionGrant 封闭类型；
- 闭合 Procedure 和 delegated Agent 的派生授权；
- 对副作用实现 journal、outbox、幂等和 reconciliation；
- 建立 proposal、admission、accepted-command compiler 的明确边界；
- 让 Observation、Evidence 和 Verification 各自拥有单一语义；
- 为 Intake、Control 和 Dispatch 建立原子提交或可证明恢复协议；
- 将 Task Intake、Model Invocation、Control、Execution、Result Acceptance 收敛为五条核心协议；
- 用 hermetic tests 保护不变量，用多 trial eval 评价开放策略。

### 3.2 非目标

- 不创建保存所有事实的 `AgentState`；
- 不创建 `GovernanceManager.validate(anything)`；
- 不把 Skill、Tool、Agent 和 Procedure 压成同一种执行接口；
- 不让 Planner 绑定 Provider、凭证或物理并发；
- 不让 Tool、Provider、child Agent 或模型宣布 Goal/Task 完成；
- 不承诺通用 exactly-once；目标是可证明的 effectively-once 或显式 unknown outcome；
- 不为所有只读调用强制 Outbox；
- 不为 Intake、Control 或 Acquisition 机械建立完整事件聚合；
- 不为目录对称增加没有独立业务目的的 Model 或 Service。

## 4. 强制设计原则

### 4.1 高内聚、低耦合、不过度设计

- Runtime 只决定当前任务状态和下一次允许发生的变化；
- Capability 只决定可见能力、适用性、可用性和本次授权；
- Governance 只决定 Proposal/Command 是否可以被接受；
- Execution 只执行已经获得授权的 invocation；
- Verifier 只接受或拒绝结果，不选择执行路径；
- Orchestration 只组合 Port、Checkpoint、interrupt/resume，不重写领域规则。

### 4.2 单一事实 owner

| 事实 | 唯一 owner |
| --- | --- |
| 入口原始请求、clarification 和当前 Task proposal | `TaskIntakeState` |
| 用户目标、criterion、resource、dependency | `TaskContract` |
| Goal 当前状态和验证覆盖 | `TaskRuntimeProjection` |
| 短期策略定义 | `PlanDefinition` |
| Plan step 当前状态 | `PlanRuntimeProjection` |
| 当前 control turn 恢复现场 | `ControlTurnState` |
| 能力静态描述 | 对应 Skill/Capability/Agent/Procedure Registry |
| Skill 内容/integrity/trust 可用性 | `ContextCapabilityAvailabilityProjection` |
| Tool/Model/Agent/Procedure 运行可用性 | `ExecutionCapabilityAvailabilityProjection` |
| 模型调用可使用的 Skill 内容 | `SkillContextGrant` |
| 模型 Provider、egress 和 cost 授权 | `ModelInvocationGrant` |
| Accepted Action 的最终执行路径 | `ExecutionRouteDecision` |
| Atomic/Procedure/Node/Delegation 执行授权 | 对应叶子 `ExecutionGrant` |
| 外部 dispatch 与远端结果状态 | `InvocationJournal` |
| invocation 当前 attempt 状态 | `InvocationAttemptState`，由 Journal 投影 |
| 外部返回记录 | `Observation` |
| Observation 是否可作为 Evidence | `EvidenceAdmissionDecision` |
| criterion 是否满足 | `GoalVerifier` 产出的 `VerificationReport` |
| Task 是否完成 | `CompletionVerifier` 产出的 `CompletionReport` |
| 当前可恢复现场组合 | `RunCheckpoint` |

### 4.3 模型角色分离

```text
Definition / Contract       稳定定义与授权边界
Proposal / Command          请求一次有界变化
Admission Decision          接受、拒绝或要求交互
Accepted Command / Event    确定性系统接受的变化
Runtime Projection          从事实投影出的当前状态
View                        调用时组合读取，不建立新事实
```

可从 canonical state 推导的字段不得成为第二份可写状态。Snapshot/View 不允许反向写回 owner。

### 4.4 模型处理开放语义，代码控制可判定边界

模型可以提议 Goal、策略、Action、证据语义和答案组织。确定性系统独占：

- identity、revision、cursor、引用完整性和 DAG；
- 状态迁移、预算、幂等、dispatch journal；
- resource/operation match、权限交集和 grant；
- write set、HITL、数据外发和 commit-time policy；
- receipt、approval、evidence 下限和 completion；
- checkpoint、event append、replay 和 reconciliation。

### 4.5 权限单调收缩

```text
Task authority
  ∩ Goal resource scope
  ∩ Action requested scope
  ∩ Capability definition scope
  ∩ Parent execution grant / Procedure envelope
  ∩ Runtime policy
  ∩ User confirmation
  = Effective leaf ExecutionGrant
```

后续阶段不得补回上游未授权的 operation、locator、provider、credential、egress、tool、delegation depth 或 side effect。

## 5. 顶层架构

```text
                         thin kernel primitives
                         ↑          ↑          ↑
                 Runtime Domain  Capability  Governance
                         \          |          /
                    Application Protocol Orchestration
             Intake / Model / Control / Execution / Result
                      GoalVerifier / CompletionVerifier
                                   |
                         Agent Execution Plane
                 ┌─────────┬────────┬─────────┬──────────┐
              Model      Tool/MCP  Agent    Procedure   Internal
              Runtime    Gateway   Gateway   Runtime     Compute
                 └─────────┴────────┴─────────┴──────────┘
                                   |
                      State & Evidence Foundation
                 Checkpoint / Event / Journal / Artifact /
                 Observation / Evidence / VerificationReport
```

Runtime、Capability、Governance 只能通过 Port 和 typed contract 协作。它们只能共同依赖极薄的 kernel primitive，领域 contract 留在所属领域；任何一方都不能依赖其他控制域的具体实现或读取对方完整 projection。

## 6. Runtime Control Domain

### 6.1 TaskIntakeState

TaskContract 建立前使用轻量 durable substate：

```text
TaskIntakeState
  intake_id
  status: analyzing | awaiting_input | compiled | cancelled
  source_message_refs[]
  original_input_ref
  current_proposal_ref | None
  proposal_revision
  missing_requirement_ids[]
  interaction_request_ref | None
  compiled_task_ref | None
  policy_revision
```

约束：

- Intake 不拥有 Goal runtime，不是半成品 Task；
- 每次 clarification 产生新 proposal revision，不原地改写历史 Proposal；
- InteractionRequest 在 interrupt 前写入 checkpoint；
- Task compilation 在同一提交边界内创建 TaskContract、初始化 runtime、写入 `compiled_task_ref` 并将 Intake 置为 compiled；
- cancelled Intake 不产生 Task；
- 只有当 Intake 需要独立审计/重放且 checkpoint 无法满足时，才增加专属 Event，不预建空 aggregate。

### 6.2 Task 生命周期

```text
active
  -> awaiting_input
  -> paused
  -> completed
  -> terminated

awaiting_input -> active | paused | terminated
paused         -> active | terminated
completed      -> terminal
terminated     -> terminal
```

```text
TaskTerminationReason
  user_cancelled
  policy_denied
  budget_exhausted
  unrecoverable_failure
  superseded
  administrator_stop
```

| 转换 | 唯一触发者 |
| --- | --- |
| `active -> awaiting_input` | 已通过 admission 的 InteractionRequest |
| `awaiting_input -> active` | 与 request 绑定且通过校验的用户输入 |
| `active/awaiting_input -> paused` | Durable Run control command |
| `paused -> active` | resume command + snapshot revalidation |
| `active -> completed` | CompletionVerifier 接受 CompletionClaim |
| `* -> terminated` | typed termination command + reason |

Task status 保持简洁，终止原因由不可为空的 typed reason 表达。`completed/terminated` Task 不得产生新 Action、Grant 或 control turn。

### 6.3 五条 Canonical Protocol

整个 Agent 只组合五条核心协议：

```text
Task Intake Protocol
  User Input -> Task Proposal -> Task Admission
  -> Clarification | TaskCompilationCommit

Model Invocation Protocol
  ModelCallIntent -> SkillActivationDecision
  -> optional SkillContextGrant
  -> ModelInvocationRequest -> ModelInvocationGrant
  -> ContextProjection -> Model Runtime -> Typed Model Outcome

Control Protocol
  Typed Proposal -> Stage Admission -> AcceptedCommandCompiler
  -> AcceptedCommand -> ControlCommit

Execution Protocol
  Accepted Action -> ExecutionRouteDecision
  -> ExecutionCapabilityRequest -> leaf ExecutionGrant
  -> ExecutableInvocation -> DispatchCommit
  -> Journal/Outbox -> Provider -> Observation

Result Acceptance Protocol
  Observation -> Evidence Admission -> VerificationReport
  -> Goal Progress -> CompletionClaim -> CompletionVerifier
```

TaskAnalyzer、Planner、Executive、Monitor 和 Semantic Verifier 需要模型时，统一调用 Model Invocation Protocol；它不是 Runtime 主循环中只执行一次的固定步骤。

### 6.4 Canonical Runtime Loop

```text
0. Run Task Intake Protocol
1. Materialize Task/Goal View
2. Project Coordination Facts
3. Assess CoordinationMode
4. If deliberative, invoke Planner through Model Invocation Protocol
5. Admit Plan Proposal and create/patch/replace Plan
6. Project Control View
7. Invoke Executive through Model Invocation Protocol
8. Run Control Protocol for one Typed Proposal
9. Resolve an explicit ExecutionRouteDecision when command is executable
10. Run Execution Protocol or apply a non-execution Command
11. Run Result Acceptance Protocol when an Observation exists
12. Invoke semantic Monitor through Model Invocation Protocol when required
13. Continue / Await Input / Pause / Terminate / Complete
```

这是唯一运行语义，不要求每轮经过全部阶段。跳过条件必须来自 typed state/mode/route，不能由 `None`、空字符串或节点内部猜测决定。任何直接调用 LLM Provider、绕过 Model Invocation Protocol 的路径都是架构违规。

### 6.5 CoordinationMode

```text
CoordinationMode = reactive | deliberative
```

#### Reactive

一个有界 Decision 很可能直接推进 ready Goal，不创建 PlanDefinition：

```text
CoordinationAssessment(reactive)
  -> Executive
  -> ControlDecision
```

#### Deliberative

多个 Goal、依赖、证据缺口或路径不确定性需要短 horizon 协调：

```text
CoordinationAssessment(deliberative)
  -> AdaptivePlanner
  -> PlanDefinition
  -> validated frontier
  -> Executive
```

只有 deliberative 维护 Adaptive Plan。Planner 保持 provider-neutral，不绑定 Tool、凭证或物理并发。

### 6.6 ExecutionRoute

每个 Accepted Action/PlanStep 独立选择：

```text
ExecutionRoute
  atomic             Tool / MCP / Retriever
  delegated          Child Agent
  procedure          Governed Procedure
  internal_reasoning 本地组合、推理、验证
```

CoordinationMode 与 ExecutionRoute 正交：

| 场景 | CoordinationMode | ExecutionRoute |
| --- | --- | --- |
| 单目标搜索 | reactive | atomic |
| 单目标删除知识 | reactive | procedure |
| 检索后写入知识库 | deliberative | atomic -> procedure |
| 多来源调研 | deliberative | atomic/delegated |

Mandatory Procedure 约束 ExecutionRoute，不再把整个 Task 的 CoordinationMode 改成 `procedural`。

Planner 或 Executive 只能产生 `RouteProposal`。最终路径由 `ExecutionRoutePolicy` 根据 Action 语义、风险、mandatory procedure、delegation policy 和 internal reasoning 边界生成 `ExecutionRouteDecision`：

```text
RouteProposal + AcceptedAction + GovernanceSnapshot
  -> RouteAdmission
  -> ExecutionRouteDecision
       accepted_route
       mandatory_constraints[]
       denied_routes[]
       reason_codes[]
       policy_revision
```

Policy 可以强制 Procedure、禁止 Delegation 或禁止 internal reasoning 访问外部资源，但不能扩大 AcceptedAction 的 resource/operation scope。Orchestration 只消费 RouteDecision，不得自己猜 route。

### 6.7 ControlDecision

```text
ClarifyDecision
ExecuteBoundedActionDecision
DelegateDecision
InvokeProcedureDecision
RequestConfirmationDecision
RequestCapabilityAcquisitionDecision
FinishDecision
TerminateDecision
```

当前 `ExecuteMetaCapabilityDecision` 目标态更名为 `ExecuteBoundedActionDecision`；`BoundedAction.meta_capability` 更名为 `execution_intent`。`acquire/explore/reason/verify/transform/commit` 是 Action 语义分类，不是 Capability 类型。

基础 Skill activation 从 ControlDecision 删除。模型调用发现上下文不足时，Model Invocation Protocol 返回 typed `ContextGapOutcome`，由 Runtime 选择重新解析 Skill、请求能力补齐、clarification 或失败；不得先调用 Executive 再让 Executive 决定是否为本次调用激活 Skill。

### 6.8 ControlTurnState

```text
ControlPhase
  preparing_model_call
  proposing
  admitting
  routing
  resolving_execution
  preparing_dispatch
  awaiting_result
  accepting_result
  monitoring
  awaiting_input
  closed
```

允许的主迁移：

```text
preparing_model_call -> proposing -> admitting
admitting -> routing | awaiting_input | closed
routing -> resolving_execution | closed
resolving_execution -> preparing_dispatch | awaiting_input | closed
preparing_dispatch -> awaiting_result
awaiting_result -> accepting_result
accepting_result -> monitoring | closed
monitoring -> preparing_model_call | awaiting_input | closed
awaiting_input -> preparing_model_call | closed
```

失败、暂停或终止可以从非 terminal phase 转到 closed，但必须同时保存 typed RuntimeDisposition/termination reason。

```text
ControlTurnState
  turn_id
  task_revision
  task_event_cursor
  plan_ref | None
  coordination_mode
  phase: ControlPhase
  model_call_ref | None
  proposal_ref | None
  admission_decision_ref | None
  accepted_command_ref | None
  execution_route_decision_ref | None
  capability_resolution_ref | None
  invocation_refs[]
  observation_refs[]
```

Control turn 是 checkpoint substate，不建立完整 Event + Projection。`phase` 只回答恢复时下一步调用哪个协议，不声明 Provider 是否成功；远端执行真相仍由 InvocationJournal 独占。Task/Plan definition、MaterializedView、完整 model context、Grant 字段镜像和派生 execution trace 不得写入其中。

### 6.9 RuntimeDisposition

```text
continue_control
retry_invocation
reassess_coordination
patch_plan
replace_plan
await_input
pause
terminate
propose_completion
```

只有 CompletionVerifier 可以将 `propose_completion` 转换为 Task completed Event。

### 6.10 原子提交与恢复边界

定义三个 application-level Unit of Work；它们是提交协议，不是新的业务 aggregate：

```text
TaskCompilationCommit
  TaskContract creation
  + initial TaskRuntimeProjection
  + TaskIntakeState(compiled, compiled_task_ref)
  + checkpoint CAS

ControlCommit
  AdmissionDecision
  + AcceptedCommand
  + resulting domain event(s) when applicable
  + canonical event cursor
  + ControlTurnState phase/ref
  + checkpoint CAS

DispatchCommit
  ExecutableInvocation
  + invocation_prepared
  + outbox entry when required
  + ControlTurnState invocation_ref/phase
  + checkpoint CAS
```

同一事务内可以同步更新 Projection，但 Projection 不是第二份提交事实；若异步更新，则按 canonical cursor 追平。若存储无法共享事务，必须使用可重放 commit record、稳定 identity、CAS 和 recovery coordinator 达到相同结果。禁止出现“Intake 已 compiled 但没有 compiled_task_ref”“Checkpoint 已 awaiting_result 但不存在 invocation_prepared”等不可恢复组合。

## 7. Capability Management Domain

### 7.1 统一发现视图，分离使用协议

```text
CapabilityPortfolioView
  portfolio_revision
  contextual_entries: SkillPortfolioEntry[]
  execution_entries: ExecutionCapabilityEntry[]
```

```text
SkillRegistry            -> SkillDefinition
ModelRegistry            -> ModelCapabilityDefinition
AtomicCapabilityRegistry -> AtomicCapabilityDefinition
AgentRegistry            -> AgentCapabilityDefinition
ProcedureCatalog         -> ProcedureDefinition
```

Portfolio 是只读 View。Skill 内容、模型能力/Provider binding、Tool schema、Agent profile、Procedure node 和 Provider payload 留在各自 definition owner 中。统一 discovery 不表示 Skill、Model、Tool、Agent 和 Procedure 共用一种 Request、Grant 或 dispatch 接口。

### 7.2 模型调用前的 Skill Activation

Skill 不使用 Action 后置 ExecutionGrant：

```text
ModelCallIntent
  -> SkillActivationRequest
  -> Skill discovery
  -> trigger/domain/version/trust admission
  -> SkillActivationDecision
  -> SkillContextGrant | no_skill_required
```

```text
SkillActivationRequest
  request_id
  model_call_intent_ref
  domain_requirements[]
  trust_floor
  context_budget
  preferred_skill_refs[] | None
  policy_profile_ref

SkillActivationDecision
  request_id
  outcome: granted | no_skill_required | denied
  discovery_snapshot_ref
  considered_skill_refs[]
  admitted_skill_refs[]
  denied_skill_refs[]
  reason_codes[]

SkillContextGrant
  grant_id
  request_id
  model_call_intent_ref
  admitted_skill_refs[]
  content_refs[]
  trust_floor
  context_budget
  expires_after_model_call
```

`preferred_skill_refs` 只是提示，不是 Runtime 预先完成 discovery。SkillContextGrant 只允许 Skill 内容进入指定模型调用，不授予模型 Provider 或外部资源权限，不可复用于另一 purpose。Skill 对 trajectory 的效果通过离线 eval 评价，不根据单次 Tool success 自动记“Skill 成功”。

### 7.3 Model Invocation Grant

模型调用本身是受治理的外部 invocation：

```text
ModelCallIntent
  intent_id
  task_ref | intake_ref
  goal_refs[]
  caller_role
  purpose
  required_context_refs[]
  expected_outcome_contract_ref
  source_snapshot_ref
```

ModelCallIntent 是“为什么需要模型以及期望返回什么”的稳定输入，SkillActivationRequest 和 ModelInvocationRequest 都引用它，不复制 task/purpose/context/output contract。

```text
ModelCallIntent + SkillActivationDecision
  + optional SkillContextGrant
  -> ModelInvocationRequest
  -> model capability discovery and binding
  -> context/egress/region/sensitivity admission
  -> token/cost/latency budget admission
  -> structured-output compatibility admission
  -> ModelInvocationGrant or ModelInvocationDenial
  -> ContextProjection constrained by activation decision and grant(s)
  -> Context Gateway
  -> Model Runtime
  -> Typed Model Outcome + Model Trace
```

```text
ModelInvocationRequest
  request_id
  model_call_intent_ref
  required_model_capabilities[]
  context_classifications[]
  data_egress_requirement
  region_constraints[]
  latency_budget
  token_budget
  cost_budget
  structured_output_requirement
  policy_profile_ref

ModelInvocationGrant
  grant_id
  request_id
  model_ref
  provider_binding_ref
  admitted_context_refs[]
  admitted_data_egress_scope
  admitted_regions[]
  token_limit
  cost_limit
  timeout
  structured_output_contract_ref | None
  policy_bundle_hash
  dependency_set
  expires_after_call
```

ModelInvocationGrant 的 dependency set 至少绑定 model definition revision、provider binding revision、对应 ExecutionCapabilityAvailability revision(s)、context classification snapshot、budget reservation revision 和 policy bundle hash；任一相关依赖变化都需要重新 admission。

SkillContextGrant 控制“注入什么方法和知识”；ModelInvocationGrant 控制“用什么模型、外发什么数据、花费多少资源”。ModelInvocationGrant 永远必需；SkillContextGrant 只有在 SkillActivationDecision 显式记录 `no_skill_required` 时可以缺省。Model Runtime 必须引用这次 activation decision，完整 prompt 不得由业务调用方直接提交给 Provider。

```text
ModelInvocationOutcome =
    TypedProposal
  | ContextGapOutcome
  | ModelInvocationFailure
```

ContextGapOutcome 可以触发重新解析 Skill、capability acquisition 或 clarification，但不能伪装成业务 ControlDecision。ModelInvocationFailure 保存 Provider/timeout/schema/budget 等封闭失败类，不把自由文本当 route。

### 7.4 Action 后的 Execution Capability Resolution

```text
Accepted Action + ExecutionRouteDecision
  -> ExecutionCapabilityRequest
  -> Portfolio discovery
  -> kind-specific applicability
  -> lifecycle / availability admission
  -> resource / operation hard match
  -> trust / egress / credential policy
  -> provider binding
  -> optional outcome-aware ranking
  -> CapabilityResolutionDecision
  -> leaf ExecutionGrant or CapabilityDenial
```

```text
ExecutionCapabilityRequest
  request_id
  task_ref
  goal_ref
  action_ref
  execution_route_decision_ref
  requested_resource_selector
  requested_operation_scope
  provider_constraints
  risk_envelope
  parent_grant_ref | None
  policy_profile_ref
```

```text
CapabilityResolutionDecision
  request_id
  discovery_snapshot_ref
  considered_candidate_refs[]
  hard_denial_refs[]
  selected_execution_grant_ref | None
  reason_codes[]
```

Request 只描述需要什么，不携带 candidate、discovery revision 或发现结果，不指定未经授权的 Provider，也不嵌入 Runtime projection。Discovery snapshot 由 ResolutionDecision 记录；Request 一旦创建不可变。

### 7.5 Definition 与 Availability

```text
definition lifecycle: active | deprecated | retired
runtime availability: available | degraded | unavailable | unknown
```

```text
ContextCapabilityAvailabilityProjection
  observations: map[SkillRef, ContextCapabilityAvailability]

ContextCapabilityAvailability
  skill_ref
  availability_revision
  status
  content_revision
  integrity_status
  trust_status
  compatible_model_purposes[]
  observed_at
  expires_at | None
  reason_codes[]

ExecutionCapabilityAvailabilityProjection
  observations: map[CapabilityRef, ExecutionCapabilityAvailability]

ExecutionCapabilityAvailability
  capability_ref
  availability_revision
  status
  credential_ready
  health_observed_at
  health_expires_at
  provider_binding_revision
  reason_codes[]
```

两类 Availability 分别由 ContextCapabilityAvailabilityProjection 和 ExecutionCapabilityAvailabilityProjection 独占写入，通过 discriminated union 进入 Portfolio View；不得用空 `credential_ready` 或空 `content_revision` 伪造统一模型。Availability 不复制 selector、operation 或 schema。高风险 Action 不得把过期或 unknown health 当作 available。Retired definition 不产生新 Grant。

### 7.6 ExecutionGrant 封闭类型

```text
ExecutionGrant =
    AtomicCapabilityGrant
  | ProcedureGrant
  | ProcedureNodeGrant
  | DelegationGrant

ExecutionGrantCommon
  grant_kind: atomic | procedure_start | procedure_node | delegation
  grant_id
  request_id
  action_ref
  granted_resource_selector
  granted_operation_scope
  granted_data_egress
  granted_credential_mode
  required_confirmation_ref | None
  retry_family_id
  dependency_set: GrantDependencySet
  expires_at
```

叶子授权的专属绑定：

| Grant | 只允许的 dispatch | 必须绑定 |
| --- | --- | --- |
| `AtomicCapabilityGrant` | Tool/MCP/Retriever invocation | capability + provider binding |
| `ProcedureGrant` | exact Procedure start | procedure id/version + permission envelope |
| `ProcedureNodeGrant` | exact Procedure node invocation | procedure run + node + capability binding |
| `DelegationGrant` | exact child Agent start | agent binding + bounded sub-goal/context/budget |

每次 dispatch 只引用一个叶子 ExecutionGrant。父 ProcedureGrant 负责启动 Procedure 和形成 permission envelope，不能作为内部任意 Tool dispatch 的通用授权；不存在可传给所有 Gateway 的具体 `CapabilityGrant` 基类。

```text
GrantDependencySet
  task_revision
  goal_definition_fingerprint
  action_fingerprint
  plan_id / plan_revision / step_fingerprint | None
  capability_definition_revision
  provider_binding_revision | None
  availability_dependencies[]:
    capability_ref
    availability_revision
    valid_until | None
  authority_revision
  policy_bundle_hash
  confirmation_revision | None
```

`availability_revision` 由对应 Availability owner 单调递增，Grant 不引用一个未定义的全局 relevant revision。Portfolio revision 只用于复现 discovery，不默认成为所有 Grant 的失效条件。新增无关 Tool 不应使现有知识读取 Grant 失效；任何 dependency set 中的相关事实变化都必须重新 resolution。

强制不变量：

- Grant scope 是 Request、Definition、ParentGrant 和 Policy 的交集；
- Grant 绑定一个 Action/Procedure start/node/Delegation 和 retry family；
- same-provider retry 只有在 Grant 有效、幂等和 retry policy 允许时复用；
- equivalent provider retry 必须重新 resolution；
- Gateway 只接收 Grant 允许的 payload；
- Grant 不能替代 Procedure commit-time policy；
- Grant 过期不能原地延长。

### 7.7 Procedure 子授权闭环

采用“Procedure 权限信封 + node 派生 Grant”的单一设计：

```text
ProcedureGrant
  exact procedure id/version
  goal/action scope
  permission_envelope
  confirmation policy
  receipt contract

ProcedureDefinition.Node
  declared resource/operation/egress requirement

Procedure node
  -> DerivedExecutionCapabilityRequest
  -> ProcedureNodeGrant
  -> Tool/MCP/Agent Gateway
```

```text
child scope
  ⊆ ProcedureGrant.permission_envelope
  ⊆ Procedure node declared requirement
  ⊆ Task/Goal authority
```

每个 node 必须持有绑定 `procedure_run_id + node_id` 的 ProcedureNodeGrant；副作用 node 还必须满足 confirmation/receipt 约束。Procedure Runtime 不得因自身受治理而绕过 Gateway，也不得让同 Goal 的普通 Action Grant 兜底匹配所有 node。Commit 前再次验证 exact target、confirmation、policy、idempotency 和 receipt contract。

### 7.8 Delegation 子授权闭环

```text
DelegationGrant
  parent_task_ref
  parent_goal_ref
  bounded_sub_goal
  resource_scope
  operation_scope
  allowed_capability_refs[]
  allowed_tool_refs[]
  context_projection_refs[]
  data_egress_policy
  token/cost/time/provider budgets
  max_delegation_depth
  completion_contract
  expires_at
```

Child Agent 不继承父 Agent 的完整 TaskContract、ContextInventory、credential 或 tool registry。DelegationGrant 只允许 Agent Gateway 启动 exact child；child runtime 必须在该 envelope 内为自己的 Tool/Procedure 调用重新派生 Atomic/Procedure grants，不能把 DelegationGrant 直接交给 Tool Gateway。远程 Agent 的 Agent Card 只是能力声明，不能替代 DelegationGrant。Child artifact 默认 unverified，必须回到父 Runtime 的 Evidence Admission 和 Verification。

### 7.9 Capability Acquisition

CapabilityGap 由 Runtime 转换成管理命令，而不是伪造一个可执行 Capability：

```text
CapabilityGap
  -> RequestCapabilityAcquisitionDecision
  -> CapabilityAcquisitionRequest
  -> suggest / install / enable / connect / request-auth
  -> Registry or Availability owner update
  -> CapabilityAcquisitionOutcome
  -> Runtime 使用新 discovery snapshot 重新 resolution
```

默认策略是 suggest + user approval。自动 install/connect 只有在 allowlist、签名验证、sandbox、credential policy 和 rollback 都具备时允许。Acquisition 成功只表示环境变化，不代表 Goal progress。

### 7.10 Outcome 闭环

技术执行与业务效果发生在不同阶段：

```text
CapabilityExecutionOutcomeEvent
  invocation_ref
  capability_ref
  binding_ref
  technical_outcome
  latency_bucket
  remote_status
  observed_at

CapabilityEffectivenessEvent
  action_ref
  invocation_refs[]
  capability_refs[]
  verification_report_ref
  criterion_coverage_delta
  goal_progress
  evaluated_at
```

ExecutionOutcome 在 invocation 结束后写入；Effectiveness 只能在 Verification 后写入。两者均不可修改，ranking 聚合时按引用 join。Policy denial、用户取消、Provider unavailable 和任务难度必须分开统计，不能都记为 Capability 失败。

## 8. Governance & Policy Domain

### 8.1 统一治理规则

```text
Canonical Taxonomy
  RiskClass / SideEffectClass / MutationOperation /
  AdmissionVerdict / RuntimeDisposition / ReasonCode

Versioned Policy Profiles
  RuntimePolicy / CapabilityPolicy / MutationPolicy /
  ContextPolicy / VerificationPolicy

Stage-local Admission
  TaskAdmission / PlanAdmission / DecisionAdmission /
  RouteAdmission / SkillAdmission / ModelInvocationAdmission /
  ResolutionAdmission / ExecutionInvocationAdmission /
  EvidenceAdmission / OutcomeAdmission
```

各 Admission 靠近被保护的状态转换。公共 taxonomy 可以共享，禁止抽成 `validate(any)`。

### 8.2 Authority Matrix

| 阶段 | 模型可以做什么 | 模型不能做什么 | 接受者 |
| --- | --- | --- | --- |
| Task Analysis | 提议 Goal/resource/criterion/dependency | 创建 Runtime Event、批准 Mutation | GoalGraphCompiler |
| Coordination | 灰区协调模式建议 | 用 procedure 绕过协调判断 | CoordinationModePolicy |
| Adaptive Planning | 提议 provider-neutral steps | 绑定 Provider、扩大 operation、改 Task | PlanAdmission |
| Executive | 提议一次 typed Decision | 写 projection、直接执行、宣布完成 | DecisionAdmission |
| Skill selection | 提议相关 Skill | 注入未审查内容或扩大 purpose | SkillAdmission |
| Model invocation | 提议所需模型能力与预算 | 自选未授权 Provider、外发 Context、突破 cost/region | ModelInvocationAdmission |
| Execution route | 建议 route | 绕过 mandatory Procedure、扩大 Action scope | RouteAdmission |
| Capability ranking | 对 hard-eligible 候选软排序 | 恢复被拒候选 | ResolutionAdmission |
| Monitor | 提议 strategy impact | 修改已运行 step、突破 patch quota | MonitorAdmission |
| Verification | 判断开放 criterion 语义 | 降低 evidence/receipt/approval 下限 | GoalVerifier |
| Presentation | 组织表达 | 改写 canonical result | PresentationAssembler |

### 8.3 Proposal 到 AcceptedCommand

禁止 Validator 静默修改 Proposal：

```text
Typed Proposal
  -> Schema Validation
  -> Stage Admission
  -> AdmissionDecision
       accepted_proposal_ref
       verdict
       effective_constraints
       denied_fields[]
       monotonicity_proof
       policy_revision
       input_snapshot_ref
  -> AcceptedCommandCompiler
  -> AcceptedCommand
  -> Domain Event / RouteDecision / InvocationCompiler
```

权限交集体现在 `effective_constraints` 和 `monotonicity_proof` 中。AcceptedCommand 是新对象并引用原 Proposal；Admission 不补写新的 Goal、Provider、Resource 或业务语义。若收缩后无法满足 Proposal 的最小语义，必须 deny 或 clarification，不能编译残缺 Command。

非执行 Command 可以直接产生领域 Event；执行类 Command 必须继续经过 RouteDecision、Resolution 和 InvocationCompiler：

```text
AcceptedActionCommand
  -> ExecutionRouteDecision
  -> CapabilityResolutionDecision
  -> leaf ExecutionGrant
  -> InvocationCompiler
  -> ExecutableInvocation
```

目标态不存在 `InvocationIntent`。AcceptedCommand 表示业务动作已被接受；ExecutableInvocation 表示 route、capability/provider binding、payload、Grant、idempotency 和 retry/timeout policy 已全部固化的不可变执行定义。

### 8.4 Snapshot 与 Fencing

```text
GovernanceSnapshotRef
  task_revision
  task_event_cursor
  plan_id / plan_revision / plan_event_cursor | None
  policy_bundle_hash
  context_projection_ref | None
  discovery_snapshot_ref | None
```

GovernanceSnapshot 用于复现一次 Admission；具体 Grant 是否失效由 `GrantDependencySet` 决定。避免用全局 Portfolio revision 造成无关失效，也不能漏掉 capability definition、provider binding、相关 availability、confirmation 或 authority 的变化。

### 8.5 Fail-closed

必须 fail closed：

- unknown Goal/resource/capability/provider identity；
- 相关 revision、fingerprint 或 cursor 不一致；
- Mutation target、write set、confirmation 或 receipt contract 缺失；
- credential、trust、egress 或 authority 不满足；
- mandatory Procedure/ProcedureNodeGrant 不可用；
- delegated child scope 无法证明是父授权子集；
- deterministic evidence/approval/receipt 下限失败；
- side-effect dispatch outcome unknown 且无法 reconcile。

允许显式降级：

- semantic assessor 不可用时采用已定义 safe policy；
- outcome ranking 无样本时使用静态 priority + deterministic tie-break；
- semantic verifier 不可用时保留 deterministic result，不 false-pass；
- 低风险只读 Provider 不可用时重新 resolution 等价 Provider。

不存在安全 fallback 时，返回 clarification、capability gap 或 typed termination；不得用关键词、空对象或默认 Provider 伪造路径。

### 8.6 Mutation 治理

```text
TaskContract.MutationIntent
  -> Accepted Action
  -> mandatory ProcedureGrant
  -> node ProcedureNodeGrant
  -> exact target resolution
  -> user confirmation
  -> commit-time policy
  -> journaled idempotent dispatch
  -> MutationReceipt
  -> Evidence Admission
  -> GoalVerifier
```

任一阶段只能收缩 operation/target。Tool `ok=true` 只代表 technical outcome；没有 receipt 或 reconciliation 时不得 verified。

### 8.7 Observation 与 Evidence Admission

```text
Observation
  observation_id
  invocation_ref | interaction_ref | verifier_ref
  source_ref
  provenance
  trust_class
  taint_flags[]
  content_hash
  artifact_refs[]
  observed_at
  payload_ref
```

`Observation` 的语义是“系统记录到来源返回了这些内容”，不是“内容为真”。默认外部 Observation 为 untrusted data，不能作为模型指令。

```text
Observation
  -> EvidenceAdmissionDecision
       admitted | rejected | quarantined
       evidence_refs[]
       reason_codes[]
  -> VerificationReport
```

```text
EvidenceRef
  observation_ref
  admitted_purposes:
    model_context | criterion_verification |
    receipt_validation | strategy_monitoring
  applicable_criterion_refs[]
  trust_tier
  freshness_boundary
  policy_revision
```

`admitted` 只表示该 Observation 可以在列出的 purpose 和 criterion scope 内参与判断，不表示内容为真，也不表示 criterion 已满足。Provider timeout 可以用于 strategy monitoring 但不能充当内容证据；签名 receipt 可以用于 receipt validation，但不自动成为答案来源。

技术状态、timeout、receipt signature 等封闭字段可以被确定性 Monitor 使用；开放内容进入模型前必须经过 Context Gateway，以 data block 和 provenance 呈现。Prompt injection 标记内容不得被提升为 instruction。

### 8.8 Context Governance

每次模型调用声明：

```text
purpose
required_refs
skill_context_grant_ref | None
model_invocation_grant_ref
trust_floor
source_snapshot
admission_policy_ref
```

ContextProjection 必须同时满足 Evidence admission、SkillContextGrant 和 ModelInvocationGrant 的 admitted context/egress scope。Materialized payload 不进入 checkpoint。模型 Proposal 记录 ContextProjection ref、ModelInvocationGrant ref 和 model trace ref，完整 prompt 不复制进领域 Event。

## 9. Agent Execution Plane 与恢复正确性

### 9.1 ExecutableInvocation 与 Journal

`ExecutableInvocation` 定义要执行什么；`InvocationJournal` 是外部 dispatch 状态的唯一 owner；`InvocationAttemptState` 是 Journal 的可恢复投影。

```text
ExecutableInvocation
  invocation_id
  accepted_command_ref
  route_decision_ref
  execution_grant_ref
  provider_binding_ref
  compiled_payload_ref + payload_hash
  idempotency_key | None
  timeout_policy
  retry_policy
  journal_policy
```

InvocationCompiler 只能在 RouteDecision 和叶子 ExecutionGrant 均有效后创建 ExecutableInvocation。它不保存 mutable attempt 状态，不允许 Gateway 在 dispatch 时临时补 Provider、Resource、Operation 或 payload target。

```text
InvocationJournalEvent
  invocation_prepared
  dispatch_started
  remote_accepted
  remote_completed
  observation_recorded
  outcome_unknown
  reconciled
  failed
  cancelled
```

```text
InvocationAttemptState
  invocation_ref
  status
  attempt_count
  journal_cursor
  remote_operation_ref | None
  receipt_refs[]
  observation_refs[]
  failure_class | None
```

AttemptState 不另存完整 Journal。原有独立 idempotency ledger 应成为 Journal 的索引/投影，不能与 Journal 形成两个可写 dispatch truth。

### 9.2 Side-effect Outbox

副作用或不可安全重试的调用：

```text
1. Validate the leaf ExecutionGrant and confirmation
2. Compile immutable ExecutableInvocation
3. Persist invocation_prepared + outbox entry through DispatchCommit
4. Worker claims outbox entry
5. Append dispatch_started
6. Call Provider with idempotency key
7. Persist remote receipt/status
8. Create Observation
9. Append observation_recorded
```

若 checkpoint store 和 outbox 无法共享本地事务，必须增加明确的 coordinator/recovery protocol；不能用调用顺序假装原子性。

### 9.3 Recovery

| Journal 状态 | 恢复行为 |
| --- | --- |
| `prepared` | 尚未 dispatch，可由 worker 发送 |
| `dispatch_started` | 查询 Provider；仅在幂等保证成立时重试 |
| `remote_accepted` | 使用 remote operation ref poll |
| `remote_completed` | 补写 Observation，不重复 dispatch |
| `outcome_unknown` | reconciliation 或人工处理，禁止盲目重试副作用 |
| `observation_recorded` | attempt 已闭合，不再 dispatch |

目标不是数据库与外部世界的理论 exactly-once，而是：

```text
durable prepared invocation
+ idempotency key
+ remote receipt/status query
+ duplicate suppression
+ reconciliation
= effectively-once side effect
```

不支持 idempotency 和状态查询的 Provider 必须允许 `outcome_unknown` 终态/人工处理，不能声称确定性恢复。

### 9.4 轻量执行路径

满足以下全部条件的调用可以不使用 durable outbox：

- read-only；
- 无外部状态变化；
- 重试不会扩大成本/权限到不可接受范围；
- Provider response 丢失时允许重新执行；
- 不需要长时异步 poll。

轻量路径仍必须持有叶子 ExecutionGrant、记录 Attempt、形成 Observation，并受预算和 Gateway policy 约束。模型调用不复用 ExecutionGrant/ExecutableInvocation；它使用独立的 ModelInvocationGrant 和 Model Runtime adapter，但同样必须记录调用 trace、budget usage、Provider binding 和终止状态。

## 10. 目标模型与当前概念收敛

### 10.1 保留并强化

| 当前模型 | 目标定位 |
| --- | --- |
| `TaskContract` | Task/Goal Definition owner |
| `TaskRuntimeProjection` | Goal runtime owner |
| `PlanDefinition` | Deliberative strategy owner |
| `PlanRuntimeProjection` | Plan runtime owner |
| `ExecutableInvocation` | invocation definition |
| `InvocationAttemptState` | Journal-derived runtime projection |
| `ObservationRef` | 收敛为带 trust/taint/provenance 的 `Observation` |
| `VerificationReport` | criterion 接受结果 |
| `RunCheckpoint` | substate 组合，不是业务 aggregate |

### 10.2 新增

| 模型 | 类型 | 用途 |
| --- | --- | --- |
| `TaskIntakeState` | Checkpoint Substate | Task 建立前的 durable admission |
| `CoordinationAssessment` | Decision | reactive/deliberative 判断 |
| `ExecutionRoute` | Value Object | Action/Step 执行路径 |
| `ExecutionRouteDecision` | Decision | RouteAdmission 接受的最终路径 |
| `ControlPhase` | Enum | control turn durable resume anchor |
| `ControlTurnState` | Checkpoint Substate | control turn 恢复现场 |
| `ModelCallIntent` | Command | 声明一次模型调用 purpose/requirements |
| `SkillActivationRequest` | Command | 模型调用前请求 Skill |
| `SkillActivationDecision` | Decision | 记录 discovery、admitted Skills 或 no_skill_required |
| `SkillContextGrant` | Contract | 指定 model purpose 的 Skill 上下文授权 |
| `ModelInvocationRequest` | Command | 请求模型、Provider、egress 与预算 |
| `ModelInvocationGrant` | Contract | 一次模型调用的不可复用授权 |
| `ModelInvocationOutcome` | Union | TypedProposal/ContextGap/typed failure |
| `CapabilityPortfolioView` | View | contextual/execution 能力发现视图 |
| `ContextCapabilityAvailabilityProjection` | Projection | Skill availability owner |
| `ContextCapabilityAvailability` | Projection Item | Skill content/integrity/trust 可用性 |
| `ExecutionCapabilityAvailabilityProjection` | Projection | Provider-backed availability owner |
| `ExecutionCapabilityAvailability` | Projection Item | Provider/credential/health 可用性 |
| `ExecutionCapabilityRequest` | Command | Action 的执行能力请求 |
| `CapabilityResolutionDecision` | Decision | discovery snapshot、候选与选择结果 |
| `AtomicCapabilityGrant` | ExecutionGrant | Atomic dispatch 授权 |
| `ProcedureGrant` | ExecutionGrant | exact Procedure start 与 permission envelope |
| `ProcedureNodeGrant` | ExecutionGrant | exact Procedure node dispatch 授权 |
| `DelegationGrant` | ExecutionGrant | exact child Agent start 授权 |
| `GrantDependencySet` | Value Object | Grant 精细 fencing 依赖 |
| `CapabilityAcquisitionRequest/Outcome` | Command/Decision | 能力补齐 |
| `EvidenceAdmissionDecision` | Decision | Observation 到 Evidence 的准入 |
| `InvocationJournalEvent` | Event | 外部 dispatch canonical facts |
| `CapabilityExecutionOutcomeEvent` | Event | 技术执行结果 |
| `CapabilityEffectivenessEvent` | Event | 验证后的 Goal 效果 |
| `GovernanceSnapshotRef` | Value Object | Admission 输入快照 |
| `AdmissionDecision` | Decision | verdict/effective constraints/proof |

### 10.3 删除或替换

- `PlanningMode` 更名为 `CoordinationMode`，删除 `procedural` 值；
- `PlanningModeAssessment/Policy` 更名为 `CoordinationAssessment/Policy`；
- Procedure applicability 生成 ExecutionRoute constraint，不生成 CoordinationMode；
- `ExecuteMetaCapabilityDecision` 更名为 `ExecuteBoundedActionDecision`；
- `BoundedAction.meta_capability` 更名为 `execution_intent`；
- 从 ControlDecision 删除基础 `ActivateSkillDecision`；
- Skill 和 Model Invocation 从通用 Action CapabilityRequest/Grant 中移出；
- 删除具体通用 `CapabilityGrant`，Gateway 只接受封闭 ExecutionGrant union 的合法叶子；
- `ChildCapabilityGrant` 更名并收敛为 `ProcedureNodeGrant`；
- 删除 `InvocationIntent`，统一为 AcceptedCommand -> ExecutableInvocation；
- 删除 Request 中的 discovery revision/candidate 镜像，结果归 CapabilityResolutionDecision；
- 删除未分型、依赖空字段的 CapabilityAvailability；
- `CapabilityOutcomeEvent` 拆为 ExecutionOutcome/Effectiveness；
- `TaskLifecycle.stopped` 替换为 `terminated + TaskTerminationReason`；
- 分散 Intake 字段收敛到 TaskIntakeState；
- 独立可写 idempotency ledger 收敛为 InvocationJournal projection/index；
- 授权相关 raw dict、空 identity 和同 Goal fallback grant 全部删除。

## 11. 包与依赖方向

建议结构：

```text
personal_agent/
├─ kernel/primitives/
│  ├─ identity.py
│  ├─ reference.py
│  ├─ revision.py
│  ├─ time.py
│  └─ result.py
├─ runtime/
│  ├─ contracts/
│  │  ├─ intake.py
│  │  ├─ task.py
│  │  ├─ planning.py
│  │  └─ control.py
│  ├─ intake_runtime.py
│  ├─ task_runtime.py
│  ├─ coordination.py
│  ├─ planning_runtime.py
│  └─ control_runtime.py
├─ capabilities/
│  ├─ contracts/
│  │  ├─ skill.py
│  │  ├─ model.py
│  │  ├─ execution.py
│  │  ├─ availability.py
│  │  └─ grants.py
│  ├─ portfolio.py
│  ├─ skill_activation.py
│  ├─ model_resolution.py
│  ├─ applicability.py
│  ├─ availability.py
│  ├─ resolver.py
│  ├─ acquisition.py
│  └─ outcomes.py
├─ governance/
│  ├─ contracts/
│  │  ├─ admission.py
│  │  ├─ evidence.py
│  │  └─ policy.py
│  ├─ taxonomy.py
│  ├─ profiles.py
│  ├─ task_admission.py
│  ├─ plan_admission.py
│  ├─ decision_admission.py
│  ├─ model_invocation_admission.py
│  ├─ execution_invocation_admission.py
│  ├─ route_admission.py
│  ├─ evidence_admission.py
│  └─ outcome_admission.py
├─ execution/
│  ├─ contracts/
│  │  ├─ invocation.py
│  │  └─ journal.py
│  ├─ invocation_journal.py
│  ├─ dispatch_outbox.py
│  ├─ reconciliation.py
│  ├─ model_runtime.py
│  └─ provider_ports.py
├─ verification/
│  ├─ contracts/
│  │  └─ reports.py
│  ├─ goal_verifier.py
│  └─ completion_verifier.py
├─ application/protocols/
│  ├─ task_intake.py
│  ├─ model_invocation.py
│  ├─ control.py
│  ├─ execution.py
│  └─ result_acceptance.py
└─ orchestration/
   └─ graph/checkpoint/interrupt composition only
```

目录不是目标本身。只有文件混合多个 owner 或依赖方向错误时才移动。一个类型只有在脱离所属领域后仍有稳定、独立语义，才能进入 kernel；TaskContract、PlanDefinition、ProcedureGrant、EvidenceAdmissionDecision 等领域模型不得为了共享方便下沉。

禁止结构与依赖：

- kernel primitive 包含 Task/Plan/Capability/Grant/Evidence 等领域语义；
- kernel primitive 依赖 Provider；
- Runtime 读取 Capability/Governance 具体 repository；
- Capability 写 Task/Plan projection；
- Governance 调用 LLM 生成业务 Proposal；
- Execution 改 Task/Plan contract；
- Provider Adapter 读取整个 RunCheckpoint；
- Orchestration 重新实现 Admission；
- 业务模块直接调用 LLM SDK/LlmClient，绕过 Model Invocation Protocol；
- Child Agent 获得父 Runtime object 或完整 credential。

## 12. 端到端示例

任务：“检索最新资料，验证后更新知识库。”

### 12.1 Intake 与 Task

若“最新资料”范围不清晰，TaskIntakeState 创建 InteractionRequest 并 durable interrupt。补充后 TaskAnalyzer 通过 Model Invocation Protocol 生成新 Proposal revision，GoalGraphCompiler 固化两个 Goal、依赖、criteria、MutationIntent 和 receipt contract；TaskCompilationCommit 原子写入 Task、initial runtime、`compiled_task_ref` 和 checkpoint。

### 12.2 协调与路由

两个 Goal 存在依赖，因此 `CoordinationMode=deliberative`。Plan 包含两个 step：

```text
检索验证 step  -> RouteProposal=atomic/delegated
知识写入 step  -> RouteProposal=procedure
```

RouteAdmission 对每个 Accepted Action 产生最终 ExecutionRouteDecision，不再把整个 Task 标为 procedural。

### 12.3 Skill 与模型调用

Planner/Executive 模型调用前，SkillActivationRequest 发现证据研究 Skill，SkillAdmission 产生仅用于该 purpose 的 SkillContextGrant。ModelInvocationAdmission 再选择满足结构化输出要求的 Model/Provider，限制敏感上下文外发、region、token 和 cost，产生一次性 ModelInvocationGrant；Context Gateway 只投影 activation decision 与适用 Grant 共同允许的内容。

### 12.4 检索能力

Accepted read Action 与 RouteDecision 生成 ExecutionCapabilityRequest。Resolver 完成 hard match、availability、policy 和 ranking，在 CapabilityResolutionDecision 中记录 discovery snapshot，并产生只允许 search/read 的 AtomicCapabilityGrant。执行结果先形成 untrusted Observation，经 scoped Evidence Admission 后才能参与 Goal Verification。

### 12.5 Procedure 与副作用

写入 Goal ready 后，mandatory Procedure 约束 RouteDecision。外层 ProcedureGrant 绑定 exact procedure version 和 permission envelope；每个写入 node 产生 ProcedureNodeGrant。确认后 InvocationCompiler 生成 ExecutableInvocation，DispatchCommit 将 `invocation_prepared`、Outbox 和 checkpoint 一起持久化，再 dispatch。成功 receipt 经 reconciliation 和 scoped Evidence Admission 后验证 Goal。

### 12.6 完成

GoalVerifier 接受全部 required criteria 后，CompletionVerifier 接受 CompletionClaim，Task 才进入 completed。任何 Tool success、child artifact 或 acquisition success 都不能直接完成 Goal。

## 13. 落地顺序

每阶段先定义 golden/eval case，再修改代码。阶段内直接切换全部调用方，不保留旧模型 alias 或双写。

### Phase 0：固定 Baseline

交付：

- reactive/deliberative、atomic/delegated/procedure 各有 canonical trajectory；
- read、mandatory mutation、capability gap、entry clarification、crash-window 各有 golden case；
- 固定 hermetic suite 和关键多 trial eval baseline。

### Phase 1：Runtime Protocol 与提交语义收敛

交付：

- 固化 Task Intake、Model Invocation、Control、Execution、Result Acceptance 五条协议边界；
- 引入 TaskIntakeState、ControlPhase、ControlTurnState、RuntimeDisposition；
- `PlanningMode` 拆为 CoordinationMode + ExecutionRoute；
- 引入 RouteProposal/ExecutionRouteDecision，Orchestration 不再猜 route；
- clarification/run control/acquisition request 归属 Runtime；
- 重命名 ExecuteBoundedActionDecision/execution_intent；
- 从 ControlDecision 删除基础 ActivateSkillDecision；
- terminal lifecycle 改为 completed/terminated + typed reason；
- 实现 TaskCompilationCommit 和 ControlCommit 的 CAS/recovery contract；
- orchestration 只调用 Port，不直接写领域 projection。

验收：

- Task 建立前 clarification 可恢复且不制造半成品 Task；
- Intake 不会 compiled 而缺失 compiled_task_ref；
- reactive Procedure 和 deliberative Procedure step 均可表达；
- ControlPhase 能确定性恢复且不复制 Journal 状态；
- terminal Task 不产生新 Action；
- 所有 control outcome 映射到封闭 RuntimeDisposition。

### Phase 2：Model Invocation 与 Context 授权

交付：

- 引入 ModelCallIntent、SkillActivationDecision、SkillContextGrant；
- 引入 ModelInvocationRequest/Grant/Denial；
- Model Provider、region、egress、sensitivity、token/cost 和 structured output 全部进入 admission；
- TaskAnalyzer、Planner、Executive、Monitor、Semantic Verifier 及其他业务 LLM 调用统一接入 Model Invocation Protocol；
- Context Gateway 只接受 Grant refs，不接受业务模块拼装的完整 prompt。

验收：

- Skill 在当前模型 Proposal 之前生效；
- 未授权 Provider、敏感数据外发或预算突破不能调用模型；
- ModelInvocationGrant 不可跨 purpose 或跨调用复用；
- 代码静态检查不存在绕过协议的 LLM SDK/LlmClient 业务调用；
- 模型不可用产生 typed denial/context gap，而不是默认 Provider fallback。

### Phase 3：ExecutionGrant 与 Invocation 正确性

交付：

- 引入 ExecutionCapabilityRequest、CapabilityResolutionDecision、GrantDependencySet；
- 建立 AtomicCapabilityGrant/ProcedureGrant/ProcedureNodeGrant/DelegationGrant 封闭 union；
- 建立 InvocationJournal 和 risk-scoped Outbox；
- 实现 DispatchCommit；
- idempotency ledger 收敛为 Journal projection/index；
- dispatch recovery 支持 receipt query、unknown 和 reconciliation；
- Gateway 只接受与 dispatch 类型匹配的叶子 ExecutionGrant。

验收：

- crash-after-remote-success 不盲目重复副作用；
- stale/revoked Grant 无法 dispatch；
- ProcedureGrant 不能直接授权内部 Tool dispatch；
- 不支持 reconciliation 的 Provider 显式 outcome_unknown；
- 低风险 read fast path 不承担无意义 Outbox 成本。

### Phase 4：Procedure 与 Delegation 权限闭环

交付：

- ProcedureGrant permission envelope；
- 每个 Procedure node 派生 ProcedureNodeGrant；
- DelegationGrant 包含 scope、context、tool、budget、depth 和 completion contract；
- 删除同 Goal fallback resolution；
- child artifacts 默认 unverified。

验收：

- Procedure node/child Agent 无法扩大父授权；
- mandatory Procedure 不可用时 fail closed；
- child 无法读取未授权 Context 或 Tool；
- commit receipt 与 journal/Grant 可追溯。

### Phase 5：Portfolio、Availability 与 Discovery

交付：

- Portfolio 分 contextual/execution entries；
- SkillActivationRequest 只声明 requirements/preference，resolver 拥有 discovery；
- CapabilityResolutionDecision 拥有 discovery snapshot/candidates；
- ContextCapabilityAvailability 与 ExecutionCapabilityAvailability 分型；
- per-entry availability revision 成为 GrantDependencySet 的正式 owner 输入；
- Action resolution 只处理 atomic/delegated/procedure；
- Portfolio revision 仅用于 discovery audit。

验收：

- SkillContextGrant 不获得外部资源权限；
- Request 不镜像 candidate 或 discovery revision；
- 无关能力新增不使现有 Grant 失效；
- unavailable/retired capability 不进入 ranking。

### Phase 6：Governance、Observation 与 Evidence

交付：

- proposal -> AdmissionDecision -> AcceptedCommandCompiler；
- effective constraints、denied fields、monotonicity proof 可审计；
- Observation 增加 provenance/trust/taint/hash；
- EvidenceAdmissionDecision 接入 Context/Verification；
- EvidenceRef 绑定 admitted purpose、criterion scope 和 freshness；
- canonical policy/taxonomy 逐阶段收敛，不一次性建立 MegaValidator。

验收：

- Validator 不静默改 Proposal；
- 外部内容不能成为指令；
- admitted evidence 不被解释为内容为真或 criterion 已满足；
- deterministic floor 不能被 semantic verifier 覆盖；
- 每个 accepted command 可追溯 Proposal、Policy 和 Snapshot。

### Phase 7：Capability Acquisition

交付：

- CapabilityGap -> AcquisitionRequest/Outcome；
- 默认 suggest/user approval；
- 自动 install/connect 具备 allowlist、signature、sandbox 和 rollback；
- acquisition 后基于新 discovery snapshot 重新 resolution。

验收：

- acquisition 不计 Goal progress；
- credential 不进入模型或日志；
- 未审查来源不能自动安装；
- denied/failed acquisition 有明确 Runtime disposition。

### Phase 8：Outcome-aware Ranking

交付：

- 分离 ExecutionOutcome 与 Effectiveness Event；
- 建立跨运行聚合和保留策略；
- 静态 priority 与 outcome ranking 离线对照；
- 无足够样本时保持 deterministic tie-break。

验收：

- ranking 不影响 hard eligibility；
- policy denial、用户取消和任务难度不污染能力质量；
- 排序变化可解释并可回滚到 profile revision。

### Phase 9：删除旧边界并更新当前文档

交付：

- 删除旧 PlanningMode procedural、ActivateSkillDecision、implicit/general grant、InvocationIntent、meta_capability 和重复 state；
- 将 kernel/contracts 收缩为 kernel/primitives + domain-owned contracts；
- 静态测试禁止旧类型/字段回归；
- 更新 current-state、workflow 和 topics 的历史命名；
- future 文档保留为决策记录，不充当当前事实源。

## 14. 测试与 Eval

### 14.1 Hermetic invariants

- Intake revision、interrupt/resume 和 Task creation；
- TaskCompilationCommit、ControlCommit、DispatchCommit crash-window recovery；
- CoordinationMode/ExecutionRoute 正交；
- ControlPhase 合法迁移及其与 Journal truth 的分离；
- 所有模型调用持有 purpose-scoped ModelInvocationGrant；
- SkillContextGrant 与 ModelInvocationGrant 的 context 交集；
- Goal/Plan identity、DAG、revision/CAS；
- leaf ExecutionGrant scope 单调收缩和 dependency fencing；
- Procedure/Delegation child authorization；
- journal/outbox/idempotency/reconciliation；
- Mutation confirmation、exact target、receipt；
- Observation taint 与 Evidence Admission；
- verifier deterministic floor 和 completion exclusivity；
- termination reason 完整性。

### 14.2 Golden trajectories

- 单 Goal read 为 reactive + atomic，不创建 Plan；
- 单 Goal delete 为 reactive + procedure；
- 多 Goal 任务为 deliberative，step 可混合 route；
- Skill 在模型 Proposal 前激活；
- Planner/Executive/Verifier 均通过同一 Model Invocation Protocol；
- 敏感 Context 被 ModelInvocationAdmission 拒绝外发；
- capability gap 触发 acquisition，但不产生 Goal progress；
- Provider 成功后进程崩溃，恢复只补 Observation；
- unknown side effect 进入 reconciliation/人工处理；
- delegated child 越权请求被拒；
- evidence 不足不 false-complete。

### 14.3 Model / trajectory eval

- Goal 拆分与 dependency quality；
- CoordinationMode 成本/收益；
- Plan relevance、horizon 和 replan quality；
- Skill 选择与 trajectory 改善；
- capability soft ranking；
- semantic verification calibration；
- clarification timing；
- task success、turn、模型/Provider 调用和用户打扰次数。

### 14.4 Safety negatives

- 未授权 delete；
- stale Grant dispatch；
- 业务模块绕过 Model Invocation Protocol 直接调用 Provider；
- SkillContextGrant 被误当作模型 Provider/egress 授权；
- ModelInvocationGrant 跨 purpose 或跨 call 复用；
- ProcedureGrant 被用于内部 Tool dispatch；
- Procedure node 超出 permission envelope；
- child Agent 继承父完整 Context；
- confirmation 与 target/action 不一致；
- Provider 自述 trust 被直接接受；
- admitted Evidence 被直接标记为 true/verified；
- Prompt injection Observation 被注入 instruction；
- Tool success 无 receipt；
- semantic verifier 覆盖 deterministic failure；
- Validator 通过改 locator 让非法 Proposal 合法；
- reserved dispatch 无 reconciliation 却被标记成功。

## 15. 可观测与审计

每个 control turn 至少关联：

```text
run/intake/turn id
task/plan revision + cursor
coordination mode + execution route
proposal + admission + accepted command refs
model call + skill context grant + model invocation grant
route decision + leaf execution grant
grant dependency set
invocation journal + remote receipt
observations + evidence admission
verification/completion report
runtime disposition / termination reason
```

指标分组：

### Runtime

- Intake clarification、turn、replan、mode reassessment；
- awaiting_input、pause、completion、termination reason；
- resume/recovery latency。

### Capability

- model binding、egress/region denial、token/cost usage；
- hard denial、availability/credential miss；
- Grant expiry/re-resolution；
- acquisition approval/denial；
- technical outcome 与 effectiveness 分布；
- ranking basis。

### Governance / Execution

- stage admission denial；
- HITL、stale dependency rejection；
- proposal 越权和 monotonicity proof failure；
- journal unknown/reconciliation；
- deterministic floor 拒绝的 false-pass attempt。

日志不得保存明文 credential、完整模型上下文、敏感 Provider payload 或未脱敏 Observation body。

## 16. 架构验收口径

### Agent 如何运行

Agent 先用 durable Intake 将用户请求原子编译成 Task/Goal contract，再通过 reactive 或 deliberative 协调模式进入有界控制循环；所有模型调用经过统一 Model Invocation Protocol，每个 Accepted Action 再由 RouteAdmission 独立决定 atomic、delegated、procedure 或 internal route。执行后产生默认不可信 Observation，经 scoped Evidence Admission 和 Verification 决定继续、重试、重规划、等待输入、终止或完成。

### Agent 如何管理能力

Portfolio 提供 Skill、Model 和执行能力的统一发现视图，但使用协议分离：SkillContextGrant 控制注入内容，ModelInvocationGrant 控制模型/Provider/egress/cost，Accepted Action 通过 ExecutionCapabilityRequest 获得与 dispatch 类型匹配的叶子 ExecutionGrant。Procedure node 和 delegated child 只能使用父授权派生的 ProcedureNodeGrant/DelegationGrant，任何后续阶段都不能扩权。

### Agent 如何保持确定性

LLM 只通过受授权的 Model Invocation 产生 typed Proposal；Stage Admission 生成显式 constraints/proof，AcceptedCommandCompiler 才能建立 Command/Event。Task、Control、Dispatch 具有明确 commit/CAS/recovery 边界；副作用通过 Journal、Outbox、idempotency、receipt 和 reconciliation 实现 effectively-once，未知结果保持 unknown。Observation 不等于事实，Evidence admitted 不等于内容为真，Tool success 不等于 Goal success，CompletionVerifier 独占 Task completed 转换。

若代码、测试和当前架构文档无法同时支持这三段描述，则本设计尚未完成。

## 17. 最终约束

- 不把 CoordinationMode 与 ExecutionRoute 再次合并；
- 不把 Skill activation 与 Action resolution 再次统一；
- 不让任何模型调用绕过 Model Invocation Protocol、ModelInvocationGrant 或 Context Gateway；
- 不把 SkillContextGrant 当作模型 Provider/egress/cost 授权；
- 不把基础 ActivateSkillDecision 放回 ControlDecision；
- 不引入可执行所有 dispatch 的具体通用 CapabilityGrant；
- 不让 Procedure/Delegation 继承隐式父权限；
- 不用 ControlPhase 复制 InvocationJournal 的远端状态；
- 不用 checkpoint status 冒充外部 dispatch 真相；
- 不宣称无法证明的 exactly-once；
- 不把 Observation 当可信指令或已确认事实；
- 不把 Evidence admitted 解释为内容为真或 criterion 已满足；
- 不让 Validator 静默修改 Proposal；
- 不用全局 revision 制造无关 Grant 失效；
- 不把领域 Contract 下沉到共享 kernel 类型仓库；
- 不为统一建立 MegaValidator、MegaState 或通用 execute(dict)；
- 不为兼容保留新旧字段、alias、双写或无限 deprecated path；
- 无法说明 owner、输入、产物、失败语义和业务不变量的模型不得进入实现。

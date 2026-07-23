# personalAgent 当前核心架构

本文描述已经落地的 Agent 主链。组织方式是先说明每个模块解决什么业务问题，再说明模块之间通过什么协议协作；它不是代码调用顺序的逐行翻译。

架构声明的 live E2E 证据、边界和暂不纳入核心主链的集成，见
[`core-architecture-e2e-audit.md`](core-architecture-e2e-audit.md)。产品能力目录、Tool /
MCP / A2A 当前事实和可信发布基线见
[`phase0-capability-release-baseline.md`](phase0-capability-release-baseline.md)。

旧 E01–E17 只证明其 catalog 标注的架构边界或 Capability Profile，不等于新产品能力
E01–E13。当前可信原生产品能力与组合能力基线均为空；任何实现、配置或历史 trace 都
不能绕过同 revision release gate 扩大该声明。

## 1. 架构要回答的三个问题

一个可持续演进的 Agent 必须同时回答：

1. **如何运行**：如何把用户目标推进为可验证结果，并在失败、暂停和恢复后继续。
2. **用什么能力**：如何发现、筛选并授权 Tool、MCP、Procedure、Model 和 child Agent。
3. **如何保持确定性**：如何限制概率模型的权力，使写操作、证据和完成判断可审计、可恢复。

当前工程用三个控制面回答这三个问题：

| 控制面 | 负责 | 不负责 |
| --- | --- | --- |
| Runtime Plane | Goal、短期计划、单轮控制、运行状态和恢复 | 直接信任模型输出、选择未经授权的 provider |
| Capability Plane | 能力目录、实时可用性、解析、排名、授权和获取 | 修改 Goal、宣布任务完成 |
| Governance Plane | 提案准入、Policy、Confirmation、Evidence admission、Verification | 生成业务策略、代替执行器执行操作 |

“控制面”表示它掌握某类决策的唯一写入口，而不是三个独立部署的服务。好处是职责冲突可以被协议拒绝：Executive 可以提出动作，但 Capability Plane 决定谁能做，Governance Plane 决定是否允许做，Verifier 决定结果是否完成 Goal。

## 2. 统一模型语义

核心模型遵循五种角色：

```text
Definition  不可变的业务要求
Command     已获准的一次有界变更请求
Event       已经发生的事实
Projection  由事实投影出的可恢复当前状态
View        读取时组合多个 owner，不保存新事实
```

全局开发准则是高内聚、低耦合、不过度设计：同一事实只有一个 owner；可推导值不重复持久化；不保留新旧模型兼容层；校验器拒绝冲突，不负责同步副本；空字符串和裸字典不能充当身份、授权或状态。

包依赖由 `scripts/check_layers.py` 按显式 DAG fail closed 检查。未知包、未声明边、缺失包和循环依赖都会使 CI 失败。

## 3. Task Analysis：只理解，不执行

`TaskAnalyzer` 位于用户自然语言和正式任务契约之间，输出 provider-neutral 的 `TaskAnalysisProposalBody`。系统将它封装为绑定输入摘要的 `TaskAnalysisProposal`，经 `TaskAnalysisAdmission` 检查 provenance、revision lineage 和 user-explicit identity grounding，只有 accepted proposal 才编译为 `AcceptedTaskAnalysis`。

criterion 和 constraint 都显式携带 `user_explicit/model_inferred` origin；模型声称 user-explicit 时必须给出逐字 source、digest 和字段引用。准入只拒绝并产生 `DecisionFeedback`，不会替模型补语义；grounding-only 修订不得改变 Goal、criterion、constraint 或 relation。完整尝试链保存在 `TaskAnalysisAttempt[]`，最终唯一语义 owner 是 `AcceptedTaskAnalysis.analysis`。

实现：`planning/task_analyzer.py`。

## 4. GoalGraphCompiler：把概率提案变成可信任务定义

`GoalGraphCompiler` 是已接受语义与确定性运行时之间的编译边界。输入是 `AcceptedTaskAnalysis.analysis`，输出是 `GoalCompilation`：

```text
AcceptedTaskAnalysis.analysis
  -> TaskContract
  -> 初始 TaskRuntimeProjection
  -> ContextInventory
```

实现：`planning/task_compiler.py`。

### 4.1 为什么需要编译，而不是直接执行分析结果

LLM 擅长理解语义，但不适合拥有身份分配、依赖合法性、Mutation 分类和完成标准的最终决定权。Compiler 将这些规则集中为可测试的确定性步骤，使后续模块面对的是合法契约，而不是各自修补模型输出。

### 4.2 Compiler 实际完成的设计职责

**建立稳定身份和拓扑。** Compiler 校验 Goal ID 唯一、依赖端点存在、关系不重复、自依赖不存在、阻塞依赖无环。`goal_id` 是 Goal 定义、运行状态、Action、Observation、Procedure 和 Verification 的关联键；悬空或循环身份会让任务永远无法收敛，所以必须在运行前拒绝。

**固化资源归属。** `ResourceHint` 是 Analyzer 的语义猜测，Compiler 将其规范化为 `ResourceRequirement`。Requirement 不保存 `goal_id`：Goal 局部资源放在 `GoalDefinition.resources`，任务共享资源放在 `TaskContract.shared_resources`。归属由聚合结构表达，避免叶子对象和外层对象同时维护 identity。

**建立 canonical Mutation taxonomy。** Compiler 将 create、update、delete、ingest、repair 归一为 Mutation operations。这不是为了多做一次标签转换，而是让 Confirmation、Procedure、Policy、Receipt 和 Verifier 使用同一套副作用语言。如果跳过归一化，每个 Tool 的 `save/write/persist/apply` 都会各自解释风险，治理无法统一。taxonomy 在这里表示“受控分类体系”。

**保留成功标准 provenance。** Analyzer 必须显式提出至少一条 success criterion，Compiler 不再从 description/user_goal 拼接业务标准。`user_explicit` 与 `model_inferred` 分别编译为 `user_explicit` 与 `model_derived`；只有 mutation receipt 这类稳定协议不变量由 Compiler 追加为 `contract_derived` criterion。

**确定结果契约。** 单 Goal 使用其结果类型；多种结果并存时，Task 的 `result_contract=compound`，表示任务只有在多个 Goal 各自满足其输出与 criteria 后才完成，而不是返回一个任意字符串就算结束。

**原子建立定义与初始状态。** `TaskCompilationCommitter` 用 proposal revision 做 CAS，一次提交 `TaskContract`、初始 `TaskRuntimeProjection` 和 `TaskCompilationCommit`。无阻塞依赖的 Goal 初始为 active，有阻塞依赖的 Goal 为 pending。

### 4.3 Compiler 不做什么

Compiler 不选择协调模式、不生成短期计划、不绑定 provider、不批准写操作，也不判断运行结果是否成功。若某项逻辑无法解释为“建立任务不变量”，它就不应放进 Compiler。

## 5. TaskContract 与 TaskRuntimeProjection：要求和进度分治

`TaskContract` 是整个任务的不可变 Definition，回答“必须完成什么”：

```text
TaskContract
├─ task_id / revision / user_goal / result_contract
├─ constraints / mutation_intent / evidence_requirements
├─ shared_resources
└─ GoalGraphDefinition
   └─ GoalDefinition[]
      ├─ description / result_contract
      ├─ resources / criteria / constraints
      └─ dependencies
```

`TaskRuntimeProjection` 是运行投影，回答“当前推进到哪里”：

```text
TaskRuntimeProjection
├─ task_id / task_revision / lifecycle / event cursor
└─ goal_states{goal_id -> GoalRuntimeState}
   ├─ status / attempts
   ├─ evidence gaps / coverage
   └─ verification_ref / replan reason
```

两者不是两份“整个任务状态”。Contract 拥有 Goal 的定义字段；Runtime 只拥有会随执行变化的字段，不复制 description、resource、criterion 或 dependency。

`materialize_goals(task, runtime)` 先校验 task identity、revision 和 Goal 集合完全一致，再生成只读 `MaterializedGoalView`。需要这一步，是为了让调用方获得一个一致视图，而不让每个模块自行 join、遗漏 revision fencing，或把 View 变成第三个事实 owner。

`task.resources_for_goal(goal_id)` 是有效资源的唯一读取入口：返回共享资源与该 Goal 局部资源；未知 Goal fail closed。这里的资源是任务运行要访问的业务对象或边界，例如 workspace、repository、document、web source、external account 及其允许操作，不是具体 Tool 实例。

Goal status 中，`verified` 表示已通过验收，`degraded` 表示按明确的降级终止规则关闭，`abandoned` 表示不再追求。调度器跳过这些终态，因为继续为它们生成 Action 会重复副作用或浪费预算。Task 是否完成则由 CompletionVerifier 根据所有必需 Goal 的状态和报告统一判断。

实现：`runtime/contracts/task.py`、`runtime/task_runtime.py`、`runtime/commits.py`。

## 6. Coordination 与 Adaptive Planning：决定是否需要短期策略

`CoordinationMode` 只有 `reactive` 和 `deliberative`。它回答“当前是否值得维护短期计划”，不回答“使用什么执行技术”。

- `reactive`：一个有界下一动作可能安全推进 Goal。
- `deliberative`：多 Goal、依赖、证据路径或不确定性需要短 horizon 计划。

Procedure、native tool、ReAct 和 delegation 属于 `ExecutionRoute`，不再混入 mode。一次 deliberative Plan 的某个 step 完全可以路由到这些执行方式；因此“deliberative 包含其他处理”是正常组合，不是模式嵌套。

只有 deliberative 会创建 `PlanDefinition`。`AdaptivePlanner` 生成 provider-neutral 的语义步骤和 `CapabilityRequirement`，不写具体工具名。`FrontierSelector` 选择依赖已满足的 step；`PlanMonitor` 根据新 Observation 判断保持计划、局部重试、step invalidation 或 branch invalidation；只有受影响部分通过 CAS patch 更新，避免每轮重做整份计划。

实现：`planning/adaptive.py`。

## 7. Executive Control：每轮只推进一个有界决策

`ExecutiveController` 读取 materialized Goal、当前 Observation、Plan frontier、预算、Procedure candidate 和能力类别摘要，输出 `ControlProposal`。它优化的是“下一步最可能让哪个开放 Goal 接近验收”，不是一次生成完整 Workflow。

可提议的决策包括 clarify、execute bounded action、delegate、invoke procedure、request confirmation、request capability acquisition、finish 和 terminate。

模型只能产生 `ControlProposal`。`DecisionValidator` 根据 Task revision、Goal 状态、grounding、资源范围、Mutation/confirmation、预算和 route 约束生成 `StageAdmissionDecision`。拒绝产生限制 mutable/immutable fields 与 revision scope 的 `DecisionFeedback`；只有 accepted proposal 才由 `AcceptedIntentCompiler` 逐字冻结为 `AcceptedIntent`，再由 `ExecutionCommandResolver` 推导 immutable `ResolvedExecutionCommand`。

`ControlCommitter` 将 proposal、admission、AcceptedIntent、初始 Command 与 runtime cursor 作为同一条 CAS 链提交。Command 不可覆盖；provider rebinding 必须创建 superseding Command。Confirmation 绑定 `AuthorizationDigest`，Grant、Journal 和 Receipt 绑定更细的 `ExecutionCommandDigest`。

实现：`runtime/control_runtime.py`、`governance/decision_admission.py`、`runtime/commits.py`。

## 8. Capability Plane：从业务需要到一次性执行授权

Capability Plane 分成四层：

1. `Capability` 描述能力是什么，包括 kind、operations、semantic domain、resource types、provider、风险和 binding metadata。
2. `ExecutionCapabilityAvailability` 描述此刻是否可用、credential 是否就绪、provider binding revision 和健康观测时间。
3. `CapabilityResolver` 将 `CapabilityRequirement` 与资源范围、Policy、实时可用性和历史结果比对，生成显式 resolution decision。
4. `CapabilityGrantIssuer` 只在 provider-bound superseding Command 已持久化后签发 `ExecutionGrant`。

Resolver 只有在 output contract、side-effect class、authority scope、data egress、evidence contract、failure semantics、trust floor 和 freshness contract 全部满足同一 `CapabilityEquivalenceClass` 时才允许绑定。排名只能在该等价类内部优化成本、延迟或健康度；语义不同候选不能用 aggregate score 选“最接近”的一个。

远程能力在没有实时 availability observation 时 fail closed。只有 system metadata 且无需 credential 的本地能力可在无观测时视为可用。能力缺失不会硬选最相似工具：尚未形成可执行 Proposal 时，Executive 直接提出并持久化 `CapabilityAcquisitionRequest`；已接受 Action 在解析时发现缺口，则产生 `CapabilityGapObservation` 再回到控制面。批准 acquisition 只表示允许获取，不能冒充新的 availability 或 provider binding。MCP、A2A 等具体远程 adapter 的生产主链资格仍取决于各自的 live E2E。

`runtime_meta` 是 Capability 的运行约束，不是业务能力本身：它描述 provider binding revision、credential mode、执行环境、并发/超时、成本和健康信息，供 Resolver 与 Gateway 在执行前再次核对。

实现：`capabilities/contracts`、`capabilities/portfolio.py`、`capabilities/resolver.py`、`capabilities/acquisition.py`。

## 9. Execution Route 与 Gateway：授权和执行分开

Route admission 只校验 AcceptedIntent 推导出的原子 Tool、Procedure、ReAct 或 child Agent route，不重新解释业务语义。能力选择先产生 provider-binding `DerivationRecord`，随后生成并持久化 superseding Command，最后才签 Grant；Procedure node 也拥有自己的 provider-bound Command 和 digest。

`ToolGateway` 和 `AgentGateway` 是最终执行门：它们要求 invocation/node 与 grant 精确绑定，复核 capability/provider/resource/operation，执行 commit-time policy，并记录审计。Procedure 的 Mutation node 在用户确认后会获得新的 confirmation-bound grant；幂等键不能冒充 confirmation reference。

Procedure 用于封装稳定事务不变量，例如 prepare、confirm、commit、receipt。它不是 Planning mode，也不是普通 prompt 模板。`ProcedureApplicabilityResolver` 比较当前 Goal 的有效资源与 Procedure 声明的 domain/type/operation：只有能覆盖要求的 Procedure 才是 candidate，mandatory Procedure 会阻止 Executive 绕过事务路径。

当前 `knowledge_delete` 核心路径只接受用户输入中已显式给出的 canonical note ID：Procedure 只校验该 ID 在当前用户 scope 内存在，再等待 confirmation。按标题、相似度或图谱候选选择删除目标的旧路径已移除；在存在可 Gateway 绑定的 `DeletionCandidates` provider、完整等价类和专项 live E2E 前，它不能作为删除主链能力。

`InvocationJournal` 在 provider 调用前原子写入 reserved journal entry 与 prepared outbox；dispatch 后转为 dispatched，观察结果后转为 observed。相同 idempotency key 和 revision 通过 CAS 防止重复副作用。一次任务会有多个 invocation，因此 Journal 保存多个 item；每个 Goal 也可能经历搜索、转换、写入和验证等多次执行。

实现：`execution/`、`governance/gateway.py`、`runtime/procedure_runtime.py`、`agents/gateway.py`。

## 10. Context Gateway：控制模型到底看见什么

Context Gateway 是模型输入的唯一边界，因为“运行时拥有很多数据”不等于“每次 LLM 都应看到全部数据”。它按 purpose、snapshot 和 token budget 从 `ContextInventory` 生成 `ContextProjection`，显式记录 selected、omitted、selection reason 和 projection id；Materializer 只展开 projection 引用的 item，并区分可信 instruction 与不可信 content。

Agent 主链的模型调用使用审计后的 `ContextProjection.projection_id`。边界明确、完整输入就是 message list 的应用服务使用 content-addressed `sealed-context` 引用；任何可见内容变化都会改变 hash。`StructuredModelRequest.context_projection_ref` 必填，空值和旧的 `inline:*` 绕过会被拒绝。所有 structured 与 streaming 调用都必须经过 governed model client，形成 call intent、skill context decision 和一次性 model invocation grant。

因此 Context Gateway 管理的是“进入模型的上下文投影和可信度”，不是替代 Memory、Task 或 Runtime 成为所有原始数据的 owner。

实现：`context/`、`capabilities/contracts/model.py`、`capabilities/model_resolution.py`。

## 11. Observation、Monitor 与 Verification：反馈、调路、验收分离

三者处理同一执行结果的不同问题：

- `ObservationRef`：发生了什么。它包含 goal、provenance、trust、taint、summary 和 artifact refs，是运行反馈事实。
- `PlanMonitor`：这件事是否使当前短期计划失效。它可以维持、重试或触发局部 patch，但无权宣布 Goal 完成。
- `ExecutionFactVerifier`：receipt、provider、command digest 等机械事实是否成立，输出 `ExecutionFactReport`。
- `GoalVerifier`：已准入证据是否满足 SuccessCriterion，输出独立 `GoalVerificationReport`。

外部 Observation 默认带 `external_content` taint，不能作为 system instruction。进入 semantic verification 前必须经过 `EvidenceAdmission`，得到 purpose 和 criterion scope 有界的 `EvidenceRef`；带不可信 instruction taint 的内容会被拒绝。

Action technical success 只产生 `CapabilityExecutionOutcomeEvent`，说明 provider 是否完成调用。Goal verification 后才产生 `CapabilityEffectivenessEvent`，说明该能力是否真正推进验收。超时、策略拒绝和 credential 缺失不会被误计为能力质量差。

Mutation 不能靠模型文字自证：Verifier 确定性检查 Tool result 中的 `MutationReceipt`。`CompletionVerifier` 再根据所有必需 Goal 的 verification report、completion claim 和终止规则判断 Task lifecycle。

实现：`runtime/contracts/control.py`、`governance/evidence_admission.py`、`verification/runtime.py`、`capabilities/outcomes.py`。

## 12. Orchestration 与 RunCheckpoint：组织流程，不拥有业务事实

Orchestration graph 串联 compile、coordinate、control、admit、resolve、dispatch、observe、monitor 和 verify 节点。`RunCheckpoint` 保存恢复所需的引用和子状态，包括 Task definition/runtime、control commits、invocation journal/outbox、evidence admissions、verification reports、Procedure/Agent run 和 interrupt 信息。

Checkpoint 是恢复容器，不应复制 Goal definition。`Decision Audit Store` 保存 Proposal/Admission/Feedback，`Command Store` 保存 immutable Command，`canonical_domain_events` 保存已提交执行事实，`agent_trace_events` 只保存运行解释；四者不能互相冒充 canonical owner。

Action 由 Executive 提出，经 admission 和 resolution 后，由对应 Gateway 交给 Tool executor、Procedure runtime 或已获得专项 live E2E 的 provider route 执行。Graph 本身不绕过 Gateway 直接调用 provider。没有专项 live E2E 的 ReAct、Agent provider、MCP route 和 capability acquisition 不应视为主链组成部分。

实现：`orchestration/orchestration_graph.py`、`orchestration/orchestration_nodes/`、`orchestration/orchestration_models.py`。

## 13. 一次任务如何闭环

```text
用户输入
  -> TaskAnalyzer 产生 TaskAnalysisProposalBody
  -> TaskAnalysisAdmission -> AcceptedTaskAnalysis
  -> GoalGraphCompiler 建立 TaskContract + 初始 Runtime
  -> CoordinationMode 决定 reactive 或 deliberative
  -> Executive 产生 ControlProposal
  -> Governance admission -> AcceptedIntent -> 初始 ResolvedExecutionCommand
  -> CapabilityResolver 仅选择完整等价 provider
  -> superseding provider-bound Command 持久化
  -> CapabilityGrantIssuer 按最终 ExecutionCommandDigest 签 Grant
  -> Gateway + InvocationJournal 执行
  -> Receipt / Observation 记录发生的事实
  -> EvidenceAdmission 限定可用于语义验收的证据
  -> ExecutionFactReport 与 GoalVerificationReport 分层验收
  -> PlanMonitor 根据 Observation 调整短期策略
  -> CompletionReport
  -> FinalAnswerProposal / Admission
```

这不是固定流水线：reactive 可跳过 Plan；缺少完整能力等价类会进入 acquisition pause 或由 Capability gap 回到 Executive；Mutation 进入 confirmation-bound Procedure；Observation 可触发局部 replan；interrupt 后从 Checkpoint 恢复。但任何执行分支都不能跳过 Proposal/Admission/Grant/Gateway/Verification 的权责边界。

## 14. 当前架构不变量

- Goal 定义只属于 `TaskContract`，运行状态只属于 `TaskRuntimeProjection`。
- Definition 与 Runtime 的 task identity、revision、Goal 集合必须一致。
- `goal_id` 是跨模块关联键，但不是所有叶子模型都重复保存的字段。
- 模型输出永远是 proposal，不是权限、事实或完成证明。
- ExecutionGrant 只能缩小，且必须绑定最终 provider-bound `ExecutionCommandDigest`。
- 无实时可用性证据的远程能力 fail closed。
- Mutation 必须有 confirmation、commit-time policy 和 receipt。
- Observation 必须带 typed provenance/trust/taint；Evidence 必须经过 purpose-scoped admission。
- Action success 不等于 Goal success；Goal success 不等于 Task completion。
- Journal 与 outbox、Proposal 与 Admission/Command 均使用原子 commit 和 CAS fencing。
- 包依赖只能沿显式 DAG，禁止循环和兼容重导出。

## 15. 主要代码入口

| 关注点 | 路径 |
| --- | --- |
| Task Analysis / Compile | `planning/task_analyzer.py`、`planning/task_compiler.py` |
| Task / Goal contracts | `runtime/contracts/task.py` |
| Coordination / Adaptive Plan | `planning/adaptive.py` |
| Executive Control | `runtime/control_runtime.py` |
| Admission / Evidence | `governance/decision_admission.py`、`governance/evidence_admission.py` |
| Capability management | `capabilities/` |
| Invocation / outbox | `execution/` |
| Procedure runtime | `runtime/procedure_runtime.py` |
| Context boundary | `context/` |
| Verification | `verification/runtime.py` |
| Graph / checkpoint | `orchestration/` |
| Architecture gate | `scripts/check_layers.py`、`scripts/check_agentic_architecture.py`、`.github/workflows/architecture.yml` |

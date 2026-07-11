# 知识 Agent 元能力组合目标设计

## 定位

本文只定义知识 Agent 的目标架构，不描述当前实现状态、兼容方案或历史落地阶段。当前事实以 [知识 Agent 元能力运行时当前状态](../summary/agentic-meta-capability-current-state.md) 为准；Capability、MCP 与 A2A 的治理边界以 [全局 Capability Scoping 设计](global-capability-scoping-design.md) 和 [Agent Gateway 与 A2A 设计](agent-gateway-a2a-design.md) 为准。

目标不是继续增加 Capture、Ask、Research、MCP 等命名 workflow，而是建立一个持续围绕用户目标工作的受治理执行体：它能够拆解目标、发现能力缺口、选择下一步动作、观察结果、修订计划、验证结论，并在需要时调用确定性领域协议。

> Agentic 的核心不是一次选中正确流程，而是在约束内持续判断下一步，直到成功标准满足、需要用户介入或任务明确无法继续。

## 设计原则

1. 用户目标是一级对象，intent、provider 和 workflow 名称都不是任务主轴。
2. 主 Agent 在整个 run 中保留目标所有权和最终回答责任。
3. 模型提出下一步控制决策，Runtime 校验并执行；模型不能直接授予权限。
4. 每轮只执行一个有界控制动作，结果进入观察，再决定下一步。
5. Execution Pattern 是可选的计划宏和经验先验，不是一次性路由结果。
6. Skill 提供方法、质量标准和能力偏好，不拥有执行权，也不固定完整步骤图。
7. Native、Retriever、MCP 和 A2A 在统一 capability contract 下满足需求；provider 不决定任务类别。
8. LangGraph 承载 checkpoint、interrupt、恢复和确定性子图，不承担业务意图分类。
9. 高风险、副作用、异步生命周期和事务语义由固定 workflow/state machine 负责。
10. 完成必须由成功标准、证据和 verifier 共同判定，而不是由模型自行宣告。

## 总体架构

```text
User Input
  -> Goal Interpreter
       -> TaskSpec / clarification
  -> Executive Loop
       -> observe ControlState
       -> propose one ControlDecision
       -> Decision Validator
       -> Capability Resolution + Policy Clamp
       -> execute bounded action
       -> admit Observation / Artifact
       -> update ExecutionLedger
       -> revise TaskSpec through Goal Interpreter when required
       -> verify progress and completion
       -> continue / interrupt / finish
  -> EntryResult
```

Executive Loop 可以调用四类执行面：

```text
Meta-capability executor   acquire / explore / reason / verify / transform
Capability runtime        native / retriever / MCP / model tool
Delegation runtime        A2A / isolated subagent
Protocol runtime          capture / commit / delete / research lifecycle / subscription
```

控制面与执行面必须分离：Executive 决定“下一步需要做什么”，CapabilityResolver 判断“哪些实现满足要求”，PolicyEngine 与 Gateway 判断“当前是否允许执行”，具体 executor 负责“如何可靠执行”。

## 核心对象

### TaskSpec

`TaskSpec` 是用户目标的权威结构化表达，不是 Router intent 的包装。

```python
class TaskSpec:
    task_id: str
    revision: int
    user_goal: str
    outcome_kind: str
    subjects: tuple[str, ...]
    resource_requirements: tuple[ResourceRequirement, ...]
    requested_operations: tuple[str, ...]
    constraints: TaskConstraints
    success_criteria: tuple[SuccessCriterion, ...]
    evidence_requirements: EvidenceRequirements
    mutation_intent: MutationIntent | None
    clarification_needed: bool

class SuccessCriterion:
    criterion_id: str
    description: str
    required: bool
    origin: Literal[
        "user_explicit",
        "user_implicit",
        "policy_required",
        "runtime_derived",
        "skill_recommended",
        "macro_recommended",
    ]
    mutability: Literal["immutable", "user_revisable", "runtime_revisable", "derived"]
    evidence_policy: EvidencePolicy
    acceptance_contract: str
```

Goal Interpreter 只负责：

- 提取目标、对象、约束、资源线索和副作用意图；
- 形成可验证的成功标准；
- 识别真正阻塞执行的歧义；
- 接受用户在执行中的修正并生成显式 revision。

它不选择 provider，不选择 Execution Pattern，也不决定完整执行图。旧 intent 可以作为观测或评估标签，但不能成为目标架构的控制条件。

TaskSpec revision 只能由用户输入、明确的澄清结果或 Runtime 可验证事实触发。Executive 可以提出 `TaskRevisionProposal`，但不能静默改变用户目标、删除必要成功标准或把执行失败改写成目标降级；所有 revision 都必须保留前一版本和变更原因。

`origin` 和 `mutability` 用来区分用户承诺、policy 要求与执行过程中派生的操作标准。`user_explicit` 和 `policy_required` 默认不可由 Executive 修改；Skill/Macro 推荐的 criterion 只能作为可审计提案，不能伪装成用户要求。Goal Interpreter 对隐含标准不确定时应保留假设或请求澄清，不能为了方便规划而过早锁死任务。

### ControlState

`ControlState` 是 Executive 每轮决策的最小充分视图。它从 checkpointed runtime state 投影而来，而不是把完整历史直接交给模型。

```python
class ControlState:
    task_spec: TaskSpec
    ledger: ExecutionLedger
    context_summary: ContextProjection
    active_skills: tuple[SkillRef, ...]
    available_capability_classes: tuple[CapabilityClassSummary, ...]
    outstanding_evidence_gaps: tuple[EvidenceGap, ...]
    pending_approvals: tuple[ApprovalRef, ...]
    latest_observations: tuple[ObservationRef, ...]
    verification_state: VerificationState
    remaining_budget: Budget
```

只向 Executive 暴露 capability 的语义摘要和当前可用类别。具体工具集合由某个控制动作产生的 `CapabilityRequirement` 再做 scoped resolution，避免把完整 registry 放入模型上下文。

### ControlDecision

Executive 每轮只能返回一个判别联合类型的强类型决策。不同 action 具有不同必填字段，不能使用一个包含大量可选字段的宽松对象：

```python
class DecisionBase:
    target_goal_id: str
    basis: DecisionBasis
    expected_progress: str

class DecisionBasis:
    unmet_criterion_ids: tuple[str, ...]
    triggering_observation_ids: tuple[str, ...]
    evidence_gap_ids: tuple[str, ...]
    expected_state_change: str
    rejected_action_codes: tuple[str, ...]

class ExecuteMetaCapabilityDecision(DecisionBase):
    action: Literal["execute_meta_capability"]
    meta_capability: str
    requirement: CapabilityRequirement

class ExecuteParallelDecision(DecisionBase):
    action: Literal["execute_parallel"]
    parallel_actions: tuple[BoundedAction, ...]

class DelegateDecision(DecisionBase):
    action: Literal["delegate"]
    subtask: SubtaskSpec

class InvokeProtocolDecision(DecisionBase):
    action: Literal["invoke_protocol"]
    protocol_call: ProtocolCall

class RevisePlanDecision(DecisionBase):
    action: Literal["revise_plan"]
    proposed_ledger_patch: LedgerPatch

class FinishDecision(DecisionBase):
    action: Literal["finish"]
    completion_claim: CompletionClaim

ControlDecision = Annotated[
    ClarifyDecision
    | ActivateSkillDecision
    | RevisePlanDecision
    | ExecuteMetaCapabilityDecision
    | ExecuteParallelDecision
    | DelegateDecision
    | InvokeProtocolDecision
    | RequestConfirmationDecision
    | FinishDecision
    | StopDecision,
    Field(discriminator="action"),
]
```

`DecisionBasis` 用于审计和评估，不构成授权依据。系统不要求、保存或评估模型的自由文本思维过程；trace 只记录决策关联的 criterion、observation、gap、被拒动作代码和预期状态变化。Runtime 不执行自由文本计划，只执行经过 schema、状态和 policy 校验的结构化动作。

`execute_parallel` 仍是一个控制决策，但可以启动多个相互独立、只读且预算明确的 `BoundedAction`。Validator 必须证明它们不存在 artifact 依赖、资源写冲突或审批顺序要求；副作用动作和 protocol call 不允许通过该决策并行化。

`BoundedAction` 是一个有明确输入输出和局部自治边界的语义执行单元，不等同于一次底层 API/tool call：

```python
class BoundedAction:
    action_id: str
    meta_capability: str
    input_artifact_ids: tuple[str, ...]
    output_contract: str
    requirement: CapabilityRequirement
    max_tool_calls: int
    max_model_calls: int
    max_iterations: int
    deadline: datetime | None
    read_set: tuple[ResourceRef, ...]
    write_set: tuple[ResourceRef, ...]
    side_effect_class: str
    approval_dependencies: tuple[str, ...]
    protocol_dependencies: tuple[str, ...]
```

Executive 控制动作的任务语义，而 executor 可以在预算内完成多次确定性读取或 scoped ReAct。动作粒度应以“是否需要新的任务级信息才能决定下一步”为边界，不能把每次读取、抽取、格式化都升级为一次 Executive 模型调用。

### ExecutionLedger

`ExecutionLedger` 是真实执行状态的权威来源，取代“一次编译后基本不变的计划图”作为 Agent 的任务控制中心。

```python
class ExecutionLedgerItem:
    goal_id: str
    parent_goal_id: str | None
    description: str
    status: str  # pending / active / blocked / awaiting_input / candidate_complete / verified / degraded / abandoned
    success_criteria: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    input_artifacts: tuple[str, ...]
    output_contract: str
    coverage: tuple[CapabilityCoverage, ...]
    attempts: tuple[AttemptRef, ...]
    replan_reason: str | None

class ExecutionLedger:
    task_id: str
    revision: int
    items: tuple[ExecutionLedgerItem, ...]
    active_goal_ids: tuple[str, ...]
    active_skill_ids: tuple[str, ...]
    applied_macros: tuple[PlanMacroRef, ...]
```

Ledger 的修改必须使用受限 patch：可以拆分未执行目标、增加证据缺口、调整低风险待办、放弃无效路径；不能删除已发生的副作用、伪造完成状态、扩大授权或绕过 protocol 状态机。

`ExecutionPlan` 可以作为 UI 展示、并行依赖校验或 protocol 调用前的临时投影，但不再是整个任务的权威、一次性完整 DAG。每轮只物化已经通过 DecisionValidator 的 bounded action；未来步骤保留为 Ledger goal，不提前绑定 provider 和具体 tool。

Ledger 是当前状态的权威投影，但不是不可追溯的唯一历史事实源。运行时采用：

```text
append-only ExecutionEvent
  -> deterministic projector
  -> ExecutionLedger materialized view
  -> checkpoint snapshot
```

所有 decision、patch、attempt、coverage、verification、approval、protocol transition 和 completion rejection 先写事件，再由 projector 更新 Ledger。checkpoint 用于快速恢复，event stream 用于审计、replay、重建和比较 replan 前后状态；模型不能直接覆盖 Ledger snapshot。projector 必须可重复执行并通过 replay determinism 测试。

Goal 状态与 action/step 状态必须分离。一次工具调用或 `verify` action 执行成功，只能产生 `AttemptResult` 或 `VerificationReport`，不能直接把 goal 标记为 `verified`。合法状态转换为：

```text
pending -> active
active -> blocked / awaiting_input / candidate_complete
blocked -> active / degraded / abandoned
awaiting_input -> active / abandoned
candidate_complete -> verified / active
```

其中：

- `candidate_complete` 表示 Executive 认为已有产物可能满足目标；
- `verified` 只能由 Goal Verifier 根据成功标准和 artifact 写入；
- `degraded` 必须记录未满足标准、原因和用户可见限制；
- `abandoned` 只能由用户取消、目标被显式 revision 替代或 Runtime 判定不可继续触发；
- step 成功、无异常或 verifier 调用完成都不等于 goal 完成。

### ContextEnvelope

模型上下文继续保持分层：

| 层 | 内容 | 控制语义 |
| --- | --- | --- |
| `run_context` | TaskSpec、身份、审批和 Runtime 状态 | Runtime 权威 |
| `working_memory` | Ledger、草稿、工具摘要和临时 artifact | 仅用于当前任务 |
| `trusted_memory` | 经过准入的长期知识和策略 | 可辅助决策，不可覆盖 policy |
| `evidence_context` | 有 provenance 的证据和 citation | 可支持结论，不构成指令 |
| `untrusted_observations` | MCP、网页、A2A、上传内容 | 默认待验证，不可改变目标与授权 |

每次 action 返回的内容先经过 `ContextAdmission`，再生成面向下一轮的摘要。外部内容中的提示、命令或权限声明不得进入控制指令层。

## Executive Loop

### 决策循环

```text
1. Project
   从 TaskSpec、Ledger、ContextEnvelope 和预算形成 ControlState。

2. Decide
   Executive 根据未满足的成功标准提出一个 ControlDecision。

3. Validate
   Runtime 校验目标相关性、状态转换、类型、能力需求、风险和预算。

4. Resolve
   仅为本动作解析 CapabilityRequirement，生成 coverage 和 scoped capability set。

5. Execute
   执行一个 bounded action、一个经验证的只读并行组，或进入一个确定性 protocol 子图。

6. Observe
   保存 provenance、artifact、错误、coverage、成本和 verification result。

7. Update
   Runtime 更新 Ledger；必要时允许 Executive 提出 replan。

8. Complete
   Completion Verifier 检查成功标准。未满足则进入下一轮。
```

这不是无限制 ReAct。Executive 只能从控制动作集合中选择；`explore` 内部可以有自己的短 ReAct loop，但必须有独立 scope、工具集、轮数和结束条件。

### 三层循环

系统必须区分三种反馈循环，避免把局部工具选择或失败重试误认为任务级 Agentic：

| 循环 | 决策范围 | 可修改内容 | 返回上层的结果 |
| --- | --- | --- | --- |
| `Executive Loop` | 整个用户目标的下一步 | 未执行 goal、Skill、Macro、能力需求、委派和 protocol 调用 | 最终结果或中断 |
| `Executor Loop` | 一个 bounded action 内部 | 当前 action 的读取/搜索顺序和局部工作记忆 | `ActionOutcome` |
| `Recovery Loop` | 瞬时错误和同类实现恢复 | retry、backoff、同 provider 重连、幂等恢复 | 恢复结果或 escalation |

`scoped ReAct` 属于 Executor Loop，只能在已经批准的 requirement、capability set 和预算内选择下一次 observation/action。它不能新增任务目标、切换到 A2A、激活 Skill、调用写入 protocol 或宣布整个任务完成。

Recovery Loop 不生成新的任务 DAG。重试耗尽、coverage 改变、需要另一类 provider 或原假设失效时，它必须返回结构化 `Escalation` 给 Executive，由 Executive 决定 revise、delegate、clarify、degrade 或 stop。旧式“失败后追加若干自由 ExecutionStep”的 Replanner 不属于目标架构。

### 何时重规划

以下事件应触发下一轮 Executive 决策，而不是仅按原图重试：

- capability coverage 为 `partial`、`unavailable` 或 `denied`；
- 新证据否定假设或暴露新的必要子目标；
- verifier 判定证据不足、引用错误、结果冲突或 artifact 不合约；
- provider 失败且存在不同能力类别的替代路径；
- 委派结果需要补充调查或无法满足主任务标准；
- 用户修正目标、资源范围、预算或预期输出；
- protocol 返回拒绝、取消、超时或部分提交；
- 成本、轮数或时间预算接近边界。

普通瞬时错误、幂等重试和协议内部恢复由 executor 或 state machine 处理，不必唤醒 Executive。

每次 replan 必须说明触发事件、保留的已完成事实、被替代的未执行工作以及预期收益。仅改变步骤措辞、重复相同 requirement 或在没有新信息时再次调用同一失败 provider，不算有效 replan，并应由循环检测器阻断。

### 完成与停止

`finish` 只是完成提案。Runtime 至少检查：

1. 所有必要 goal 已达到 `verified` 或有明确的 degraded 说明；
2. 每项成功标准有对应 artifact 或 verification result；
3. 必需证据已覆盖，引用与 provenance 可追溯；
4. mutation 已确认并产生 receipt，或明确未执行；
5. 没有未决审批、运行中的委派或必须处理的冲突；
6. 最终输出没有消费未经准入的 observation。

不满足时，Runtime 拒绝 finish，并把结构化缺口作为下一轮 observation。达到预算上限、用户取消或 policy 拒绝时使用 `stop`，输出可解释的部分结果和阻塞原因。

### 验证语义

验证分为三层，不能用一个 `verify` step 状态代替：

```text
Artifact Validation
  检查 schema、来源、完整性和类型 contract。

Goal Verification
  检查某个 goal 的 success criteria、证据覆盖和领域质量标准。

Completion Verification
  聚合所有必要 goal、审批、委派、mutation receipt 和预算状态，判断整个 task 是否结束。
```

统一结果 contract：

```python
class VerificationReport:
    subject_id: str
    status: Literal["passed", "failed", "inconclusive"]
    checked_criteria: tuple[CriterionResult, ...]
    evidence_refs: tuple[str, ...]
    unresolved_gaps: tuple[str, ...]
    recommended_next_actions: tuple[str, ...]
```

只有 `status == "passed"` 且所有 required criterion 通过时，Runtime 才能将 goal 从 `candidate_complete` 转为 `verified`。`failed` 和 `inconclusive` 必须保留 evidence gap，并重新进入 Executive；验证器自身成功返回不代表验证通过。

Verifier 由 criterion 的 `acceptance_contract` 和 Skill profile 选择，不能默认使用“相同模型再判断一次”：

| 任务/产物 | 首选验证方式 |
| --- | --- |
| 结构化 artifact | schema、类型和 provenance 程序校验 |
| 代码修改或诊断 | test、compile、static analysis、可复现命令 |
| 外部事实 | 引用覆盖、来源一致性、反证和 freshness 检查 |
| 知识写入 | admission policy、冲突/过期检查、用户确认 |
| 状态操作 | MutationReceipt 与目标状态回读 |
| 开放分析 | 独立 critique/evidence verifier，必要时使用不同模型或不同上下文 |

Artifact Validation 应尽量确定性；Goal Verification 只对相应 criterion 调用必要 verifier；Completion Verification 主要聚合状态。简单任务不得机械地增加多次模型自评，Runtime 应记录 verifier 成本和收益，避免验证开销超过任务本身。

## Execution Pattern 重定位

Execution Pattern 更名为概念上的 `Plan Macro`。它是经过评估的计划先验，不是 task 到 workflow 的枚举映射，也不要求一个 run 只能使用一个 macro。

| Plan Macro | 建议的初始子目标 | 典型完成检查 |
| --- | --- | --- |
| `evidence_answer` | 获取证据、形成主张、检查覆盖、组织回答 | 每个关键主张可追溯 |
| `investigation` | 建立假设、探索、比较反证、验证根因 | 假设被证实或排除 |
| `knowledge_change` | 获取依据、形成变更提案、验证、确认、提交 | receipt 与准入结果存在 |
| `delegated_research` | 划分子问题、委派、验证 artifact、综合 | 子任务合同满足且主 Agent 已复核 |
| `managed_operation` | 检查状态、形成操作提案、调用 protocol、验证结果 | 领域状态机达到目标状态 |

Macro 可以提供：

- 推荐的初始 Ledger item；
- 常见 evidence gap 和 verifier profile；
- 推荐 Skill 与 capability 类别；
- 恢复策略和停止条件；
- 必须调用的 protocol gate。

Macro 不可以：

- 授予工具、权限或资源访问；
- 将 provider 固定为 MCP、native 或 A2A；
- 阻止 Executive 根据 observation 增删低风险子目标；
- 把复合任务压缩为一个唯一类别；
- 绕过 confirmation、Gateway 或领域状态机。

Macro 激活应由 Executive 根据当前目标和缺口决定，也可以完全不激活。一次任务可以先使用 `investigation`，随后进入 `knowledge_change`；这两个 macro 共享同一 TaskSpec 和 Ledger，不形成两个割裂 workflow。

## Skill

Skill 是可按需激活的方法包：

```python
class Skill:
    skill_id: str
    version: str
    description: str
    applicability: SkillApplicability
    instructions: str
    context_policy: ContextPolicy
    capability_preferences: tuple[CapabilityPreference, ...]
    verifier_profile: str
    output_contracts: tuple[str, ...]
    eval_contract: str
```

Executive 根据任务领域、当前证据缺口和方法需求激活 Skill，而不是仅在 run 开始时按 domain 静态匹配。Skill 内容采用渐进加载：候选阶段只暴露 description，激活后才注入 instructions 和必要资源。

Skill 可以建议使用某个 Plan Macro、capability 类别或 verifier，但不得限制任务只能走某个固定 Pattern，更不得扩大 scope、权限、预算或副作用边界。Skill 的激活和退出都写入 Ledger event。

## 元能力与执行形态

| 元能力 | 语义 | 典型执行形态 | 主要产物 |
| --- | --- | --- | --- |
| `acquire` | 从已知资源获取上下文 | deterministic read/retrieve | `ContextPack` |
| `explore` | 围绕未知位置或证据缺口迭代探索 | scoped ReAct | `EvidencePack` |
| `reason` | 比较、归纳、形成假设或候选结论 | structured model call | `Draft` / `DecisionProposal` |
| `verify` | 校验证据、事实、测试或 contract | verifier/test/retriever | `VerificationReport` |
| `transform` | 将已验证结果组织为目标输出 | structured model call | `Answer` / `Artifact` |
| `delegate` | 将边界清楚的子目标交给其他 Agent | A2A/subagent | `AgentRunRef` / `AgentArtifact` |
| `commit` | 执行已批准的状态变更 | deterministic protocol | `MutationReceipt` |
| `remember` | 将满足准入条件的结果沉淀为长期知识 | memory protocol | `KnowledgeStateReceipt` |

元能力描述“要完成的语义动作”，Capability 描述“可由谁实现”，executor 描述“如何运行”。三者不得合并为 provider-specific workflow。

## Capability 解析

每个 `execute_meta_capability` 或 `delegate` 决策必须形成 `CapabilityRequirement`：

```python
class CapabilityRequirement:
    purpose: str
    semantic_domains: tuple[str, ...]
    operations: tuple[str, ...]
    resource_binding: ResourceRequirement | None
    input_contract: str
    output_contract: str
    minimum_trust_level: str
    side_effect_class: str
```

Resolver 的输出必须包含充分性，而不只是 allowlist：

```text
Requirement
  -> registry discovery
  -> policy clamp
  -> resource and operation matching
  -> trust / freshness / cost ranking
  -> satisfied / partial / unavailable / denied
  -> scoped capability set + rationale
```

Executive 不从完整 registry 中直接选择具体工具。它选择语义动作并声明 requirement；Resolver 在全局 registry 中发现候选，但只把当前 scope、policy 和资源绑定允许的最小集合交给 executor。

候选选择采用分阶段过滤与分层排序，不将异质维度压成一个手工加权总分：

```text
1. policy / authorization / operation / resource hard filter
2. input-output contract / minimum trust / freshness eligibility filter
3. semantic fit and resource affinity
4. cost / latency / historical quality Pareto frontier
5. deterministic preference or bounded semantic comparison among finalists
```

`local-first`、低成本、低延迟和历史成功率都是可解释偏好，不是跨场景硬规则。Resolver 必须返回被淘汰阶段和 reason code，禁止使用难以审计的 `semantic * a + trust * b + cost * c` 混合分数掩盖资格不足。

Native、Retriever、MCP 可以竞争同一个 requirement，也可以共同满足不同子需求。例如代码调查可以先使用本地搜索，发现目标只存在于远端后再提出新的 requirement 并解析 GitHub MCP。MCP 的出现是 observation 驱动的能力补全，不是入口路由结果。

### Coverage 缺口处理

Coverage 不是终止判断，而是下一轮控制信号：

| Coverage | Runtime 行为 | Executive 可选动作 |
| --- | --- | --- |
| `satisfied` | 生成最小 scoped capability set | 执行当前 action |
| `partial` | 保存已覆盖与缺失 operation | 拆分 requirement、补充 provider、委派或给出受限结论 |
| `unavailable` | 保存 registry 与 resource binding 诊断 | 改用其他 capability 类别、请求 locator/授权、委派或 stop |
| `denied` | 保存 policy 决策且不暴露被拒工具 | 缩小 scope、请求必要确认或 stop；不得换名绕过 policy |

Resolver 不负责自动改变计划，也不能把 `partial` 提升为 `satisfied`。Executive 必须基于结构化 `CapabilityGapObservation` 决定下一步；连续生成语义等价且仍无法满足的 requirement 时，Runtime 应触发循环检测并要求 clarify、degrade 或 stop。

```python
class CapabilityGapObservation:
    requirement_id: str
    status: str
    satisfied_operations: tuple[str, ...]
    missing_operations: tuple[str, ...]
    attempted_capability_classes: tuple[str, ...]
    resolvable_by_authorization: bool
    resolvable_by_resource_binding: bool
    suggested_capability_classes: tuple[str, ...]
```

## A2A 与委派

委派由 Executive 在以下条件下选择：

- 子目标边界和输出 contract 清楚；
- 专业模型、独立上下文或并发带来实质收益；
- 主上下文会被大量中间结果污染；
- 委派成本低于主 Agent 自行执行；
- 存在可验证的返回 artifact。

委派不能由入口 intent、固定 Pattern 或某个 provider 名称直接触发。Executive 应比较“主 Agent 自行执行、调用普通 capability、隔离 subagent、远程 A2A”四种路径的能力覆盖、上下文成本、延迟、可信度和可验证性，再形成 `DelegateDecision`。具体 Agent 由 Agent CapabilityResolver 根据 `SubtaskSpec` 选择，而不是写死在计划宏中。

每次委派必须创建 `SubtaskSpec`，只投影必要上下文和最小能力范围。外部 Agent 不继承主 Agent 的隐式权限、完整会话或长期 memory。委派结果默认进入 `untrusted_observations`，通过结构验证不等于事实验证；主 Agent仍负责补充证据、综合和最终结论。

A2A 不进入通用 ReAct tool 列表。它是 `delegate` 的执行形态，具有独立生命周期、预算、取消、恢复和 artifact contract。

## Workflow 与 LangGraph 边界

固定 workflow 是 Executive 可调用的 `Protocol`，不是用户任务分类器。

以下情况必须使用确定性 protocol/state machine：

- 删除、外发、授权变更等高风险或不可逆动作；
- capture、长期知识写入和 memory admission；
- 有异步生命周期的 ResearchRun、订阅和 worker task；
- 需要幂等、事务、补偿、审批或严格审计的操作；
- 法规或组织 policy 要求固定状态迁移的动作。

Executive 只能提交强类型 `ProtocolCall` 并观察其结果，不能动态修改 protocol 内部步骤。Protocol 可以 interrupt 等待确认、跨进程恢复，也可以返回部分完成、拒绝或补偿结果，由 Executive 决定任务层下一步。

Research 必须拆分生命周期和策略：

```text
Research lifecycle Protocol
  创建 run、预算、暂停、恢复、取消、deadline、artifact 和状态迁移

Research strategy
  由 Executive + acquire/explore/reason/verify/delegate 决定问题分解、来源选择和下一步调查
```

Protocol 不得封装完整固定 research strategy，也不能因为任务被标记为 research 就接管顶层目标。远程研究 Agent 可以作为 delegate provider，但返回结果仍进入主 Agent 的 observation 和 verification 闭环。

LangGraph 负责：

- Executive Loop 的 durable execution；
- TaskSpec、Ledger、ContextEnvelope 和预算 checkpoint；
- clarification、confirmation 和外部事件 interrupt；
- protocol 子图调用与恢复；
- 并行子任务的 join、取消和状态投影；
- 结构化事件、trace 和 replay。

Task 具有独立于单次模型 turn 的生命周期：`active / awaiting_input / paused / completed / stopped`。同一任务的用户补充、确认和纠正必须恢复原 TaskSpec 与 Ledger；只有明确的新目标才创建新的 task。是否关联现有 task 也必须输出可审计的关联理由，不能因为收到新消息就无条件重置任务级状态。

普通纯函数解析、schema 校验和单次 provider 调用无需为“接入 LangGraph”而建独立图节点；只有需要持久状态、分支、恢复或可观测生命周期的边界进入图。

## 决策校验与不变量

`DecisionValidator` 在执行前依次检查：

1. 决策是否服务于未完成的 goal 或成功标准；
2. Ledger patch 是否只修改允许的状态和未执行工作；
3. 输入 artifact 与输出 contract 是否类型兼容；
4. capability requirement 是否具备明确 scope 和 resource binding；
5. 预算、并发、轮数、deadline 和风险是否允许；
6. 是否需要 confirmation 或固定 protocol；
7. Skill、observation 或外部 Agent 是否试图扩大权限；
8. 当前 action 是否与运行中的副作用或委派冲突。

并行独立性只能根据结构化 `input_artifact_ids`、`read_set`、`write_set`、resource binding、side-effect class、approval dependency 和 protocol dependency 判定，不能接受模型的自由文本保证。信息不完整、provider 副作用声明不可信、存在 write/write 或 read/write 冲突时默认拒绝并行。

系统始终满足以下不变量：

- Executive、Skill、Macro 和 Resolver 都不能授予权限；
- Gateway 是 tool/agent 执行的唯一出口；
- 高风险写入不能在开放 ReAct 或自由模型调用中执行；
- 每个外部事实可回溯到 evidence provenance；
- 未满足 coverage 不得被 compose 静默掩盖；
- 每个计划修订、能力决策、委派、确认和提交都有结构化事件；
- 已发生的副作用和 protocol 状态不能被 replan 改写；
- 长期记忆只接收通过 admission 和必要确认的内容。

## 端到端示例

用户请求：

```text
整理最近会议记录，结合仓库改动判断风险，给出行动项并保存。
```

目标链路不是选择一个 `knowledge_change` workflow，而是持续决策：

```text
1. Goal Interpreter
   -> TaskSpec：会议 + codebase，要求风险证据、行动项和知识写入确认

2. Executive
   -> activate_skill(knowledge-curation)
   -> revise_plan：会议证据、代码证据、风险验证、写入四个子目标

3. acquire
   -> Retriever 获取会议记录
   -> Observation：会议提到鉴权重构，但缺少代码依据

4. Executive
   -> activate_skill(code-investigation)
   -> execute_meta_capability(explore codebase)

5. Resolver
   -> 本地 workspace 无目标仓库
   -> GitHub MCP 满足 search + read

6. scoped ReAct
   -> 搜索变更、读取调用链和测试
   -> EvidencePack

7. Executive
   -> reason：形成风险与行动项候选
   -> verify：发现一项风险只有会议观点，没有代码反证检查

8. Executive replan
   -> explore：补充测试和历史变更证据
   -> verify：风险覆盖通过

9. Executive
   -> invoke_protocol(knowledge_commit, proposed artifact)
   -> Runtime interrupt 请求确认
   -> commit + memory admission

10. Completion Verifier
    -> 风险均有 provenance，行动项已确认写入，receipt 存在
    -> finish
```

这个过程可以动态加载多个 Skill、使用 native 与 MCP、补充调查并调用写入 protocol，但始终只有一个 TaskSpec、一个 Ledger 和一个主 Agent 对结果负责。

## 评估

评估单位应从“是否路由到正确 Pattern”升级为“控制决策是否让任务可靠前进”。至少覆盖：

| 维度 | 核心指标 |
| --- | --- |
| 目标理解 | TaskSpec 完整率、非必要澄清率、成功标准质量 |
| 决策质量 | 合法推进动作率、forbidden action 率、无效循环率、replan 收益 |
| 能力选择 | coverage 准确率、provider 替代成功率、过度授权率 |
| 计划管理 | 子目标覆盖、Ledger 一致性、已执行状态保护 |
| 证据质量 | 主张可追溯率、冲突检出率、错误完成拦截率 |
| 完成判定 | required criterion 通过率、false-finish 率、degraded 说明完整率 |
| 委派质量 | 委派必要性、context 最小化、artifact 合约通过率 |
| 安全治理 | 越权拦截、确认绑定、幂等与恢复正确性 |
| 效率 | provider 调用数、token、延迟、上下文增长和并发收益 |

关键场景必须包含：

- 无需工具的问题直接完成，不为 Agentic 而制造步骤；
- 初始能力不足后切换 native、MCP 或 A2A；
- 证据冲突触发新子目标和重新验证；
- 复合目标跨多个 Plan Macro，但不拆成孤立 workflow；
- Skill 推荐被 policy 拒绝后选择替代方法；
- A2A artifact 结构合格但事实依据不足；
- verifier 正常返回但结果为 failed/inconclusive，goal 不得变为 verified；
- executor 重试耗尽后升级到 Executive，而不是追加自由步骤；
- 写入确认拒绝、恢复、重复提交和部分失败；
- prompt injection、资源越界、预算耗尽和错误 finish；
- protocol 内部失败由状态机恢复，任务级失败由 Executive replan。

开放任务通常不只有一个唯一正确的下一步，因此 decision eval 不使用单一 `expected_action` 或固定 golden step sequence。每个评估状态定义：

```python
class DecisionEvalSpec:
    acceptable_action_classes: tuple[str, ...]
    forbidden_action_classes: tuple[str, ...]
    required_properties: tuple[str, ...]
    expected_progress_dimensions: tuple[str, ...]
    max_incremental_cost: CostBudget | None
```

评估依次判断动作是否合法、是否关联未完成 criterion 和最新 observation、是否带来可观测进展、是否重复无效路径、是否产生不必要成本，最后再衡量端到端成功率和 false-finish。Decision trace golden 只固定 Runtime 不变量和关键 reason code，不固定模型必须选择的唯一合理路径。

## 落地计划

### 实施原则

本计划按不兼容目标实施，不建设新旧语义转换层，也不长期保留双主链路：

1. 新 contracts 直接替换旧 contracts；调用方和测试在同一 Phase 内同步修改。
2. checkpoint schema 提升主版本。旧 checkpoint 明确返回 `incompatible_checkpoint_version`，不做字段补齐或状态猜测。
3. 已持久化的 workflow event 继续作为历史审计数据只读保留，但不回放到新 Executive state。
4. 固定领域 state machine 可以保留内部实现，但必须通过新的 `Protocol` contract 暴露，不再由 intent 路由直接进入。
5. 每个 Phase 必须同时交付 contract、runtime、事件、测试和文档；只有验收门槛全部通过才进入下一阶段。
6. 新主链路完成前可以在开发分支逐步构建，但正式切换时只保留一个 entry topology。
7. 不为复用旧类名而扭曲新职责。职责变化时直接新增正确抽象，并在切换 Phase 删除旧抽象。
8. 开发与评估阶段允许对历史 event/trace 做离线 replay、shadow decision 和基线比较，但 shadow 结果不得执行工具、写入状态或形成生产双轨。

### 依赖顺序

```text
Phase 1 目标与控制 contracts
  -> Phase 2 Ledger 与验证语义
  -> Phase 3 Executive Graph 骨架
  -> Phase 4 Executor 与 Recovery 分层
  -> Phase 5 Capability 缺口闭环
  -> Phase 6 Skill 与 Plan Macro
  -> Phase 7 动态委派与并行
  -> Phase 8 Protocol 接入与入口切换
  -> Phase 9 删除旧链路、全量评估和文档收口
```

Phase 1-5 构成只读开放任务的最小 Agentic 纵切；Phase 6-7 扩展方法选择和协作；Phase 8 才允许新主链路执行副作用；Phase 9 负责证明旧控制模型已经彻底退出。

首个纵向切片严格限定为只读开放知识任务，只启用 `acquire / explore / reason / verify / transform`、native/current artifact/local retrieval 和一个 MCP provider。它必须先证明：

1. 初始证据不足时 observation 会改变下一步 task-level decision；
2. Executive 能在 native 与 MCP 之间动态补全 capability；
3. verifier 判定不足时不会错误 finish；
4. 简单问题能以少量 decision 完成，不产生微步骤模型调用；
5. 相比旧 trace，成功率或 false-finish 至少有一项显著改善，成本与循环率不失控。

在这个纵切通过离线 replay、shadow decision 和独立 e2e eval 前，不接入动态 Skill、Plan Macro、A2A、并行或副作用 Protocol。这里的 shadow 只产生不可执行决策记录，不构成兼容层或生产双跑。

### Phase 1：重建目标与控制 contracts

目标：建立 Executive 可依赖的强类型状态，先消除 intent、Pattern 和宽松 step dict 对控制面的塑形。

主要改动：

- 将 `TaskSpec` 升级为带 revision、结构化 `SuccessCriterion`、criterion origin/mutability 和稳定 resource binding 的目标对象。
- 新增 `ControlState`、判别联合 `ControlDecision`、`BoundedAction`、`ActionOutcome`、`Escalation` 和 `TaskRevisionProposal`。
- 将 `ExecutionLedger.active_pattern` 替换为 `applied_macros`，移除 `source_intents` 的控制语义。
- 为 Task、Goal、Attempt、Approval、AgentRun 和 ProtocolRun 定义稳定 ID 与状态枚举。
- 给 `AgentGraphState` 增加 task lifecycle、executive turn、remaining budget 和 latest observation refs。
- checkpoint schema 直接升主版本，删除旧状态 migration 在新图上的入口。

建议代码归属：

```text
kernel/contracts/agentic.py       TaskSpec、Ledger、Verification contracts
kernel/contracts/executive.py     ControlState、ControlDecision、ActionOutcome
orchestration/orchestration_models.py  checkpointed state
```

验收门槛：

- 所有 decision variant 都能通过 discriminator 严格反序列化；variant 缺少必填 payload 时必须失败。
- TaskSpec revision 不能删除 required criterion 或静默扩大 mutation intent。
- user/policy criterion 不得被 Executive revision；derived criterion 必须保留 origin。
- 新 checkpoint 可以 round-trip；旧版本得到显式不兼容错误。
- contract 测试不再断言 `active_pattern`、`source_intents` 或 provider-specific workflow ID。

### Phase 2：让 Ledger、Verification 与 Completion 成为事实源

目标：在引入 Executive 前先消除“step 成功即 goal verified”和“没有 errors 即完成”的错误语义。

主要改动：

- 实现 `LedgerPatchValidator`，只允许合法 Goal 状态转换和未执行工作的受限修改。
- 建立 append-only `ExecutionEvent` 与 deterministic Ledger projector；snapshot 只作为 materialized view/checkpoint。
- 引入 `ArtifactValidator`、`GoalVerifier`、`CompletionVerifier` 以及统一 `VerificationReport`。
- step/action 完成只写 `AttemptResult`；goal 先进入 `candidate_complete`，再由 GoalVerifier 写入 `verified`。
- CompletionVerifier 按 required criterion、evidence gap、approval、AgentRun、ProtocolRun 和 receipt 聚合完成状态。
- `finish` 被拒绝时产生 `CompletionGapObservation`，不能直接进入 final node。
- `degraded`、`abandoned`、`stopped` 形成独立用户可见结果，不再伪装成成功回答。

建议代码归属：

```text
planning/ledger_validation.py
planning/verification.py
planning/completion_verifier.py
orchestration/orchestration_nodes/_completion.py
```

验收门槛：

- verifier 返回 `failed` 或 `inconclusive` 时 goal 不得成为 `verified`。
- 所有 step 无异常但 required criterion 未满足时，run 不得完成。
- 写入任务没有确认或 receipt 时，CompletionVerifier 必须拒绝 finish。
- property-based 状态机测试覆盖所有非法 Ledger transition。
- 同一 event stream 重放必须得到字节级等价的规范化 Ledger 状态。

### Phase 3：建立 Executive Graph 最小闭环

目标：让顶层控制从预编译完整步骤图转为每轮一个 `ControlDecision`。

Graph 拓扑：

```text
interpret_goal
  -> project_control_state
  -> decide
  -> validate_decision
  -> resolve_action_capabilities
  -> dispatch_action
  -> admit_observation
  -> update_ledger
  -> verify_goal_progress
  -> verify_completion
       -> decide / interrupt / finalize
```

主要改动：

- 实现 `GoalInterpreter`，直接生成 TaskSpec；Router intent 只保留为离线评估标签。
- 实现 `ExecutiveController.decide(ControlState) -> ControlDecision` 和 `DecisionValidator`。
- 每轮只物化一个 `BoundedAction`；未来工作只存在于 Ledger，不生成完整 `ExecutionPlan`。
- 根据“是否需要新的任务级信息”选择 action 粒度，并强制 tool/model/iteration/deadline/read-write budget。
- direct answer 也通过 `reason/transform -> candidate_complete -> verification -> finish`，但允许在一个或少量 turn 内完成。
- 所有 decision、validation、observation 和 ledger revision 写结构化事件。
- 增加 max executive turns、重复 decision hash 和无进展检测。

验收门槛：

- 一个证据不足的只读任务能够至少经历两次 Executive 决策并根据 observation 改变下一步。
- 简单问题不会为展示 Agentic 而产生无用工具调用或子目标。
- 相同 ControlState 连续产生语义等价决策时触发 loop guard。
- graph checkpoint 可在任意 Executive 边界恢复，并产生相同后续状态转换。
- 连续确定性读取可在一个 bounded action 内完成，不得退化为每次工具调用一次 Executive 决策。

### Phase 4：拆分 Executor Loop 与 Recovery Loop

目标：复用已有 deterministic、ReAct 和 model 能力，但禁止局部执行器修改任务计划。

主要改动：

- 建立 `ActionDispatcher`，按 meta-capability 和 execution shape 选择 executor。
- 将现有 scoped ReAct 改为 `ExploreExecutor`，输入固定 requirement、scope、tool set 和 budget，输出 `ActionOutcome`。
- deterministic retrieve、reason、transform、verify 统一返回 typed artifact 和 observation。
- retry、backoff、同 provider 重连和幂等恢复下沉为 `RecoveryPolicy`。
- Recovery 失败时只返回 `Escalation`，不得追加新的 ExecutionStep。
- 删除旧 `Replanner` 的自由 step 生成逻辑及同类 prompt。

建议代码归属：

```text
execution/action_dispatcher.py
execution/executors/explore.py
execution/executors/deterministic.py
execution/recovery.py
```

验收门槛：

- ExploreExecutor 无法调用 scope 外工具、A2A、Skill 或 Protocol。
- retry 耗尽后 Executive 收到结构化 Escalation，并能选择不同动作。
- completed action 不会直接改写 Goal 状态或 TaskSpec。
- 删除旧 Replanner 后，失败恢复测试全部迁移到 Recovery + Executive 场景。

### Phase 5：闭合 Capability 缺口与 provider 替代

目标：让 coverage 结果真正参与下一轮控制，而不只是 blocked 日志。

主要改动：

- CapabilityResolver 改为按当前 action requirement 解析，不再依赖预编译 step。
- 输出 `CapabilityGapObservation`，包含已覆盖操作、缺失操作、尝试类别和可解决方式。
- Executive 支持拆分 requirement、补 resource binding、请求授权、切换 native/MCP/retriever、委派、degrade 或 stop。
- 增加 requirement semantic hash，阻止无新信息时重复解析同一缺口。
- provider ranking 纳入 resource affinity、trust、freshness、成本、延迟和历史失败。
- provider ranking 使用资格过滤、semantic fit 和 Pareto/分层排序，不实现跨维度手工混合总分。
- 保持 PolicyEngine + Gateway 为唯一授权与执行出口。

验收门槛：

- native 不可用时可以在下一 Executive turn 改用 MCP，而不是入口预选 MCP。
- `partial` coverage 不得进入无约束 compose；必须补能力或显式 degraded。
- `denied` 不得通过换 tool/provider 名称绕过 policy。
- 无 provider、缺 locator 和缺授权三种情况产生不同的下一步决策。

### Phase 6：动态 Skill 与 Plan Macro

目标：把 Skill 和 Pattern 从静态编译标签改为 Executive 可按需采用的方法与计划先验。

主要改动：

- 拆分 `SkillCatalog` 的 description 索引与激活后的完整 instructions，实现渐进加载。
- Executive 可根据 evidence gap 激活、替换或退出 Skill；每次变化记录理由和版本。
- 将 Execution Pattern 重构为 `PlanMacro`，只产生受限 `LedgerPatchProposal`、verifier profile 和恢复建议。
- 一个 task 可以使用多个 Macro，也可以完全不使用 Macro。
- Skill/Macro recommendation 经过 DecisionValidator，不能扩大 capability、预算、scope 或权限。
- 建立独立 Skill/Macro eval，不用 Router intent 命中率代替方法质量。

验收门槛：

- 代码证据缺口可以在任务中途激活 `code-investigation`，而非只能在入口匹配。
- Macro 不能直接创建已绑定 provider 的 action。
- 复合任务能先使用 `investigation`，再使用 `knowledge_change`，共享同一 Ledger。
- 不激活 Skill 的简单任务仍能正常完成。

### Phase 7：动态 A2A、subagent 与受限并行

目标：让委派成为基于成本、上下文和能力缺口的运行时决策，而不是固定 intent 到固定 Agent。

主要改动：

- 建立 Agent CapabilityRegistry/Resolver，以 `SubtaskSpec` 匹配本地 subagent 或远程 A2A Agent。
- 移除计划中的固定 `gpt_researcher` agent ID；provider binding 在 delegate action 执行前完成。
- 为委派实现最小 context projection、独立 budget、deadline、cancel、resume 和 artifact admission。
- `execute_parallel` 只接受依赖独立、只读、预算有界的 action；Runtime 负责 join 和失败投影。
- 并行校验必须使用 artifact dependency、read/write set、resource、approval 和 protocol dependency；信息不完整时默认串行。
- Agent artifact 先做结构验证，再由主 Agent 决定事实复核和综合。
- 主 Agent 始终保留用户会话和 finish 所有权。

验收门槛：

- 同一研究子目标可根据可用性在本地 subagent 与 A2A provider 间选择。
- 简单任务不会因存在 Agent provider 而被不必要委派。
- 两个独立只读子目标可并行，存在依赖或写冲突时必须拒绝并行。
- A2A artifact 结构通过但事实不足时，Executive 能追加证据验证而不是直接 finish。

### Phase 8：将固定 workflow 收口为 Protocol 并切换主入口

目标：让 capture、delete、Research lifecycle、订阅和其他事务流程成为 Executive 调用的确定性 Protocol，同时完成唯一主入口切换。

主要改动：

- 定义 `ProtocolRegistry`、`ProtocolCall`、`ProtocolOutcome` 和 protocol lifecycle contract。
- 将现有领域 state machine 按职责重命名并注册为 Protocol；不允许 Executive 修改内部 transition。
- Research Protocol 只管理 run 生命周期；问题分解、来源选择和研究策略保留在 Executive/Executor。
- confirmation、memory admission、idempotency、compensation 和 receipt 保持 Runtime 强制执行。
- protocol 的拒绝、超时、部分提交和补偿结果作为 observation 返回 Executive。
- EntryGraph 切换到 GoalInterpreter + ExecutiveGraph；取消按 state-machine intent 进入 workflow 的顶层分支。
- 同一 task 的补充、确认和恢复按 task ID 进入原 Ledger，不再无条件重置任务对象。

验收门槛：

- capture、delete、ResearchRun 和 subscription 均只能通过 ProtocolCall 执行。
- Executive 无法绕过 confirmation 或直接调用写工具。
- protocol interrupt 后可从 checkpoint 恢复，并回到同一 Executive task。
- 所有 entry 类型只经过一个顶层 Executive topology。

### Phase 9：删除旧控制链路并完成系统级评估

目标：清除会让工程重新退回 workflow-driven controller 的旧抽象、字段和测试假设。

必须删除：

- `MetaPlanCompiler` 顶层职责和 `_select_pattern()`；
- `active_pattern`、`allowed_patterns` 以及 `source_intents` 的控制用途；
- 预编译完整任务 DAG 后按索引执行的主循环；
- 失败后生成和追加自由 ExecutionStep 的旧 `Replanner`；
- `verify` action 完成即写 `verified` 的状态转换；
- “没有 errors 即 answer_completed”的 final 逻辑；
- provider-specific intent 到 MCP/A2A/fixed workflow 的执行映射；
- 只验证 Pattern 命中和固定 step 序列的测试。

系统级验证：

- 按本文“评估”章节建立 e2e scenario suite 和 decision trace golden tests。
- 运行 contract、property-based、unit、integration、checkpoint/resume、policy、MCP、A2A 和 protocol 全量回归。
- 对比固定基线的成功率、false-finish、循环率、调用成本、延迟和越权率。
- 对历史 trace 运行不可执行 shadow decision，按 acceptable/forbidden/progress properties 比较，不要求唯一动作序列一致。
- 对每个 `stop/degraded` 结果验证用户可解释性和未满足标准。
- 更新 `docs/summary`，只描述实际代码事实；删除旧 Pattern 主链路总结。

最终退出条件：本文十二项目标态验收标准全部通过，代码搜索不再发现旧控制字段或旧入口分支，且 e2e trace 能证明 observation 会改变后续 task-level decision。

### 旧组件处置矩阵

| 当前组件/语义 | 目标组件/语义 | 处置 Phase |
| --- | --- | --- |
| Router intent 主导 TaskSpec | `GoalInterpreter + TaskSpec revision` | Phase 1、3 |
| `MetaPlanCompiler` | `ExecutiveController + bounded action materialization` | Phase 3、9 |
| `_select_pattern()` | 可选 `PlanMacro` | Phase 6、9 |
| `ExecutionPlan + step index` 作为主循环 | `ExecutionLedger + ExecutiveGraph` | Phase 3、8、9 |
| `SkillRegistry.select(domain)` | 渐进式 `SkillCatalog` 激活 | Phase 6 |
| coverage blocked 日志 | `CapabilityGapObservation -> ControlDecision` | Phase 5 |
| 局部 ReAct 兼任 Agentic 主体 | 有界 `ExploreExecutor` | Phase 4 |
| 失败 LLM Replanner 追加 steps | `RecoveryPolicy -> Escalation -> Executive` | Phase 4、9 |
| 固定 `gpt_researcher` 委派 | Agent CapabilityResolver | Phase 7 |
| workflow intent 顶层分支 | `ProtocolRegistry` | Phase 8 |
| step-type `verified` | `GoalVerifier` | Phase 2 |
| no-errors finalization | `CompletionVerifier` | Phase 2、8 |

### 测试与交付门禁

每个 Phase 的变更必须满足统一门禁：

```text
contract/schema tests
  -> unit tests
  -> state-machine/property tests
  -> graph checkpoint/resume tests
  -> policy and prompt-injection tests
  -> provider integration tests
  -> e2e decision-trace tests
  -> lint / type check / compile / diff check
```

测试必须断言结构化状态、事件和决策，不以最终回答字符串作为唯一正确性依据。涉及模型决策的测试使用固定 structured outputs 验证 Runtime 不变量；另行使用 eval 数据集衡量真实模型的决策质量，不能把 mock 通过等同于 Agentic 能力达标。

## 目标态验收标准

1. 顶层不再存在基于 Router intent 的一次性 `_select_pattern()` 控制路径。
2. Executive 每轮基于 checkpointed ControlState 产生一个强类型 ControlDecision，并以结构化 DecisionBasis 关联 criterion、observation 和 gap。
3. append-only ExecutionEvent 可确定性投影为 ExecutionLedger；Ledger 支持受限增量修订并成为当前任务进度事实源。
4. Plan Macro 可选、可组合、可退出，不决定 provider 或授权。
5. Skill 可在执行中按需激活，并采用渐进上下文加载。
6. MCP、native、retriever 和 A2A 由 requirement 与 coverage 动态接入，候选选择不依赖跨维度手工混合总分。
7. capability 缺失、验证失败和用户修正能够触发真实 replan。
8. Executive、Executor 和 Recovery 三层循环具有独立 contract；BoundedAction 有明确预算和读写集，局部 ReAct 与失败重试不能修改任务计划。
9. `verified` 只由通过的 criterion-specific Goal Verification 写入，不能由模型自评、step 类型或无异常执行推导。
10. finish 必须经过 Completion Verification，不能以“步骤跑完”或“没有 errors”代替。
11. 副作用、异步生命周期和事务操作全部通过固定 Protocol 执行，Research lifecycle 与 research strategy 保持分离。
12. 同一 task 可跨 turn 恢复，整条链路可 checkpoint、interrupt、resume、trace、replay，并使用多可接受动作而非唯一 golden path 评估。

## 结论

目标架构不再是：

```text
Router -> choose Pattern -> compile fixed graph -> execute
```

而是：

```text
TaskSpec
  -> Executive decides one bounded action
  -> Runtime validates and resolves capabilities
  -> Executor / A2A / Protocol acts
  -> Observation updates Ledger
  -> Executive replans until verified completion
```

Pattern 退回到计划经验，Skill 提供方法，Capability 提供行动可能性，Workflow 提供确定性协议，LangGraph 提供可靠运行时。主 Agent 通过持续决策和反馈闭环组合这些部件，才真正具备面向开放知识任务的 Agentic 行为。

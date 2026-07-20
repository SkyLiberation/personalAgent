# Agentic 决策平面与确定性管控平面重构

## 定位

本文定义 personalAgent 的下一代目标架构，解决一个核心矛盾：系统既要允许模型在开放世界中自主理解、规划、选择能力、生成业务参数和恢复策略，又必须让权限、副作用、持久状态和完成判断可审计、可恢复、不可越权。

本设计不考虑旧 checkpoint、旧 schema、旧调用方和历史测试的兼容。落地时直接修改所有调用方，提升 Task schema version，删除被替代类型和 deterministic business fallback，不保留 alias、双写、shadow path 或灰度适配层。

本文目标态已于 2026-07-17 按不兼容方式落地；当前运行事实与代码入口见 [当前核心架构](../summary/core-architecture-current-state.md)。本文保留为设计依据和验收矩阵，不再代表待兼容迁移方案。正式 live E2E 是否通过仍以当次归档 trace 为准，不能由文档状态替代。

## 1. 设计结论

一句话原则：

> 模型选择开放语义；确定性系统管控边界，并从已接受契约、明确 policy 和当前事实中推导唯一结果。

更严格地说：

> 确定性逻辑可以推导，但不得发明；模型可以提议，但不得授权或提交。

目标结构不是“模型外面包很多业务 if/else”，而是 reference monitor：

```text
Model Decision Plane
  在存在开放语义或多个语义不同路径时，产生 typed Proposal
                         |
                         v
Deterministic Control Plane
  validate -> admit/deny -> freeze AcceptedIntent -> derive/resolve -> grant/fence
                         |
                         v
Execution Plane
  严格执行 ResolvedExecutionCommand，不重新解释业务语义
                         |
                         v
Observation + Receipt
  记录外部世界实际返回的内容和可机械证明的执行事实
                         |
                         v
Semantic Verification Plane
  判断结果是否满足 SuccessCriterion，失败则返回 Agent 自主修订
```

确定性层可以缩小、拒绝和暂停模型提案，也可以完成契约已经唯一确定的 canonicalization、route compilation、provider binding、ready frontier projection 和控制状态转换；但不能增加 Agent 未提议的 intent、target、payload 或 requested result contract，也不能通过拼接、默认值、启发式排名或 fallback 替 Agent 完成仍然开放的语义决策。

统一决策规则：

| 候选状态 | 决策所有者 |
| --- | --- |
| 没有合法候选 | 确定性拒绝、请求外部输入或终止 |
| 契约与 policy 机械地唯一确定一个语义结果 | 确定性推导，并生成 `DerivationRecord` |
| 存在多个语义等价实现 | Resolver/Scheduler 按显式非语义 policy 优化 |
| 存在多个语义不同路径 | 模型提出选择，Admission 管控 |
| 结果会扩张权限或引入新 intent/target/payload/requested result contract | 不得推导；必须产生新 Proposal |

## 2. 外部参考与取舍

本设计参考的是稳定架构思想，不复制任何框架 API。

### 2.1 Anthropic：workflow 与 agent 的边界

Anthropic 在 [Building effective agents](https://www.anthropic.com/research/building-effective-agents) 中区分：workflow 通过预定义代码路径编排 LLM 和 Tool；agent 则由模型动态控制过程与 Tool 使用。同时建议优先使用简单、可组合的模式，并允许在中间步骤增加 programmatic checks。

本设计采纳：

- 业务目标、开放步骤、能力类别和语义恢复方向留在模型决策平面；
- 程序化 gate 可以检查安全和一致性，但不能把动态 Agent 重新固化成关键词路由或业务 Workflow；
- 已被模型或用户接受的稳定 Workflow/Procedure 可以确定性执行，内部不需要模型逐节点复述；
- 只把真正稳定的事务不变量和契约必然步骤固化为 Procedure。

### 2.2 OpenAI Agents SDK：模型决定动作，审批阻止副作用

OpenAI 官方 [Guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals) 明确：模型仍可决定需要某个动作，但审批会在 Tool 执行前暂停；校验应放在产生副作用的 Tool 边界，而不是只依赖 Agent 首尾 guardrail。审批返回可恢复 state，并在同一次 run 中继续。

[Orchestration and handoffs](https://developers.openai.com/api/docs/guides/agents/orchestration) 强调 specialist ownership 与 manager ownership 要显式，且只在 contract、policy 或能力隔离真正变化时拆分 Agent，避免不必要的 prompts、traces 和 approval surfaces。

[Integrations and observability](https://developers.openai.com/api/docs/guides/agents/integrations-observability) 将 model call、tool call、handoff、guardrail 和 approval 纳入结构化 trace，用于先解释单次运行，再建立 eval。

本设计采纳：

- Proposal 由模型生成，Approval/Governance 不替模型生成动作；
- mutation validation 紧贴 Tool/Gateway，并绑定同一 ResolvedExecutionCommand；
- pause/resume 继续同一 run、同一 command identity；
- trace 记录边界与事实，不保存 chain-of-thought。

### 2.3 LangGraph：持久中断与副作用隔离

LangGraph 官方 [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) 将 interrupt 定义为保存状态、暂停并等待外部输入，恢复时从节点重新执行；因此 interrupt 之前的副作用必须幂等，或更好地放到 interrupt 之后、独立节点中。[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) 还区分 thread checkpoint 与跨 thread store。

本设计采纳：

- Confirmation node 只保存等待状态，不在其前执行非幂等 mutation；
- commit side effect 使用独立节点、journal/outbox 和 command digest；
- Checkpoint 保存恢复游标，不成为业务事实的第二 owner。

### 2.4 Temporal：可重放控制与非确定性 Activity 分离

Temporal 官方 [Workflow Definition](https://docs.temporal.io/workflow-definition#deterministic-constraints) 要求相同输入和历史产生相同 Workflow Command 序列；LLM、API、数据库等非确定性交互应放在 replay path 之外的 Activity 中，历史 Command/Event 用于恢复时核对。

本设计采纳：

- Orchestration 只组织可重放协议和状态转换；
- LLM、Tool、Provider 和数据库副作用都通过显式 invocation/activity 边界；
- replay 不重新调用模型来重建已经接受的 Command；
- accepted command、dispatch 和 receipt 使用稳定 identity、digest 与 event cursor。

### 2.5 对外部评估的结论与采纳边界

外部评估指出原设计从“代码不得理解开放语义”进一步推成了“凡有业务含义都必须由模型显式提议”，这一判断合理。它准确识别了 mandatory Procedure、AcceptedCommand 全量同构、Context、Frontier、Capability、Recovery 和 Final composition 中不必要的 model-first 倾向。

本设计分三类采纳：

| 评估建议 | 结论 | 约束 |
| --- | --- | --- |
| 契约唯一结果可由代码推导 | 完全采纳 | 唯一性必须来自 accepted contract、typed policy 与当前事实，且产生 `DerivationRecord` |
| mandatory Procedure 可强制唯一 route | 完全采纳 | intent、target、payload 必须已被接受；route 不得改变业务语义或扩大权限 |
| `AcceptedIntent` 与 `ResolvedExecutionCommand` 分层 | 完全采纳 | 前者是语义唯一 owner；后者是只读派生命令，不成为第二个可写业务模型 |
| Admission rejection 不属于 Observation | 完全采纳 | 改为 `DecisionFeedback`；Observation 仅表示执行或外部世界结果 |
| Context 可确定性召回和压缩候选 | 有条件采纳 | 必须以显式 `ContextRequirement` 为输入，检索分数不能直接形成最终语义判断 |
| Frontier/Capability/Recovery 可确定性选择 | 有条件采纳 | 只处理唯一结果或语义等价实现；存在语义差异时回到模型 |
| 纯状态消息可确定性渲染 | 完全采纳 | 仅忠实展示 canonical state；业务答案仍由模型生成 |

以下原结论继续保留：Validator/Admission 不得修改 Proposal 的业务语义；代码不得在模型缺失或提案非法时创造替代 Plan、Action、query、payload 或业务答案；Execution fact、Goal semantics 与 Completion 必须分层。

### 2.6 二次评估的结论

二次评估认可上述方向，指出的问题主要位于类型所有权、授权摘要粒度和 revision loop，而不是推翻决策原则。以下建议全部采纳：

- `ResolvedExecutionCommand` 是必须持久化、不可覆盖的 immutable derived contract，不是可随时重算的 View；
- 用户确认绑定 `AuthorizationDigest`，Grant/Journal/Receipt 绑定更细的 `ExecutionCommandDigest`；
- Proposal 中只声明 `requested_result_contract`，真实 outcome 只能来自 Observation、Receipt、Verification 和 Completion；
- `DecisionFeedback` 显式限定可修改字段、不可修改字段和 revision scope；
- 循环检测拆分 intent、submission、rejection equivalence 三类 hash，并增加跨阶段 cycle budget；
- capability/environment 缺口、外部权威选择、系统 provenance 和 verification feedback 必须拥有独立类型；
- 等价 provider 必须满足正式 `CapabilityEquivalenceClass`，不能因为“都返回文本”就视为等价；
- denied Proposal 与 revision attempt 默认进入 Decision Audit Store，而不是污染 canonical Domain Event stream。

对 `DerivationProof` 的命名建议也予以采纳，统一改为 `DerivationRecord`。原因是系统能够机械证明的是封闭规则、输入摘要和 typed invariant result，而不是开放语义本身；无法重放验证的自然语言断言不得称为 proof。

## 3. 原则的精确定义

### 3.1 模型决策

以下属于开放世界语义，默认由模型提出：

- 用户意图、Goal、SuccessCriterion 和 Goal relation；
- 是否需要短期 Plan、Plan step、frontier 语义优先级；
- 当前推进哪个 Goal、采取何种 Action；
- 业务 Capability 类别、开放 Procedure/Workflow 选择及其业务参数；
- 哪些 ContextItem 与当前判断相关；
- Observation 对计划的语义影响；
- 验证失败后会改变业务语义的 retry、replan、clarify、degrade 或 terminate 策略；
- 最终面向用户的业务回答与结果组合。

这些输出必须是 typed Proposal，并引用它所依据的 context、artifact、observation 或 predecessor output。

“由模型选择”只适用于仍未被更高权威决定、且 policy 允许 Agent 自主判断的部分。语义权威顺序是：用户明确指令与 TaskContract frozen constraints 优先；权限授予、高风险歧义 target 和确认由 User/Admin 决定；模型只补足剩余开放语义。模型不得重新选择用户已明确排除的 Web、resource 或 side effect。

### 3.2 确定性管控

以下属于封闭世界 invariant，可以由代码机械证明：

- schema、identity、revision、cursor、DAG、lifecycle；
- Goal 是否 ready、dependency 是否已满足；
- budget、deadline、rate limit、resource scope、operation scope；
- capability availability 与等价 provider implementation 绑定；
- 从 AcceptedIntent 解析 canonical ID/version、缩小 scope、绑定等价 provider、计算 read/write set；
- 从显式依赖、priority、policy 推导唯一 ready frontier；
- 将已接受 mutation intent 编译到 policy 唯一允许的 Procedure route；
- policy、risk、confirmation requirement；
- Proposal 声明的 grounding/source/hash 关系是否成立；
- AcceptedIntent 是否逐字冻结 Proposal 的语义字段；
- ResolvedExecutionCommand 是否语义保持且 authority 单调不扩张；
- confirmation 是否绑定 AuthorizationDigest，grant/invocation/journal/receipt 是否绑定对应 ExecutionCommandDigest；
- idempotency、CAS、lease、fencing、outbox、replay；
- receipt、record identity、provider status 等执行事实；
- required VerificationReport 是否齐全，Completion 是否允许提交。

### 3.3 Decision Ownership Taxonomy

不再只用“模型/代码”二分所有决策。每个决策点必须标注以下类型之一：

| 类型 | 判定标准 | 所有者 | 典型输出 |
| --- | --- | --- | --- |
| `external_authority_choice` | 用户已明确约束、需要用户选择歧义目标或管理员授权 | TaskContract / User / Admin | frozen constraint / InteractionDecision |
| `semantic_choice` | 契约未决定且允许 Agent 自主判断的多个语义结果 | Model Decision Plane | Proposal |
| `contract_derivation` | accepted contract、policy、事实机械地唯一确定结果 | Compiler/Resolver | derived value + `DerivationRecord` |
| `equivalent_optimization` | 候选满足同一语义 contract，仅成本、延迟、可用性不同 | Resolver/Scheduler | binding/schedule + policy reason |
| `admission_control` | 判断 schema、权限、风险、预算、grounding、revision | Admission/Governance | Decision + reason code |
| `execution_fact` | provider、receipt、digest、revision 等可机械证明 | Gateway/Fact Verifier | Observation/Receipt/FactReport |
| `semantic_verification` | 判断证据是否满足开放语义 criterion | Model Verifier | GoalVerificationProposal |
| `presentation_rendering` | 只将 canonical control state 映射为固定消息 | Deterministic Renderer | StatusMessage |

`contract_derivation` 只有同时满足以下条件才成立：

1. 输入只来自已接受契约、版本化 policy 和已提交事实；
2. 对所有合法输入都是 total、typed、可重放的；
3. 不使用关键词、相似度、LLM 评分或隐藏优先级声称“唯一”；
4. 不新增 intent、target、payload 或 requested result contract，authority 只能保持或缩小；
5. 输出附带可审计的规则引用和证明。

### 3.4 明确禁止的确定性业务决策

禁止通过确定性代码：

- 从 description、constraints、user_goal 中拼接 Tool payload；
- 在模型未给出合法 Plan 时编译替代业务 Plan；
- 在模型未给出合法 Action intent 时选择 Goal、Capability 类别或 query；
- 用关键词、正则或默认资源替模型理解开放语言；
- 将 Tool title/summary 直接当最终用户答复；
- 用字符串包含、token overlap 等启发式冒充 Goal 语义完成；
- 在 Validator 内修改 Proposal 后再接受；
- 在 denied 后直接执行“最接近”的安全动作。

允许的非模型路径包括控制性 fallback，以及从 AcceptedIntent 唯一推导的执行步骤：fail closed、暂停、返回 typed feedback、同一 ResolvedExecutionCommand 的幂等技术重试、按 policy reconciliation、唯一 mandatory route compilation。它们都不能产生新的业务意图。

## 4. 当前架构审视

### 4.1 已经正确的基础

以下设计应保留并收紧：

- `TaskAnalysis -> TaskContract` 的 Proposal/Definition 分离；
- `ControlProposal -> StageAdmissionDecision -> AcceptedControlCommand`；
- mandatory Procedure 阻止 mutation 绕过稳定事务路径；
- `ExecutionGrant` 只能缩权；
- Context projection、model invocation grant、tool/agent gateway；
- Confirmation-bound grant、InvocationJournal/outbox、idempotency；
- Observation、EvidenceAdmission、VerificationReport 分离；
- Action technical success、Goal effectiveness、Task completion 分离；
- TaskContract/TaskRuntimeProjection、Definition/Event/Projection/View 分治；
- AgentEvent 与 canonical ExecutionEvent 的双层 trace 方向。

### 4.2 当前违反或模糊新原则的路径

| 当前路径 | 问题 | 目标处理 |
| --- | --- | --- |
| `AdaptivePlanner._compile_contract_plan` | 模型计划缺失/非法时由代码生成业务 Plan | 删除；返回 `plan_proposal_rejected` DecisionFeedback，让 Agent 修订；模型不可用则安全暂停/失败 |
| `AdaptivePlanner.create_plan` validation fallback | Validator 拒绝后静默换成 contract plan | 删除；不得掩盖原 Proposal，保留 rejection 与新 Proposal 因果链 |
| `ExecutiveController._materialize_contract_action` | 模型未决策时由代码选择 capability/synthesize action | 删除；只允许 Agent Proposal 或 typed safe stop |
| mandatory Procedure 直接触发 `_procedure_decision` | 当前实现既推导 route 又拼装 intent/payload，所有权混合 | 拆分：已接受 mutation intent 可确定性编译到唯一 mandatory route；缺失 intent/target/payload 时不得生成 invocation |
| `_procedure_decision` 拼接 `goal.description + constraints` | 确定性层生成业务 payload | 删除；模型输出完整 typed ProcedureInvocation 和 grounding refs |
| `ContextManager.project` 按 authority/item_id 自动选择全部可容纳内容 | visibility、retrieval、semantic relevance 与 budget 混合 | 拆成 visibility -> requirement-driven retrieval -> model semantic selection -> budget materialization |
| `FrontierSelector` 固定取前 N 个 step | 未证明唯一性就用位置决定语义优先级 | 先按 DAG/declared priority/resource policy 推导；唯一则直接选，多条语义路径仍可行时由 Agent 选择 |
| `PlanMonitor` 同时产生局部恢复动作 | 事实分类、唯一控制后果和语义恢复混合 | policy denied/stale/credential wait/同命令技术重试可确定性路由；改变目标或方案时由 Agent Proposal 决定 |
| `_apply_tool_result_to_state` 写入“已收进知识库”答复 | Tool adapter 决定用户表达 | 删除；Tool result 只形成 Observation/Artifact，最终由 Agent Composer 生成 |
| mutation verifier 使用自然语言字符串包含关系 | 将启发式内容匹配当确定性证明 | 替换为 command/receipt/resource digest 验证；Goal 语义仍由 Model Verifier 判断 |
| model semantic judgment 可覆盖已机械证明的执行事实 | 事实与语义混合 | 拆成 `ExecutionFactReport` 与 `GoalVerificationReport`，互不覆盖 |
| raw `ProcedureInvocation.input` | 业务参数、grounding 和 identity 缺乏 typed owner | 每个 Procedure 使用封闭 input model；禁止 raw dict 进入 AcceptedIntent/ResolvedExecutionCommand |

### 4.3 不应误删的确定性逻辑

新原则不是“所有 if 都交给模型”。以下逻辑仍必须确定性执行：

- Goal ID、dependency DAG 和 lifecycle 校验；
- mandatory Procedure bypass denial；
- 已接受 Action intent 到唯一 mandatory Procedure route 的编译；
- canonical resource ID/version 解析、scope 收窄、read/write set 计算；
- resource/operation scope 不得扩张；
- capability 是否在线、credential 是否可用；
- budget 和 provider call reservation；
- confirmation、grant、journal、receipt、replay；
- 同一命令的安全重试与 unknown outcome reconciliation；
- required report 完整性和 Task completion gate。

区别不再是“代码只能判断、不能产生结果”，而是：代码可以产生由契约必然决定的派生结果，但不能回答契约仍未回答的开放问题。任何派生结果都必须能回溯到唯一语义 owner，不能成为可独立编辑的第二份业务事实。

## 5. 目标模型与事实所有权

### 5.1 Proposal 不成为事实

统一使用以下抽象，不建立一个字段全可空的通用大模型：

```text
TaskAnalysisProposal
PlanProposal
FrontierSelectionProposal
ControlProposal
ContextSelectionProposal
GoalVerificationProposal
RecoveryProposal
FinalAnswerProposal
```

每个 Proposal 拥有：

```text
proposal_id
base_task_revision
base_runtime_revision / event_cursor
model_invocation_ref
context_projection_ref
decision-specific typed body
declared provenance/grounding refs
```

Proposal 只追加保存用于审计；不能直接更新 TaskRuntime 或触发 Gateway。存储所有权必须分层：

```text
Canonical Domain Event Store
  AcceptedIntent / ResolvedExecutionCommand / Grant / Journal /
  Receipt / Verification / Completion

Decision Audit Store / Agent Trace
  未通过解析的模型输出 / denied Proposal / DecisionFeedback /
  revision attempt / 简短 rationale

Checkpoint
  仅保存恢复当前 revision lineage 所需的 refs、budget 和 cursor
```

denied Proposal 默认不进入业务 Domain Event stream，避免格式错误和反复修订污染 replay；只有它被接受后形成的 canonical definition/fact 才进入 Domain Event。审计存储仍须 append-only，并通过 refs 与当前 run 关联。

### 5.2 Admission 只输出裁决

每个可执行 Proposal 都经过：

```text
AdmissionDecision
  proposal_ref
  verdict: accepted | not_accepted
  disposition: revise_model | request_external_input |
               request_capability_acquisition |
               await_environment_change | terminal
  reason_codes
  effective_constraint_refs
  governance_snapshot
  monotonicity_proof
```

Admission 不返回“修正后的 Proposal”。如果参数不完整或 grounding 不成立，输出 denied；Agent 根据 `DecisionFeedback` 生成新的 Proposal。Admission denial 是控制面的决策结果，不是外部世界或执行结果，因此不得包装成 Observation。

### 5.3 AcceptedIntent 与 ResolvedExecutionCommand

```text
AcceptedIntent
  accepted_intent_id
  proposal_ref
  admission_ref
  task/goal/revision/cursor
  semantics                  # intent/target/payload/requested_result_contract
  semantic_digest

ResolvedExecutionCommand
  command_id
  accepted_intent_ref
  supersedes_command_ref?    # re-resolution 创建新 Command，永不覆盖旧 Command
  route/procedure/version
  canonical_target_refs
  narrowed_scope
  provider_binding
  read_set / write_set
  authorization_projection
  authorization_digest
  execution_command_digest
  derivation_record_ref
  expires_at
```

`AcceptedIntent` 是被接受业务语义的唯一 owner，必须逐字冻结 Proposal 的语义字段：

```text
canonical_json(accepted_intent.semantics)
  == canonical_json(proposal.semantic_fields)
```

`ResolvedExecutionCommand` 是从 AcceptedIntent 派生、必须持久化的 immutable derived contract，不是可随时按最新 Registry 重算的普通 View，也不是第二份可写语义模型。它由 Execution Command Store/Runtime aggregate 拥有，并通过 `ExecutionCommandResolved` Domain Event 原子提交。Compiler/Resolver 可以解析 canonical ID、绑定 Procedure/version/provider、缩小 scope、计算 read/write set 和增加 fence，但必须满足：

```text
semantics(command) == semantics(accepted_intent)
authority(command) <= authority(accepted_intent)
targets(command) are traceable to accepted grounding
```

每次派生生成：

```text
DerivationRecord
  derivation_id
  derivation_kind: command_resolution | route_resolution |
                   provider_binding | frontier_projection |
                   coordination_mode
  source_contract_refs          # AcceptedIntent / TaskContract / PlanDefinition
  rule_id / rule_version
  policy_snapshot_ref
  input_fact_refs
  source_digests
  output_ref
  output_digest
  invariant_results
    canonical_target_mapping: passed
    scope_subset: passed
    route_uniqueness: passed | not_applicable
    provider_equivalence: passed | not_applicable
    authorization_projection_preserved: passed | not_applicable
  uniqueness_kind:
    single_policy_allowed_route |
    single_exact_identifier_match |
    single_active_equivalent_provider |
    single_ready_frontier_after_constraints |
    not_applicable
```

`invariant_results` 和 `uniqueness_kind` 必须是封闭类型，并能由 rule version、source refs 和 digest 重放；禁止写入“语义没变”“这是唯一选择”等自由文本假证明。“rank 最高”“文本最像”“通常这样做”不构成唯一性。若解析发现多个语义不同候选，Compiler 返回 DecisionFeedback，让模型或用户选择，不得擅自选第一个。

恢复时读取已提交 Command，不按最新 Provider、Policy 或 Registry 原地重算。stale revision、provider rebinding 或 policy version 变化需要重新解析时，生成新的 `command_id`、`supersedes_command_ref` 和 `DerivationRecord`；旧 Command 保留用于审计与 receipt 关联。

### 5.4 Grounding 是模型声明、系统核验

模型声明 payload 的来源，但系统推导和外部权威证据由各自 owner 创建：

```text
ModelGroundingClaim
  claim_id
  source_ref                 # ContextItem / Artifact / predecessor output
  source_span / artifact_path
  transform: identity | summarize | rewrite | aggregate | none
  origin: source_identity | source_transform | model_inference
  output_field_ref
  source_digest

SystemProvenanceRecord
  provenance_id
  origin: deterministic_computation | policy_derived
  derivation_record_ref / policy_snapshot_ref
  source_refs / source_digests
  output_ref / output_digest

AuthorityEvidenceRef
  authority_kind: user_confirmed | provider_observed
  confirmation_ref / observation_ref / receipt_ref

ProvenanceRef = ModelGroundingClaimRef |
                SystemProvenanceRecordRef |
                AuthorityEvidenceRef
```

确定性层不自行从用户文本寻找引号或猜测来源，只验证声明：

- source_ref 存在且在当前 projection/admitted context 中；
- identity transform 的 source span、payload 和 digest 完全相同；
- transform 在 TaskContract 与 policy 允许范围内；
- model 没有借 transform 扩张 resource/operation authority；
- summarize/rewrite 的语义忠实度交给 Model Verifier或用户确认，不由字符串启发式判断。

模型只能创建 `ModelGroundingClaim`，可以引用已有 `SystemProvenanceRecord` 或 `AuthorityEvidenceRef`，不能自行声明“由 policy 推导”或“provider 已观察”。`model_inference` 必须显式标记为推断，不能伪装成 source identity；`provider_observed` 必须由 Observation/Receipt 的事实 owner 建立。

### 5.5 Procedure 使用封闭输入类型

删除通用业务 `input: dict`。每个 Procedure version 声明输入 union，例如：

```text
KnowledgeIngestInput
  text
  grounding_claim_refs
  destination_scope

KnowledgeDeleteInput
  target_ref
  selection_evidence_refs

ResearchRunInput
  question
  evidence_policy
  freshness_requirement
```

这些输入中的 intent、target、payload 和 `requested_result_contract` 由模型填写并冻结到 AcceptedIntent；Pydantic/schema 校验不补业务值。Procedure route、canonical target、version、provider binding 等若由 policy 唯一确定，可以由 Compiler/Resolver 派生并写入 ResolvedExecutionCommand。真实 `execution_outcome`、`verification_outcome` 和 `completion_status` 只能由后续事实与报告建立。

### 5.6 AuthorizationDigest 与 ExecutionCommandDigest

使用两个不同粒度的摘要：

```text
AuthorizationProjection
  operation
  canonical_target_set
  user_visible_payload
  requested_result_contract
  side_effect_envelope
  data_egress_boundary / trust_boundary
  confirmation_relevant_cost_and_risk
  policy_required_provider_identity?     # 仅当 policy 要求用户确认具体 provider

AuthorizationDigest = digest(AuthorizationProjection)

ExecutionCommandDigest = digest(
  AuthorizationDigest + procedure/version + provider_binding +
  exact_scope + retry/idempotency config + read_set/write_set + fences
)
```

绑定关系：

```text
ConfirmationRequest/Decision -> AuthorizationDigest
ExecutionGrant               -> AuthorizationDigest + ExecutionCommandDigest
InvocationJournal/Receipt    -> ExecutionCommandDigest
```

Confirmation 展示 `AuthorizationProjection`，不重新生成业务参数。Provider rebinding 必须生成新的 ResolvedExecutionCommand、ExecutionCommandDigest 和 Grant；只有在 operation、target、payload、side effect、egress、trust、确认相关成本/风险及 policy 要求的 provider identity 均不变，即 AuthorizationDigest 相同时，才能复用仍有效的确认。任何授权投影变化都必须重新确认。

用户修改业务内容等价于新 Proposal。stale revision 重新解析时生成新 Command/DerivationRecord，不复用旧 ExecutionCommandDigest；是否需要重新确认只由新旧 AuthorizationDigest 和 confirmation validity 决定。

### 5.7 ProposalRevisionProtocol：被管控拦截后的模型修订

确定性管控拒绝 Proposal 后，默认不是直接失败，也不是由代码生成替代业务决定。统一处理协议是：

```text
Proposal
  -> Stage Admission
     -> accepted
        -> AcceptedIntent
        -> deterministic derivation/resolution when uniquely defined
        -> ResolvedExecutionCommand
     -> request_external_input
        -> durable interrupt
        -> external input
        -> new Proposal
     -> request_capability_acquisition
        -> durable AcquisitionRequest
        -> environment change event
        -> re-resolution / new Proposal when semantics changed
     -> await_environment_change
        -> durable wait
        -> re-evaluate against a new environment snapshot
     -> denied(revisable)
        -> DecisionFeedback
        -> bounded model revision
        -> new Proposal
        -> Stage Admission
     -> denied(terminal)
        -> fail closed
```

这里的 revision 是结构化纠错，不是保存一段自由形式“反思过程”，也不引入能够自我授权的 Reflection Agent。模型只看到原 Proposal、typed reason code、违反的 constraint refs 和允许修改的边界；不得向 trace、checkpoint 或用户暴露 chain-of-thought。Reflection 只负责提出新 Proposal，永远不能修改 Admission、policy、AcceptedIntent 或已提交事实。

#### 5.7.1 统一拒绝模型

```text
DecisionFeedback
  feedback_id
  stage: task_analysis | planning | context | control | route | output
  rejected_proposal_ref
  reason_codes
  violated_constraint_refs
  rejected_field_refs
  mutable_field_refs
  immutable_field_refs
  required_repairs
  revision_scope: format_only | grounding_only | parameter_completion |
                  semantic_revision | upstream_replan
  disposition: revise_model | request_external_input |
               request_capability_acquisition |
               await_environment_change | terminal
  revision_budget_remaining
  governance_snapshot_ref
  candidate_summary_refs      # 可选；只暴露合法候选及差异，不泄露隐藏 policy
```

`revision_scope` 是 Admission 对下一次模型调用的能力边界。例如 `grounding_required` 只允许修改 grounding refs；模型若需要改变 target/payload/requested result contract，必须升级为新的上游 Proposal 并重新治理，不能伪装成局部修复。

`disposition` 由 `DispositionPolicy.evaluate(stage, reason_code, task_policy, runtime_state, acquisition_options)` 确定，只表达控制结论，不包含替代业务动作。它不能仅由 reason code 静态映射，因为同一个 `credential_missing` 在不同环境中可能需要用户授权、切换已有 credential、能力获取或终止：

- `revise_model`：Proposal 的业务内容可以在原权限边界内修订；
- `request_external_input`：缺少只有用户、管理员或外部权威才能提供的信息、歧义选择或授权；
- `request_capability_acquisition`：存在 policy 允许的安装、连接、启用或授权流程，创建独立 AcquisitionRequest；
- `await_environment_change`：暂时不可用但无需改变业务语义，等待新的 environment snapshot 后重新解析；
- `terminal`：policy 永久禁止、Task 已取消、unknown mutation 无法 reconcile，或修订预算耗尽。

新的 Proposal 必须具有新 identity，并保存因果引用：

```text
proposal_id
supersedes_proposal_ref
revision_feedback_ref
revision_attempt
```

旧 Proposal 与 denied Admission 只追加保存，不允许原地覆盖。

#### 5.7.2 错误分类与处理

| 错误阶段 | 示例 | 处理 |
| --- | --- | --- |
| Model transport | timeout、429、provider unavailable | 在相同 ModelInvocationIntent 上做 policy 允许的技术重试；仍失败则 `awaiting_model`/terminal，不伪造 Proposal |
| Structured parse/schema | JSON/schema 不合法、缺少 required field | 生成 `ProposalFormatFeedback`，在 parse-revision budget 内让模型重新生成；尚未形成可 Admission 的 Proposal |
| Admission revisable denial | grounding mismatch、未知 criterion、Plan 越权、Context required set 超预算 | 生成 `DecisionFeedback(disposition=revise_model)`，模型产生新 Proposal 并重新 Admission |
| Resolution ambiguity | AcceptedIntent 可解析到多个语义不同 target/route | 生成 `DecisionFeedback(ambiguous_resolution)`；由模型或用户明确选择，不得按 rank 静默绑定 |
| External input required | 缺文件、高风险歧义 target、需要 confirmation/credential | durable interrupt；外部输入进入新的 Proposal/InteractionDecision，不修改旧 Proposal |
| Capability acquisition | plugin 未安装、connector 未连接、允许获取新 capability | durable AcquisitionRequest；环境变化后基于新 snapshot 重新 Admission/resolve，不默认改业务语义 |
| Environment wait | provider 暂不可用且没有等价 active provider | durable wait；收到环境事件后重解析，不反复调用模型 |
| Non-revisable denial | policy 禁止、Task cancelled、权限边界不可扩张 | `terminal`，不得让模型反复换措辞绕过 policy |
| Execution technical failure | 同一 Command 的 retryable timeout | 只允许同一 ExecutionCommandDigest 的幂等技术重试；不触发语义修订 |
| Unknown mutation outcome | provider 结果未知 | reconciliation；确认事实前禁止模型重做 mutation |
| Verification gap | receipt 成立但 SuccessCriterion 未满足 | `VerificationFeedback -> RecoveryProposal`，由 Agent 选择会改变业务语义的 replan/clarify/degrade/terminate |

`VerificationFeedback` 是内部评估反馈，不是 Observation：

```text
VerificationFeedback
  verification_report_ref
  unsatisfied_criterion_refs
  evidence_gaps
  deterministic_fact_refs
  recovery_budget_remaining
```

#### 5.7.3 修订预算与循环检测

`PlannerExecutionProfile`/Control policy 为每个阶段分别设置：

```text
max_task_analysis_revisions
max_plan_revisions
max_context_revisions
max_control_proposal_revisions
max_verification_recovery_turns
max_final_answer_revisions
max_cross_stage_revision_cycles
```

预算属于确定性管控，不允许模型自行增加。循环检测不能只看一个 semantic hash，必须分别计算：

```text
intent_semantic_hash
  intent + target + payload + requested_result_contract

submission_hash
  完整 Proposal，包括 grounding、refs 和重要 constraints

rejection_equivalence_hash
  由 stage/reason policy 选取“导致本次拒绝”的字段后计算

DecisionCycleKey
  task_revision + stage + reason_code + rejection_equivalence_hash +
  governance_snapshot_ref + upstream_intent_hash
```

重复判断使用 `DecisionCycleKey`，而不是单独使用 intent hash。相同 delete intent 修正 grounding 后可以继续；换措辞提交同一越权 scope 应被识别为重复。连续重复、达到阶段预算、跨阶段 cycle budget 或全局 executive-turn budget 时，进入 typed terminal/interaction state；不得切换到 deterministic business fallback。

Runtime 每次只允许一个 active revision lineage。上游 Proposal 变化必须显式列出 invalidated downstream proposal/command refs、哪些预算继续累计、哪些按 policy 重置，以及 AuthorizationDigest 是否失效。

#### 5.7.4 Orchestration 路由

每个 Admission 节点必须统一返回以下路由之一：

```text
accepted             -> freeze_accepted_intent -> derive_or_request_decision
revise_model         -> project_rejection_context -> invoke_revision_model
request_external_input          -> persist_interaction_interrupt
request_capability_acquisition  -> persist_acquisition_request
await_environment_change        -> persist_environment_wait
terminal             -> finalize_failed_or_degraded_run
```

Revision model context 只能包含：

- 当前 Task/Runtime snapshot；
- 被拒绝的 Proposal；
- Admission reason codes 与 constraint refs；
- 允许的 capability/procedure/context envelope；
- 与本次错误直接相关的 DecisionFeedback、Observation 或执行事实。

它不能包含 Validator 内部实现、隐藏 policy 规则或 chain-of-thought。新 Proposal 必须走与首次 Proposal 完全相同的 Admission，不存在“修订后免检”。

#### 5.7.5 Trace

标准事件链：

```text
proposal_created(proposal_1)
 -> admission_denied(proposal_1, reason_codes)
 -> decision_feedback_created(feedback_1)
 -> proposal_revision_started(feedback_1, attempt=1)
 -> proposal_created(proposal_2, supersedes=proposal_1)
 -> admission_accepted(proposal_2)
 -> accepted_intent_created
 -> execution_command_resolved(derivation_record_ref)
```

若终止，必须记录 `proposal_revision_exhausted`、`proposal_denied_terminal` 或 `model_revision_unavailable`，不能只留下通用 `run_failed`。

## 6. 各阶段目标协议

### 6.1 Task Analysis 与 Compile

TaskAnalyzer 继续负责开放语言理解。`GoalGraphCompiler` 改为 pure admission/compiler：

允许：

- schema、ID、relation endpoint、DAG；
- result contract 与 side-effect taxonomy 的一致性；
- 用户明确 criterion 不可丢失；
- 添加治理不可降低的最低标准，例如 mutation receipt、citation floor；
- identity、revision 和初始 runtime 原子提交。

禁止：

- 从空资源猜默认 ResourceRequirement；
- 用 goal description 生成缺失 criterion 的业务语义；
- 自动修复 relation、payload 或 mutation target；
- 将不完整 Proposal 编译成“尽量可运行”的 TaskContract。

不合法分析返回 `TaskAnalysisDecisionFeedback`，最多按预算让 Analyzer 修订。连续失败后等待用户/运维介入或安全终止。

### 6.2 Coordination 与 Planning

Coordination 不默认产生一次模型调用，先应用 `CoordinationPolicy`：

```text
contract/profile/runtime facts 唯一确定 reactive 或 deliberative
  -> deterministic coordination derivation + DerivationRecord

仍存在需要权衡的合法 coordination modes
  -> CoordinationProposal -> Admission
```

例如单一 ready Goal、无跨 Goal 依赖且 profile 禁止 Planner，可以直接得到 reactive；多个未解决依赖且 contract 要求维护短 horizon Plan，可以直接得到 deliberative。灰区才由模型提议。Reactive 表示 Agent 每轮直接提出下一动作，不代表代码替它生成 Action。

Plan 流程：

```text
Model PlanProposal
 -> PlanAdmission
    accepted -> PlanDefinition commit
    denied   -> PlanningDecisionFeedback -> model revise
```

删除 deterministic contract plan fallback。模型不可用时不创建伪 Plan；Run 进入 `awaiting_model`、`failed_model_unavailable` 或 policy 指定的 degraded terminal state。

Plan validator 只验证引用、DAG、权限上限、side-effect class、provider binding 禁止项和 budget，不改变 step 语义。若依赖、用户声明 priority 和 resource policy 已唯一确定拓扑顺序，Compiler 可以生成 derived schedule；否则不得重排语义不同的 step。

### 6.3 Executive

Executive model 一次输出一个完整 `ControlProposal`：

- target Goal；
- action kind；
- bounded action / procedure / delegation 的全部业务参数；
- grounding claim；
- expected progress 与 recovery intent。

Runtime 只物化 ready Goal view、可用 procedure/capability 摘要和 policy constraints。不得在模型无结果时调用 `_materialize_contract_action` 或 `_procedure_decision`。

mandatory Procedure 的行为是：

```text
Agent proposes mutation intent(target + payload + requested_result_contract)
  -> Admission accepts AcceptedIntent
  -> RoutePolicy finds exactly one legal Procedure route
  -> Compiler creates ResolvedExecutionCommand + DerivationRecord

Agent proposes a conflicting explicit route
  -> Admission denied(mandatory_procedure_bypass)

Agent has not proposed mutation intent/target/payload
  -> Runtime cannot create ProcedureInvocation
```

mandatory route 可以实现治理强制，但不能把 summarize intent 改成 delete intent，也不能替模型猜 target/payload。若存在多个语义不同的合法 Procedure，必须返回候选差异让 Agent 选择；若只是同一 contract 的多个 provider/version 实现，则 Resolver 可按 policy 绑定。

### 6.4 Context

Context 分四阶段：

```text
Deterministic visibility envelope
  先按 tenant、policy、trust、taint、purpose 排除绝对不可见内容

Deterministic requirement-driven retrieval
  根据 Agent 显式 ContextRequirement 做 metadata/BM25/embedding/recency/graph 召回、去重和候选压缩

Model semantic selection
  在压缩候选及其摘要中选择语义相关的 required/optional item

Deterministic budget materialization
  required 超预算则拒绝并返回预算 DecisionFeedback；optional 可按模型给出的优先级截断
```

`ContextRequirement` 必须声明目标、内容类型、时间/信任要求和用途。确定性检索可以排序候选规模，但不能根据隐藏关键词路由改变 requirement，也不能把 retrieval score 当成最终相关性或充分性判断。模型不需要先读取全部原文；它在受控候选摘要上做语义选择，选中后再物化原文。

### 6.5 Capability 与 Scheduler

Agent 提议业务能力类别和 output/evidence/side-effect contract。Resolver 只能在同一个正式等价类中绑定 provider、算法和版本：

```text
CapabilityEquivalenceClass
  required_output_contract
  allowed_side_effect_class
  authority_scope
  trust_floor
  freshness_contract
  evidence_contract
  data_egress_class
  failure_semantics
```

候选必须逐项满足同一 class 才是语义等价。若 output contract、side effect、authority、freshness、evidence、egress、failure semantics 或 trust 不等价，必须让 Agent/外部权威明确选择，Resolver 不得以排名代替语义决策。例如“网页搜索、私有知识库、委托研究”不能因为都返回文本就归入同一等价类；同一 Search contract 下满足全部字段的 providers 才可能只是实现绑定。

Scheduler 先根据 Plan DAG、已声明 priority 和 resource constraints 计算 ready set。若规则只留下唯一 frontier，可直接执行；若剩余多个语义等价 frontier，可按成本/并发 policy 优化；若多个语义不同路径仍然可行，由 Agent 提出 `FrontierSelectionProposal`。Scheduler 读取已 resolved 的 read/write set，决定物理并发、串行化、deadline 和 join feasibility，但不能新增 step 或创造未声明的 priority。

### 6.6 Procedure 与 Execution

Procedure 只保留：

```text
prepare
confirm
commit
receipt
compensate/reconcile
```

`prepare` 校验 AcceptedIntent、ResolvedExecutionCommand、DerivationRecord、AuthorizationDigest、ExecutionCommandDigest 和 provenance，不生成业务 payload；`confirm` 暂停且无非幂等副作用；`commit` 严格执行 frozen command；`receipt` 记录 execution command/resource/provider digest；`reconcile` 只解决执行状态 unknown，不选择新的业务结果。已接受稳定 Procedure 内部由 contract 唯一确定的节点不需要模型逐步重述。

Tool/Agent/MCP Gateway 对 invocation 与 grant 做最终复核，任何不一致直接拒绝，不调用 provider。

### 6.7 Observation、Verification 与 Completion

拆成三份报告：

```text
ExecutionFactReport          # deterministic
  provider 是否调用、receipt/digest/resource/revision 是否匹配

GoalVerificationReport       # semantic model proposal + admission
  Observation/Evidence 是否满足 SuccessCriterion

CompletionReport             # deterministic gate
  required Goal report 是否通过、是否仍有 pending confirmation/unknown outcome
```

确定性层不再使用自然语言 contains 证明 Goal 语义；模型 Verifier 也不能把匹配的 receipt 说成不存在。两类结论通过 criterion 类型组合，而不是互相覆盖。

Mutation 至少要求：

- `ExecutionFactReport.status=passed`；
- receipt 与 ExecutionCommandDigest 匹配；
- 需要时 read-after-write/reconciliation 完成；
- 所有 semantic SuccessCriterion 经 GoalVerifier 通过。

### 6.8 Recovery

确定性 failure classifier 输出事实，并可执行具有唯一控制后果的状态转换。会产生新业务语义的恢复才需要 Agent 提出 RecoveryProposal。

允许无需模型的恢复仅限：

- 同一 ResolvedExecutionCommand、同一 ExecutionCommandDigest、policy 允许的幂等技术重试；
- journal reconciliation；
- lease/fence 恢复；
- checkpoint replay；
- `policy_denied -> terminal/request_external_input`，由 DispositionPolicy 决定；
- `credential_missing -> external input/capability acquisition/environment wait`，由当前 acquisition options 决定；
- `stale_revision -> refresh facts and re-resolve`，但不得修改 AcceptedIntent；
- `budget_exhausted -> terminal/degraded control status`；
- 明确的 cancel/pause/timeout 状态转换。

如果恢复需要换 query、Goal、payload、语义不同 provider、降低证据标准或改变 requested result contract，则必须生成 `RecoveryProposal`。确定性 recovery policy 不能通过“最安全方案”或“最高分方案”掩盖语义分叉。

### 6.9 Final composition

Tool adapter 不再写 `state.answer`。包含业务结论、解释、总结、建议或跨 Goal 组合的答复，必须把已验证 Goal output、receipt summary、citation 和 degradation reason 放入 FinalAnswer context，由模型生成 `FinalAnswerProposal`。

确定性 Output Admission 只做内容安全、必需字段、引用完整性、敏感数据和 verified-output binding 检查；不拼接业务句子。被拒绝后由模型修订。

纯控制协议消息可以由确定性 Renderer 生成，例如“等待确认”“凭据缺失”“请求被 policy 拒绝”“模型暂不可用”“执行结果未知，正在核对”。Renderer 只能忠实映射 canonical state 和 reason code，不能包含任务结论、猜测、替代建议或将 Tool summary 伪装成业务答案。

## 7. Trace 与可恢复状态

保留三类记录并严格分工：

```text
AgentTraceSpan / AgentEvent
  model call、tool、handoff、guardrail、interrupt、latency
  面向调试、UI、eval，可采样、可演进，不是 canonical business state

Decision Audit Record
  model output、Proposal、Admission、DecisionFeedback、revision lineage、简短 rationale
  append-only、面向决策审计，但不进入业务 replay stream

DomainEvent / ExecutionEvent
  TaskContract、AcceptedIntent、ResolvedExecutionCommand、Grant、Journal、Receipt、Verification、Completion
  面向 projection、replay、audit，schema 严格、sequence 连续
```

每次 denied 必须可追踪：

```text
model_invocation
 -> proposal_created
 -> admission_denied(reason_codes)
 -> decision_feedback_created
 -> model_revision
 -> new_proposal_created
```

禁止记录 chain-of-thought；只保存结构化决定、简短 rationale、输入 projection 引用、输出 schema、token/latency 和错误。

DomainEvent sequence 不允许静默缺号。若预留后事务回滚，必须有 `event_sequence_voided` 事实或在提交时分配 sequence。

## 8. 需要删除或替换的代码

第一批直接删除：

- `AdaptivePlanner._compile_contract_plan`；
- invalid model plan -> deterministic contract plan fallback；
- `ExecutiveController._materialize_contract_action`；
- Runtime 在缺失 accepted mutation intent 时自动生成 mandatory Procedure invocation 的路径；
- `_procedure_decision` 中 description/constraints -> payload 拼接；
- Tool result adapter 写入 `state.answer`；
- mutation natural-language contains 作为确定性 Goal proof；
- Validator 内任何 model_copy 修正 Proposal 的路径；
- model unavailable 时的业务查询、计划、写入或答复 fallback。

替换为：

- typed Procedure input union；
- ModelGroundingClaim / SystemProvenanceRecord / AuthorityEvidenceRef；
- per-stage AdmissionDecision；
- DecisionFeedback revision loop；
- AcceptedIntent / ResolvedExecutionCommand / DerivationRecord；
- AuthorizationDigest / ExecutionCommandDigest binding；
- ExecutionFactReport / GoalVerificationReport 分层；
- FinalAnswerProposal + OutputAdmission。

## 9. 代码落点

| 模块 | 目标修改 |
| --- | --- |
| `planning/task_analyzer.py` | 输出 typed TaskAnalysisProposal 与 grounding claim，不产生权限 |
| `planning/task_compiler.py` | 冻结合法 Proposal 语义；只做带 DerivationRecord 的 contract derivation，删除语义补全 |
| `planning/adaptive.py` | 删除 contract-plan fallback；增加 PlanAdmission rejection loop |
| `runtime/control_runtime.py` | Executive 输出完整 ControlProposal；删除 deterministic action/payload synthesis |
| `runtime/contracts/control.py` | 定义 AcceptedIntent、immutable ResolvedExecutionCommand、DerivationRecord、typed inputs 与双 digest |
| `governance/decision_admission.py` | 扩展 grounding/scope/digest 校验，只裁决不修正 |
| `context/` | 拆分 visibility、requirement-driven retrieval、model selection、budget materialization |
| `capabilities/` | 定义 CapabilityEquivalenceClass；区分业务能力选择、能力获取与等价 implementation binding |
| `runtime/procedure_runtime.py` | Procedure 仅保留事务不变量与 typed node input |
| `execution/` | 持久化 resolved command；authorization/execution digest 与 grant、journal、receipt 全链绑定 |
| `verification/` | ExecutionFactVerifier 与 SemanticGoalVerifier 拆分 |
| `orchestration_nodes/_steps.py` | 删除 Tool adapter 最终答复副作用 |
| `orchestration/` | DecisionFeedback revision loop、interrupt/resume、trace/event sequence 收敛 |

## 10. 不兼容落地顺序

### Phase 0：架构门禁

1. 将本原则加入根 `AGENTS.md`。
2. 新增静态检查，禁止在 Validator/Admission 中出现 Proposal payload mutation。
3. 为每个现有分支标注 Decision Ownership Taxonomy；未标注的分支不得迁移。
4. 新增 architecture tests：AcceptedIntent semantics 与 Proposal semantic fields 完全一致；ResolvedExecutionCommand 必须持久化且具有 typed DerivationRecord。
5. 标记 deterministic business fallback 清单，区分“创造语义的 fallback”和“合法 contract derivation”，CI 在迁移完成后禁止前者重新出现。

验收：任何新增 deterministic branch 必须对应一个 invariant、typed policy 或 derivation rule；声称唯一结果时必须有可重放证明。

### Phase 1：重建 Proposal 与 Command contracts

1. Task schema 升级，不迁移旧 checkpoint。
2. 定义 per-stage Proposal、ModelGroundingClaim、SystemProvenanceRecord、AuthorityEvidenceRef 和 typed Procedure input。
3. 定义 immutable AcceptedIntent、immutable derived ResolvedExecutionCommand、typed DerivationRecord 和 supersedes lineage。
4. 定义 AuthorizationProjection、AuthorizationDigest、ExecutionCommandDigest，并修改 Confirmation、Grant、Journal、Receipt 的引用。
5. 定义带 mutable/immutable fields、required repairs、revision scope 的 `DecisionFeedback` 和 `ProposalFormatFeedback`。
6. 定义 context-aware DispositionPolicy，覆盖 `revise_model | request_external_input | request_capability_acquisition | await_environment_change | terminal`。
7. 删除旧 AcceptedCommand/RejectionObservation schema，不保留 alias 或双写。
8. 定义 intent/submission/rejection-equivalence hashes、DecisionCycleKey 和跨阶段 revision budget。

验收：任何 mutation 都可以从 receipt 反查到 Proposal、Admission、AcceptedIntent、DerivationRecord、ResolvedExecutionCommand、AuthorizationDigest、Confirmation 和 Grant；任何 denied Proposal 都能反查 DecisionFeedback、允许修改范围、disposition 和后续 Proposal/control state。

### Phase 2：删除 Planning/Executive fallback

1. 删除 `_compile_contract_plan`。
2. 删除 `_materialize_contract_action`。
3. 删除 Runtime 在没有 AcceptedIntent 时自动生成 ProcedureInvocation；新增 AcceptedIntent 到唯一 mandatory route 的纯 Compiler。
4. 将 Entry、Plan、Context、Control、Output Admission 接入统一 `ProposalRevisionProtocol`。
5. 增加 denied -> DecisionFeedback -> model revise loop、per-stage/cross-stage budget 与 DecisionCycleKey 检测。
6. 增加 external input、capability acquisition、environment wait 与 terminal durable routes。
7. 模型不可用时返回 typed terminal/waiting state，不生成业务结果。

验收：禁用模型时，系统不会产生新的 Plan、Action、query、payload 或 answer；revisable denial 会产生新 Proposal 并重新准入，terminal denial 不会循环调用模型。

### Phase 3：Context/Capability/Scheduler 收敛

1. Context 实现 visibility、requirement-driven retrieval、semantic selection、budget materialization 四阶段。
2. Capability requirement 由 Agent 提议，Resolver 只绑定等价实现。
3. Frontier 先做 DAG/priority 的唯一推导；有语义分叉时才请求 Agent；Scheduler 约束物理并发。
4. 所有 Resolver/Scheduler 结果引用 CapabilityEquivalenceClass、selection policy 和 typed DerivationRecord。
5. CoordinationPolicy 对明确唯一场景直接派生 mode，灰区才调用 Coordination model。

验收：管控层输出中不存在 Agent 未提议的 Goal/step/action intent；每个 derived route/frontier/provider 都能证明语义保持或候选等价。

### Phase 4：Mutation 与 Procedure

1. 全部 Procedure 改用 typed input。
2. 实现 AcceptedIntent 到 mandatory route 的唯一编译和 DerivationRecord。
3. prepare/confirm/commit/receipt 拆节点。
4. confirmation 绑定 AuthorizationDigest；grant/journal/receipt 绑定 ExecutionCommandDigest。
5. 删除自然语言 payload 拼装。
6. 增加 resume/replay 与 idempotency 故障注入。

验收：确认前无非幂等副作用；AuthorizationProjection 变化必须重新确认；等价 provider rebinding 产生新 Command/Grant，但 AuthorizationDigest 不变时可以复用有效确认；任何 invocation 与 ExecutionCommandDigest 不一致都会被 Gateway 拒绝。

### Phase 5：Verification 与 Final Answer

1. 拆分 ExecutionFactReport 与 GoalVerificationReport。
2. 删除确定性自然语言 contains 验证。
3. 将 VerificationGapObservation 替换为 VerificationFeedback。
4. 删除 Tool adapter 写 `state.answer`。
5. 增加 FinalAnswerProposal/Admission。
6. 增加只覆盖 canonical control status 的 deterministic Renderer。

验收：receipt 不能直接完成 Goal；模型判断不能推翻已验证 receipt；业务回答只引用 verified outputs；Renderer 输出不含业务结论。

### Phase 6：清理与文档切换

1. 删除旧 schema、旧 checkpoint fixture、兼容 serializer 和 deprecated reason code。
2. 更新当前架构文档，使本文从 future 变为 ADR/历史设计。
3. 运行全量 unit/integration/live E2E 与 crash-window 演练。

## 11. E2E 与评估矩阵

必须新增以下硬门禁，不使用软 aggregate score 掩盖失败：

| 场景 | 必须证明 |
| --- | --- |
| 模型给出完整合法 mutation | Admission 接受；Confirmation 绑定 AuthorizationDigest；Grant/Tool/Receipt 绑定 ExecutionCommandDigest |
| 模型给出泛化 payload | 写入前 denied；没有 Tool call；产生 DecisionFeedback；Agent 修订后重新 Admission |
| 模型遗漏 grounding | denied(`grounding_required`)；管控层不补 source |
| identity grounding 与原文不一致 | denied(`grounding_identity_mismatch`) |
| summarize transform | 管控层只验证权限/来源；语义 Verifier 判断忠实度 |
| 模型生成越权 Plan | PlanAdmission denied；产生新 PlanProposal；没有 deterministic fallback plan |
| 已接受 delete intent 且 policy 只有一个 route | 不追加模型调用；确定性生成 KnowledgeDeleteProcedure command；DerivationRecord 的 typed invariants 全部通过 |
| mandatory Procedure 显式冲突 | denied(`mandatory_procedure_bypass`)；不得执行冲突 route |
| 同一 intent 存在多个语义不同 route | 返回 `ambiguous_resolution` DecisionFeedback；模型/用户选择，不取 rank 第一名 |
| malformed structured output | bounded format revision；未生成 Proposal/AcceptedIntent/ResolvedExecutionCommand/Tool call |
| grounding-only denial | DecisionFeedback 只允许修改 grounding；模型修改 target/payload 时被视为越过 revision scope |
| 修正 grounding 后 intent 不变 | intent hash 可相同，但 submission/rejection-equivalence hash 改变；不得误判为重复非法 Proposal |
| revisable denial 后给出合法 Proposal | 新 Proposal 引用 superseded Proposal 与 DecisionFeedback；重新 Admission 后可执行 |
| 模型重复相同非法 Proposal | DecisionCycleKey 检测；消耗 revision budget；达到上限 typed terminal，不执行业务 fallback |
| 跨 Plan/Context/Executive 循环 | max_cross_stage_revision_cycles 生效；只有一个 active lineage；失效下游 refs 可追踪 |
| non-revisable policy denial | 不调用 revision model；直接 fail closed 或等待用户改变目标 |
| denial 需要外部权威输入 | durable interrupt；恢复后创建新 Proposal/InteractionDecision，不原地修改旧 Proposal |
| capability 未安装但允许获取 | 创建 durable AcquisitionRequest；环境更新后重新准入，不直接 terminal，也不让模型伪造能力 |
| provider 暂不可用且无等价候选 | await_environment_change；环境事件后重解析，不反复调用模型 |
| revision model unavailable | typed `model_revision_unavailable`/`awaiting_model`；没有业务动作或伪答复 |
| confirmation 后 AuthorizationProjection 被篡改 | AuthorizationDigest 改变；必须重新确认，Gateway 在 provider 前拒绝旧确认 |
| 等价 provider rebinding | 新 Command/ExecutionCommandDigest/Grant；AuthorizationDigest 不变且确认仍有效时不要求重复确认 |
| provider rebinding 改变 egress/trust/cost-risk | AuthorizationDigest 改变；必须重新确认 |
| Tool 成功但 receipt digest 不一致 | ExecutionFactReport failed，Goal 不得 verified |
| receipt 正确但语义目标未满足 | Execution fact passed、Goal verification failed，返回 Agent replan |
| Context 候选规模很大 | 显式 requirement 驱动确定性召回；模型只在压缩候选上语义选择；trace 保留召回规则与选择依据 |
| CoordinationPolicy 唯一确定 mode | 无额外 coordination 模型调用；DerivationRecord 可重放 |
| DAG/priority 唯一确定 frontier | 无额外模型调用；DerivationRecord 可复现；不改变 Plan 声明 priority |
| 多个语义不同 ready frontier | 由 FrontierSelectionProposal 选择；Scheduler 不静默取前 N |
| capability 存在等价 providers | 所有 CapabilityEquivalenceClass 字段一致后 Resolver 才绑定，并记录 class/policy reason |
| capability 候选语义不同 | 返回模型选择；不得用成本/排名覆盖语义差异 |
| replay 已解析 Command | 读取持久化 ResolvedExecutionCommand，不按最新 Registry/Policy 原地重算 |
| stale revision | AcceptedIntent 不变；创建 superseding Command、DerivationRecord 和 ExecutionCommandDigest；按 AuthorizationDigest 判断是否重确认 |
| policy denied/credential missing/budget exhausted | 直接进入唯一 control state；不反复调用模型绕过 policy |
| 模型不可用且需要业务回答 | 安全等待/失败；没有新业务动作或伪业务答复 |
| 模型不可用且只需状态消息 | Renderer 忠实输出 typed control status，不包含任务结论或替代建议 |
| interrupt 恢复 | 同一 run/ExecutionCommandDigest，确认前无重复副作用 |
| receipt 正确但 criterion 未满足 | 产生 VerificationFeedback 而非 Observation；RecoveryProposal 引用 unsatisfied criteria/evidence gaps |
| provenance ownership | 模型只能创建 ModelGroundingClaim；伪造 policy_derived/provider_observed 被 Admission 拒绝 |
| 最终答复 | 来自 FinalAnswerProposal，覆盖所有 verified Goal，不复用 Tool title 充当答案 |

每个 E2E trace 至少归档：

```text
Input
Model invocation + ContextProjection
Proposal
AdmissionDecision
DecisionFeedback / ProposalFormatFeedback
Proposal revision lineage
AcceptedIntent + semantic digest
DerivationRecord
ResolvedExecutionCommand + AuthorizationDigest + ExecutionCommandDigest
Confirmation/Grant digest bindings
Invocation/Receipt
ExecutionFactReport
GoalVerificationReport
VerificationFeedback when failed
CompletionReport
FinalAnswerProposal or deterministic StatusMessage
Output
```

## 12. 评审检查表

每个 PR 必须回答：

1. 新逻辑属于 Decision Ownership Taxonomy 的哪一类？
2. 若是 contract derivation，唯一性来自哪些 accepted fields、policy 和 facts？是否有可重放、无自由文本断言的 typed DerivationRecord？
3. 它是否新增或改变 Goal、Action intent、target、payload、requested result contract、语义相关性或业务表达？若是，为什么不是新 Proposal？
4. denied 后是否返回 typed DecisionFeedback，而不是伪装成 Observation 或静默 fallback？
5. DispositionPolicy 是否结合 runtime/acquisition options 区分 model revision、external input、capability acquisition、environment wait 和 terminal？
6. DecisionFeedback 是否明确 mutable/immutable fields、required repairs 和 revision scope？
7. revision 是否有 per-stage/cross-stage budget、唯一 active lineage、supersedes/invalidation refs 和 DecisionCycleKey？
8. AcceptedIntent 是否与 Proposal 语义字段完全相同，ResolvedExecutionCommand 是否持久化、不可覆盖且只缩权？
9. Confirmation 是否只绑定 AuthorizationDigest，执行链是否绑定 ExecutionCommandDigest，rebinding 是否正确决定重确认？
10. 是否存在 raw dict、空字符串或默认值绕过 typed boundary？
11. 是否把 retrieval ranking、provider ranking 或字符串启发式冒充唯一语义判断？
12. Capability 候选是否通过正式 equivalence class，而不是仅凭相同输出形态宣称等价？
13. 是否把 deterministic execution fact、VerificationFeedback 与 external Observation 混为一谈？
14. replay 是否会重新调用模型、重新解析已提交 Command 或重复副作用？
15. denied Proposal 是否进入 Decision Audit Store 而非污染 canonical Domain Event stream？
16. trace 能否解释 Proposal、Admission、Feedback、Derivation、Command、Execution、Verification 的完整因果链？

无法回答第 1 至第 2 项的确定性分支不得合入；第 3 项若引入开放语义，必须改成 Proposal；其余任一不满足时，功能不得宣称完成。

## 13. 最终不变量

- 模型拥有开放语义决策权，但不拥有执行权限和事实写入口。
- 确定性系统拥有准入、契约推导和状态提交权，但不创造业务意图。
- 确定性逻辑可以推导，但不得发明；模型可以提议，但不得授权或提交。
- Validator 只接受或拒绝，永不修理 Proposal。
- 可修订 denial 必须返回模型生成新 Proposal；外部输入、能力获取和环境等待使用各自 durable route；不可修订 denial 或预算耗尽时才 fail closed。
- Revision 不得原地修改 Proposal，不得免除二次 Admission，不得持久化 chain-of-thought。
- DecisionFeedback 必须限制 revision scope；跨阶段只能有一个 active revision lineage，并受 DecisionCycleKey 和全局 cycle budget 管控。
- AcceptedIntent 逐字冻结 Proposal 语义；ResolvedExecutionCommand 是持久化、不可覆盖、只缩权的 immutable derived contract。
- DerivationRecord 只保存可重放的 rule/version、digest、封闭 uniqueness kind 和 typed invariant results，不保存自然语言“证明”。
- Confirmation 绑定 AuthorizationDigest；Grant、Journal 和 Receipt 绑定 ExecutionCommandDigest；执行绑定变化不自动等于用户授权变化。
- mandatory Procedure 不能创造业务 intent，但可以把已接受 intent 编译到唯一合法 route。
- 用户/TaskContract/Admin 的明确语义高于模型；模型只选择剩余开放语义。
- 语义不同候选交给模型或外部权威；只有满足 CapabilityEquivalenceClass 的等价实现才可由 Resolver/Scheduler 优化。
- 模型不可用时不得生成业务替身，但可执行已冻结命令、唯一控制状态转换和纯状态渲染。
- Execution fact 与 Goal semantics 分离，任何一方都不能冒充另一方。
- Tool success 不等于 Goal success，Goal success 不等于 Task completion。
- Proposal 只声明 requested result contract；execution outcome、verification outcome 和 completion status 只能由对应事实 owner 建立。
- Checkpoint 用于恢复，Domain Event 用于 canonical 事实，Decision Audit 用于拒绝/修订审计，Trace 用于运行解释；四者不互相冒充 owner。
- Agentic 来自模型动态选择过程；可信来自确定性 reference monitor 对每个提案的边界管控。

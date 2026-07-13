# 知识 Agent 元能力运行时当前状态

本文只总结当前代码事实。目标原则、评估方法和 Phase 设计见 [知识 Agent 元能力组合设计](../future/meta-capability-composition-design.md)。

## 结论

当前主链路已从“Router 选 workflow / Pattern，再执行预编译完整步骤”切换为任务级 Executive Loop：

```text
EntryInput
  -> EntryGraph：规范化、语义理解、必要时澄清
  -> GoalInterpreter：TaskSpec + SuccessCriteria + ContextEnvelope
  -> append-only ExecutionEvent -> ExecutionLedger
  -> ExecutiveGraph
       project ControlState
       -> decide one ControlDecision
       -> deterministic validation
       -> execute one BoundedAction / ProtocolCall / SubtaskSpec
       -> observe ActionOutcome
       -> verify goal
       -> decide again
  -> CompletionVerifier
  -> final EntryResult
```

所有非澄清请求经过同一个顶层 `ExecutiveGraph`。Router 只表达用户目标和 Goal，不选择 MCP server、tool、A2A Agent、Execution Pattern 或固定执行拓扑。

## Agentic 如何体现

当前 Agentic 不等于“所有控制都交给模型”，而是智能决策与确定性管控分层：

| 层 | 智能职责 | 确定性约束 |
| --- | --- | --- |
| Goal understanding | 理解目标、拆分 Goal、识别语义资源 | `TaskSpec` schema、criterion origin/mutability、预算 |
| Executive | 根据 Ledger、observation、gap 选择下一动作 | 强类型 `ControlDecision`、`DecisionValidator`、循环上限 |
| Capability | 根据 requirement 选择 native/MCP/A2A 实现 | coverage、policy、scope、lexicographic ranking |
| Executor | 在动作内部检索、推理、ReAct 或委派 | `BoundedAction` 预算、read/write set、allowed tools |
| Protocol | 执行知识写入、删除、Research lifecycle 等事务 | 固定 transition、HITL、幂等、admission、receipt |
| Verification | 判断 criterion 是否满足、是否可以完成 | `GoalVerifier` 和 `CompletionVerifier` 独占状态转换 |

模型可以建议动作，但不能直接修改 Ledger 事实、扩大权限、跳过确认、把 step success 写成 goal verified，或自行宣布任务完成。模型不可用时，Executive 使用同一 contracts 下的确定性策略退化，不切回旧 workflow controller。

## 核心状态

### TaskSpec

`TaskSpec` schema v2 保存：

- 用户目标、outcome kind、subjects 和 resource requirements；
- requested operations、预算、并行度和最大 Executive turn；
- 带 origin、mutability、evidence policy 的成功标准；
- evidence requirements、mutation intent 和生命周期。

### ExecutionLedger

`ExecutionLedger` 是任务进度事实源，不再保存 `active_pattern` 或预编译完整 DAG。它由 append-only `ExecutionEvent` 确定性投影，记录：

- Goal 的 pending/active/blocked/candidate/verified/degraded/abandoned 状态；
- capability coverage、evidence gap 和 action attempt；
- 已激活 Skill、已采用 Plan Macro 和 verification report；
- revision 与 event sequence。

终态 Goal 不允许被普通动作重写。失败 action 也会写入 attempt，因此有副作用的 Protocol 不会因失败而被 Executive 无依据重复调用。

### ControlState 与 ControlDecision

每轮从 TaskSpec、Ledger、observation、可用 capability class、待确认项和剩余预算投影 `ControlState`。Executive 每轮只生成一个强类型决策：

```text
clarify
activate_skill
revise_plan
execute_meta_capability
execute_parallel
delegate
invoke_protocol
request_confirmation
finish
stop
```

每个决策携带 `DecisionBasis`，关联未满足 criterion、触发 observation、evidence gap、预期状态变化和被拒动作代码。重复语义决策由 loop guard 停止。

## Bounded Action

开放式工作只物化当前一个 `BoundedAction`，而非一次生成完整步骤图。动作包含：

- `acquire/explore/reason/transform/verify/delegate/commit/remember` 元能力；
- 输入 artifact、输出 contract 和 capability requirement；
- tool/model/iteration 预算与 deadline；
- read set、write set、side-effect class；
- approval 与 protocol dependency。

`ActionExecutionGraph` 只是当前动作的执行器。确定性调用、局部 ReAct 和 AgentGateway 都不能修改任务计划；它们只能返回 `ActionOutcome` 或 observation，由 Executive 决定下一步。

## Skill 与 Plan Macro

`SkillCatalog` 采用渐进加载：Executive 先看到 description，激活后才把完整 instructions 和 verifier profile 放入任务上下文。当前内置方法包括 code investigation、evidence research、knowledge curation 和 decision support。

旧 Execution Pattern 已降级为可选 `PlanMacro`。Macro 只能提交受限 Ledger patch 和验证先验，不能绑定 provider、授予权限或宣布完成。一个复合任务可以采用多个 Macro，也可以完全不用 Macro。

## Capability、MCP 与 A2A

Capability Registry 统一收录 native tool、MCP tool、retriever 和 Agent。Resolver 的职责是：

```text
requirement
  -> eligibility / policy filtering
  -> coverage: satisfied / partial / unavailable / denied
  -> lexicographic rank
  -> allowed tools / agents
```

排序不再把信任、资源绑定、操作覆盖和偏好混成一个可相互抵消的加权总分。授权仍由 PolicyEngine 决定，调用必须经过 ToolGateway 或 AgentGateway。

MCP 融入 `acquire/explore`，是可动态选择的 provider，不是一级 workflow。A2A 融入 `delegate`：Executive 先产生 provider-neutral `SubtaskSpec`，Resolver 在执行前选择 Agent，主 Agent 保留上下文、验证和最终回答所有权。Agent artifact 默认是不可信 observation，结构通过不等于事实已验证。

## Protocol

capture、solidify、delete、Research lifecycle、订阅和运维类事务通过 `ProtocolRegistry` 暴露为 `ProtocolCall`。Protocol 内部仍可使用确定性步骤和 LangGraph interrupt，但它不再拥有顶层路由权。

Protocol 边界强制执行：

- side effect 不能由普通 BoundedAction 执行；
- durable memory mutation 经过 `MemoryAdmissionGate`；
- confirmation 与具体调用绑定；
- ToolGateway 继续执行 scope、policy、audit 和幂等检查；
- 成功必须返回可验证 Mutation Receipt；
- 失败或不确定结果作为 observation 返回 Executive。

capture 和 solidify 先返回 `waiting_confirmation`，确认后从同一 checkpoint 恢复。这是有意采用的不兼容行为。

## Verification 与完成

动作成功只产生 candidate，不产生 verified：

```text
ActionOutcome(succeeded)
  -> goal_candidate_complete
  -> GoalVerifier checks criterion-specific evidence
  -> goal_verified or goal_activated with gaps
```

`finish` 必须携带 `CompletionClaim` 并经过 `CompletionVerifier`。只要仍有 unresolved goal、未满足 required criterion、待确认项或缺失 completion claim，Runtime 就拒绝完成并把缺口返回 Executive。

复合 capture + ask 的当前行为是：确认写入后，将 Mutation Receipt 作为当前任务的 evidence artifact 准入 `ContextEnvelope`，后续 ask 消费该产物并分别验证两个 Goal，最后才允许完成。这避免“写入成功但后续目标看不到刚产生的知识”。

## 恢复与可观测性

LangGraph checkpoint 保存 TaskSpec、ControlState、Ledger、当前 action、observation、ReAct、Protocol 和 confirmation 状态。当前保留：

- checkpoint resume；
- 完整 checkpoint replay/fork；
- event-sourced projection 和 debug bundle；
- action input/output/error artifact；
- SSE decision、protocol、verification 和 completion events。

旧 step 级 fork、workflow state migration、step mapping 数据表和公共 API 已删除。新旧 workflow step 不能跨版本复用为“已完成事实”，避免绕过当前 Goal/Completion Verification。

## 已删除的旧控制链

当前代码已移除：

- `MetaPlanCompiler` 顶层控制与 `_select_pattern()`；
- `IntentPlan`、`active_pattern`、`allowed_patterns` 和 `source_intents` 控制语义；
- 预编译完整任务 DAG 后按索引执行的顶层循环；
- 失败后自由追加 ExecutionStep 的 `Replanner` 及 prompt；
- step type 为 verify 就直接写 verified；
- provider-specific intent 到 MCP/A2A/workflow 的顶层执行映射；
- step 级 fork 与 workflow state compatibility migration。

## Phase 落地状态

| Phase | 当前状态 |
| --- | --- |
| 1 TaskSpec、criterion、revision | 已落地 |
| 2 Ledger、Goal/Completion Verification | 已落地 |
| 3 ExecutiveGraph 与强类型决策 | 已落地 |
| 4 Bounded Action、Executor、Recovery | 已落地 |
| 5 Capability gap 与动态 provider resolution | 已落地 |
| 6 动态 Skill 与 Plan Macro | 已落地 |
| 7 A2A、只读并行 contract、artifact admission | 已落地 |
| 8 Protocol 收口与唯一主入口 | 已落地 |
| 9 删除旧控制链与系统回归 | 已落地 |

## 当前边界

- Executive 可使用 structured model 决策，但测试和无模型环境主要覆盖确定性 fallback；真实模型的决策质量仍需独立 eval，而不是用单一 golden path 判断。
- `execute_parallel` 已有依赖、读写集、side effect 和预算校验；当前动作执行器采用确定性 join/调度，尚未把 wall-clock 并发作为正确性前提。
- A2A 已实现动态 capability binding、最小 SubtaskSpec 和结构验证；跨 provider 事实交叉验证仍由主 Agent 的后续 evidence action 完成。
- Skill/Macro 是代码内版本化 catalog，尚无独立部署、灰度和在线质量存储。
- Research 内部策略仍有领域专用决策循环，但生命周期和副作用边界已由 Protocol 持有，不再作为顶层 Agent controller。

## 验证状态

本次落地后的验证：

```text
python compileall src/personal_agent: passed
focused Executive / Protocol / API regressions: passed
full pytest: 874 passed, 4 warnings
git diff --check: passed
```

全量测试需要设置：

```text
PERSONAL_AGENT_POSTGRES_URL=postgresql://postgres:postgres@127.0.0.1:5432/personal_agent_test?sslmode=disable
```

## 代码事实源

| 主题 | 当前事实源 |
| --- | --- |
| Task/Ledger/Skill contracts | `kernel/contracts/agentic.py` |
| ControlDecision/BoundedAction contracts | `kernel/contracts/executive.py` |
| Goal interpretation | `planning/goal_interpreter.py` |
| Executive policy | `planning/executive.py` |
| Ledger projection | `planning/ledger.py` |
| Decision validation | `planning/decision_validator.py` |
| Goal/Completion verification | `planning/verification.py` |
| Skill/Macro catalog | `planning/skills.py` |
| Protocol registry | `planning/protocols.py` |
| Capability resolution | `planning/capability_resolver.py` |
| Executive nodes | `orchestration/orchestration_nodes/_executive.py` |
| Executive/Action/ReAct graph | `orchestration/orchestration_graph.py` |
| checkpoint state | `orchestration/orchestration_models.py` |
| deterministic action/Protocol executor | `orchestration/orchestration_nodes/_steps.py` |
| scoped ReAct executor | `orchestration/orchestration_nodes/_react.py` |

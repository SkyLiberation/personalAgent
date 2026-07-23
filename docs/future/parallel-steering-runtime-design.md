# 并行 Join 与语义 Steering 后续设计

## 定位

Agent Harness 的 Goal、Executive、Resolution、Context、Skill、Durable Run、异步 Subagent、Verification 和 outcome-aware ranking 具有不同接入程度，当前事实以 [核心架构与主链接入状态](../summary/core-architecture-current-state.md) 为准。

本文只服务已经由具体领域 Aggregate 或 `ChildAgentRun` 证明需要长生命周期控制的运行，不让简单 Message 或普通 ToolCall 为未来并行/steering 承担额外状态。能力边界和主运行循环见 [Capability-first Knowledge Agent Runtime](adaptive-agent-runtime-design.md)。本文只保留尚未落地的两项能力，不重复历史 Phase，也不提供旧 Router、Workflow、Protocol、Pattern 或同步 A2A 兼容设计：

1. 独立本地 read action 的真正并发执行与显式 join；
2. 用户在运行中改变重点、追加目标或调整输出形式的语义 steering。

## 当前边界

当前远程 Subagent 使用 `submit -> poll`。Action loop 会先提交所有已就绪 child run，再公平轮询，因此远程 child 可以物理并发，父链也可以继续执行其他已就绪动作。

当前 `AdaptivePlan + FrontierDecision` 已表达语义 ready set，`DispatchGroup` 契约和 Scheduler `validate_dispatch` 已进入主链，但生产 profile 的 `max_frontier_width=1`，`can_run_concurrently` 尚无正式调用者；本地 tool、retriever、compose action 仍按 LangGraph checkpoint 顺序执行。旧 `ExecuteParallelDecision` 已删除，物理并发不能由 Executive 绕过 Resolver/Scheduler 直接声明。`pause / resume / cancel` API 已存在并持久化状态，但活跃 Graph 尚无逐 dispatch `RunControlGuard`、lease heartbeat 和完整父子 cancel 传播，因此不能称为已闭合控制面；它们与语义 steering 仍是不同问题。

## 并行 Join

### 契约

并行分三层表达，避免 Planner 或 Executive 根据未解析资源直接决定物理并发：

```text
FrontierDecision
  selected_step_ids
  priority_order
  requested_join_policy: all | any | quorum
  rationale
```

Planner 只表达 step dependency，PlanLedger 根据最新状态投影 ready frontier；Executive 从该集合选择本轮值得共同推进的 step，并输出 `FrontierDecision`。这只是语义 batch，不承诺实际并发。

Resolver 对 batch 中每个 step 生成 `ResolvedActionSpec`，补齐 provider、read/write set、side effect、quota 和 deadline。Scheduler 随后生成 `DispatchGroup`：

```text
group_id
action_ids
join_policy: all | any | quorum
quorum
deadline
failure_policy
resolved_resource_snapshot
```

Scheduler 可以拆分、串行化或拒绝 FrontierDecision，但不能增加 Executive 未选择的语义 step，也不能修改 GoalGraph/AdaptivePlan。实际 join policy 不得弱于 Procedure、Verifier 或 policy 要求。

### 执行约束

- 只有完整 resolved read set 且 `side_effect_class=none` 的 action 默认并发；
- mutation 只有 Procedure 明确声明 write set、隔离级别和 parallel-safe 时才可并发；
- 每个 branch 使用独立 ContextProjection 和 PostgreSQL execution artifact namespace；
- branch 不能直接合并 Ledger，join 节点按事件序列重放 Observation；
- `any/quorum` 提前满足后取消剩余 child，晚到 artifact 标记为 orphan candidate；
- join 后仍进入 GoalVerifier 和 CompletionVerifier。
- `max_frontier_width` 来自 PlannerExecutionProfile；未通过 parallel 专项门禁的 profile 固定为 1。

### 验收

- 两个独立延迟 read action 的 wall-clock 明显低于串行基线；
- read/write 冲突和 locator 不完整时 fail closed；
- branch event、artifact、预算和取消均可回放；
- join 顺序不改变 criterion coverage 和最终完成判断。
- Executive 选择两个可并行语义 step 时，资源冲突仍会被 Scheduler 串行化；无冲突时才形成同一 DispatchGroup。

## 语义 Steering

### 控制面与任务面分离

以下命令继续直接进入 DurableRunManager：

```text
pause | resume | cancel
```

以下输入属于任务语义，必须经过 TaskAnalyzer：

```text
追加目标
改变调查重点
调整输出格式或优先级
撤销尚未提交的可变目标
```

TaskAnalyzer 输出 `TaskContractRevisionProposal`，引用当前 task revision、用户输入和受影响 Goal。Revision Admission 保证：

- immutable user criterion 不可删除或弱化；
- 已提交 mutation 不可被假装撤销；
- 新资源需求重新经过 Capability Resolution；
- 正在运行的 child 由 Executive 决定继续、取消或降级为旁证；
- revision 使用 compare-and-set，过期 steering 明确冲突。

TaskContract revision 提交后产生 `ReplanRequest(source=user_steering)`，由当前主链的 `AdaptivePlanner` 基于新 revision 创建 PlanPatch 或替换短视窗计划。Steering 不允许直接修改 PlanDefinition、TaskRuntimeProjection 或正在执行的 ResolvedAction。

### 验收

- steering 不 fork 丢失原 run，也不直接改写 Ledger；
- 同时到达的 steering 通过 revision 冲突收敛；
- 取消 child 可观测，晚到结果不能完成父 Goal；
- replay 能解释用户输入、TaskContract revision、Executive 决策和最终验证之间的因果链。

## 落地顺序

1. 接入逐 dispatch `RunControlGuard`、lease/fence 复检和父子 cancel 传播。
2. 增加 branch event reducer、join executor、late result/orphan artifact 处理和 join verifier fixture。
3. 把本地 read action dispatch 迁到 worker slot，保留远程 child 的现有 submit/poll 契约。
4. 增加 TaskContractRevisionProposal 与 revision CAS。
5. 接入 Web/CLI steering API 和 trajectory eval。

任何阶段都不得通过恢复业务关键词 Router、固定 workflow DAG 或未解析工具名来缩短实现。

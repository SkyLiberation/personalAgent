# 动态规划当前实现

当前规划由“协调成本”和“执行路径”两个正交维度组成：

```text
TaskContract + TaskRuntimeProjection + Observation
  -> CoordinationMode: reactive | deliberative
  -> optional short-horizon Plan
  -> Executive ControlProposal
  -> Admission + AcceptedControlCommand
  -> ExecutionRoute + Capability Resolution
  -> Observation / Monitor / Verification
```

## CoordinationMode

Reactive 表示一个有界动作可能直接推进 Goal；Deliberative 表示多 Goal、依赖、证据路线或不确定性值得维护短 horizon Plan。Procedure、Tool、ReAct 和 Delegation 是 ExecutionRoute，不是 mode。

## Plan 单位

只有 deliberative 创建 `PlanDefinition`。Plan step 是 provider-neutral 语义步骤，只保存 Goal、依赖、`CapabilityRequirement`、预期 Observation 与 failure class。`PlanRuntimeProjection` 只保存 step status 与 cursor，不复制 Definition。

`FrontierSelector` 选择依赖满足的 step；`PlanMonitor` 根据 Observation 决定 keep、retry、patch、replace、request input 或 stop。Patch 引用 task/plan revision 和 event cursor，用 CAS 防止旧计划覆盖新状态。

## Executive 单轮控制

Executive 不预生成完整 Workflow，每轮只生成一个 `ControlProposal`。Governance admission 接受后才编译 `AcceptedControlCommand`；CapabilityResolver 再绑定具体能力。失败和能力缺口都先成为 Observation，再影响下一轮控制。

## 模型与确定性职责

模型负责语义候选、Goal 选择、信息增益和最小计划提案。确定性模块负责 schema、identity、revision、dependency DAG、budget、scope、Policy、Grant、Mutation/HITL、Journal/outbox 和 Verification。

# 动态规划当前实现

动态规划已不是“未来再接一个生成完整步骤列表的 Planner”。当前实现是任务级、增量式 Executive Loop：

```text
TaskAnalysis
  -> GoalGraphCompiler
  -> ControlState
  -> one ControlDecision
  -> one BoundedAction / Delegate / Protocol
  -> Observation
  -> Goal Verification
  -> next decision
```

## 计划单位

Runtime 不预编译开放任务的完整 step DAG。每轮只物化当前动作，并保留：

- TaskSpec 与 success criteria；
- typed Goal Graph；
- append-only ExecutionEvent；
- ExecutionLedger；
- latest Observation；
- remaining budget；
- active Skill 与 adopted Plan Macro。

这样新证据、provider 失败、授权缺口或用户补充能影响下一轮决策，而不需要废弃并重建整份计划。

## 关系修订

Task Analyzer 提出的关系是初始假设。Executive 可基于 Observation 提出 `add_dependency/remove_dependency/update_dependency`，但 Patch 必须：

- 引用触发事件；
- 只修改 inferred/runtime relation；
- 保持端点有效和阻塞图无环；
- 不重写 terminal Goal；
- 不让开放 Goal 依赖 abandoned Goal。

## Protocol 边界

稳定事务使用 ProcedureSpec 投影内部节点。这不是第二套顶层 Planner：Executive 决定是否调用 Procedure，ProcedureMaterializer 只物化该事务的确定性内部图。

## 模型与确定性职责

模型负责目标选择、信息增益、动作类型、能力需求和是否需要修订假设。Runtime 负责 schema、预算、scope、policy、依赖图、副作用、HITL、事件投影和完成验证。

因此当前口径是“incremental deliberation + deterministic control”，不是 workflow-first，也不是无约束 autonomous planner。

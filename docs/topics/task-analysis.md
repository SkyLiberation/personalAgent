# Task Analysis 与 Goal Graph

入口不再使用 Intent Router。当前职责拆成两个边界：

```text
EntryInput + conversation context
  -> DefaultTaskAnalyzer (semantic model)
       TaskAnalysis: user_goal / goals / initial relations / resource hints
  -> GoalGraphCompiler (deterministic)
       TaskSpec / SuccessCriteria / ExecutionLedger / ContextEnvelope
  -> Executive Loop
```

## Task Analyzer

事实源是 `planning/task_analyzer.py`。模型输出 `TaskAnalysisOutput`：

- `Goal.description` 表达可验证结果；
- `intent_hint` 是语义或 Protocol 提示，不决定顶层 workflow；
- `ResourceHint` 表达语义域、操作、资源类型和用户要求的 provider binding；
- `GoalRelation` 独立于 Goal，避免把语义对象和调度状态混在一起；
- Analyzer 不读取 Capability Registry，不输出 coverage，不选择 MCP/A2A/tool。

生产路径没有关键词式离线分类。空输入由结构规则澄清；模型不可用时返回 `analyzer_unavailable`，避免将不可靠的关键词猜测伪装成任务理解。

## Goal Relation

关系有三类：

| kind | 语义 | 是否阻塞 |
| --- | --- | --- |
| `consumes_output` | 后继必须消费前驱产物 | 是 |
| `requires_completion` | 前驱完成是后继的事务前提 | 是 |
| `ordering_preference` | 只表达执行或展示偏好 | 否 |

关系还记录 `origin` 和 `rationale`。`user_explicit` 不可由 Runtime 修改；`model_inferred` 与 `runtime_derived` 可以在 Observation 推翻原假设后通过受约束 Patch 调整。

## Compiler 与 Validator

`planning/goal_graph.py` 使用 Compiler + Specification/Validator：

1. 校验 Goal ID、关系端点、重复关系和阻塞环；
2. 将 ResourceHint 编译为 Goal-scoped `ResourceRequirement`；
3. 编译 success criteria、mutation intent 和 evidence policy；
4. 将 Relation 编译为 Ledger item 上的 typed dependency；
5. 仅有未满足阻塞关系的 Goal 初始为 `pending`。

这一步没有模型调用，也不推断新关系。

## Runtime Revision

Executive 能看到完整 Goal Graph、ready Goal 和最新 Observation。模型可以提出最小的 `add_dependency`、`remove_dependency` 或 `update_dependency`，但不能直接改 Ledger。

`LedgerPatchValidator` 要求依赖修改引用触发 Observation，并校验关系可变性、端点、阻塞环、终态 Goal 和 abandoned 传播。通过后形成 `goal_dependency_added/removed/updated` 与 `plan_revised` 事件，再由 Projector 更新 Ledger。

因此初始分析是可执行假设，不是一次性冻结的完整计划。

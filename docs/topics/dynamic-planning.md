# Dynamic Planning

本文说明未来真正 dynamic planning 能力的边界。当前生产主路径没有默认启用 autonomous planner；固定业务流程仍由 `WorkflowSpec / WorkflowRegistry` 声明，并通过 `WorkflowStepProjector` 投影为 `ExecutionStep`，详见 [当前 Workflow 框架总览](../workflow/workflow-framework.md)。

Dynamic planning 只用于系统没有固定 workflow、风险较低、工具范围明确、且配置显式启用的开放式任务。它不是 `delete_knowledge`、`solidify_conversation` 等已知高风险流程的替代品。

## 目标

Dynamic planner 的目标是让模型在受控边界内生成临时步骤 DAG，再交给同一个 `StepExecutionGraph` 执行。它只负责提出步骤，不直接绕过工具治理、HITL、幂等账本、审计和 checkpoint。

目标形态：

```text
DynamicPlanner
  -> DynamicPlan
  -> PlanDAGValidator
  -> list[ExecutionStep]
  -> StepExecutionGraph
```

## 触发条件

只有同时满足这些条件，才允许进入 dynamic planning：

- Router 无法映射到固定 workflow。
- 用户目标低风险，且不会触碰删除、外发、付款、生产变更或跨用户数据。
- 可用工具来自明确 allowlist。
- 配置显式启用 dynamic planning。
- 有专项 eval 覆盖该类任务。
- 生成的计划必须能转成 `ExecutionStep` 并通过 validator。

## 禁用场景

以下场景永远优先使用固定 workflow 或直接拒绝，不交给 dynamic planner：

- `delete_knowledge`
- `restore_note`
- `solidify_conversation` 的长期写入主干
- 外发消息、付款、生产变更
- 跨用户数据操作
- 权限或资源边界不明确的工具组合
- 任何高风险、需要确认、或有不可逆副作用的动作

## Guardrail

Dynamic planning 必须至少具备这些保护：

- `DynamicPlan` 使用结构化 schema，不接受自由文本步骤。
- `PlanDAGValidator` 校验依赖图、工具 allowlist、参数 schema、风险等级和确认要求。
- 所有工具调用仍进入 `ToolGateway`。
- 高风险工具不得进入 dynamic planning allowlist。
- ReAct 只能作为单个低风险 step 的内部策略。
- checkpoint replay 只支持新 `step_execution` schema。
- 事件和 run snapshot 只暴露 `steps` / `step_execution` 语义。

## 与 Step Projection 的关系

Step projection 是当前已落地能力：固定 workflow 是真源，投影步骤只是运行时视图。

Dynamic planning 是未来能力：模型动态生成 `DynamicPlan`，再被转换为 `ExecutionStep` 并进入相同执行器。

二者共享执行层，但步骤来源不同：

| 来源 | 生成方式 | 当前状态 | 执行器 |
| --- | --- | --- | --- |
| Workflow step projection | `WorkflowSpec` 确定性投影 | 已落地 | `StepExecutionGraph` |
| Dynamic planning | 模型生成 `DynamicPlan`，validator 转换 | 未默认启用 | `StepExecutionGraph` |

## 推荐口径

可以说：当前项目已经具备 workflow-first 的 step projection 和 checkpoint-safe step execution，但还没有默认启用通用 autonomous planner。未来 dynamic planning 会作为独立模块进入同一个执行器，而不是替代固定 workflow。

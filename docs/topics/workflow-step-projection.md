# Workflow / Step Projection 层

当前项目采用 workflow-first 架构。所有已识别 Goal（ask、capture、summarize、delete、
solidify、direct_answer）都由 `WorkflowPlanner` 编译后进入 `StepExecutionGraph`。
`direct_answer_branch` 仅承担无 Goal、Router 不可用或 step projection 校验失败后的 fallback，
不再是正常业务 workflow 的第二条执行路径。

固定业务流程的真源是 `WorkflowSpec / WorkflowRegistry`。`WorkflowPlanner` 选择 active spec，并把一个或多个 Goal 确定性编译为跨 workflow 的 `ExecutionPlan` 与 `ExecutionStep` DAG，再进入 `StepExecutionGraph`。开放式动态规划不是当前生产主路径，边界见 [Dynamic Planning](dynamic-planning.md)。

对应代码主要位于：

- [workflow.py](../../src/personal_agent/agent/workflow.py)
- [workflow_validator.py](../../src/personal_agent/agent/workflow_validator.py)
- [workflow_planner.py](../../src/personal_agent/agent/workflow_planner.py)
- [execution_models.py](../../src/personal_agent/agent/execution_models.py)
- [step_projection_validator.py](../../src/personal_agent/agent/step_projection_validator.py)
- [orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)
- [orchestration_nodes/_steps.py](../../src/personal_agent/agent/orchestration_nodes/_steps.py)
- [orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py)

## 运行链路

```text
EntryInput
  -> route_intent
  -> workflow planning
       project_workflow_steps
       validate_projected_steps
       prepare_step_execution
       select_next_step
       execute_step
          -> react_graph?
          -> step_tool_node?
          -> confirm_step?
       consume_step_tool_result
       handle_step_success / handle_step_failure
       finalize_step_execution
  -> direct_answer_branch（仅 fallback）
```

正常业务 workflow 统一生成 `steps`。父图不再维护 ask、capture、summarize 的直连 branch，
从而避免 WorkflowSpec 与 branch 函数成为两个行为事实源。

## 核心模型

| 模型 | 职责 |
| --- | --- |
| `WorkflowSpec` | 固定业务流程真源，声明步骤、依赖、分支、副作用和恢复策略 |
| `WorkflowStepSpec` | workflow 内部节点契约 |
| `ExecutionStep` | workflow step 的运行时投影视图 |
| `StepRunState` | checkpoint 中单个步骤的运行态 |
| `StepExecutionState` | checkpoint 中步骤执行子状态，包含 steps、current index、results、retry counts |
| `StepProjectionValidator` | 执行前校验 action、依赖、工具 schema、风险、确认和 intent 规则 |

## Workflow 与 Step Projection

Workflow 是系统维护的业务契约，不是模型临时生成的步骤列表。它回答“这类 intent 应该按什么路径执行、哪些节点有副作用、哪些节点需要 LLM 做局部语义判断、失败时如何恢复”。

Step projection 是 workflow 的运行时视图，服务这些工程需求：

- 前端展示步骤状态。
- LangGraph checkpoint 恢复步骤进度。
- HITL 暂停和恢复。
- 工具执行前校验。
- 审计和 run history 摘要。
- 步骤间通过 `step_execution.results` 传递结构化结果。

## 当前 Workflow 类型

| 类型 | 特征 | 例子 |
| --- | --- | --- |
| Branch workflow | 由 LangGraph 普通分支直接执行，不生成 `ExecutionStep` | `ask`、`capture_text`、`capture_link`、`capture_file`、`direct_answer`、`summarize_thread` |
| Step projection workflow | 固定 workflow 仍是真源，但会投影成步骤视图并进入步骤执行图 | `delete_knowledge`、`solidify_conversation` |

## 执行边界

`StepProjectionValidator` 是步骤进入执行图前的硬边界。它会校验：

- step id 唯一、依赖可解析、依赖图无环。
- `action_type / risk_level / on_failure / execution_mode` 合法。
- 工具存在于 `ToolExecutor`。
- 工具参数满足 Pydantic args schema。
- 高风险工具必须要求确认。
- ReAct step 只能使用低风险 allowlist 工具。
- intent 特定规则，例如删除必须包含 `delete_note` 且要求确认，固化必须写入 `capture_text`。

通过校验后，步骤才进入 `StepExecutionGraph`。工具调用仍必须经过 `ToolGateway`，不会因为已经投影成步骤而绕过 timeout、retry、rate limit、HITL、幂等和审计。

## 结构化结果通道

步骤之间不靠自然语言传递关键参数，而是写入 `step_execution.results`：

- 删除流程中，`resolve` 选择真实候选后写入 `note_id`，后续 `delete_note` 动态注入该 ID。
- 固化流程中，`compose` 生成草稿后写入 draft text，后续 `capture_text` 动态注入正文。
- ReAct 步骤完成后，把结构化观察结果写入当前 step result。

这条通道避免模型在投影阶段臆造对象 ID，也让 replay、history 和审计能看见关键中间结果。

## HITL 与恢复

高风险 `tool_call` 会写入 `pending_confirmation` 并通过 LangGraph interrupt 暂停。用户确认后，系统从同一 checkpoint 恢复；用户拒绝后，当前步骤标记为 skipped，依赖它的后续步骤也会被跳过。

确认状态属于短期执行现场，不是长期业务事实。长期知识仍由 Postgres note/chunk/review/graph mapping 表承载。

## 输出与观测

对外统一使用 step 语义：

- API response: `steps`
- SSE: `steps_projected`、`steps_validated`、`step_started`、`step_completed`、`step_failed`
- Run snapshot: `steps`、`step_execution` 摘要、`pending_confirmation`
- Checkpoint export: `checkpoint_schema_version`、`step_execution`

Model / Layer 图已移到 [Workflow / Step Projection Model / Layer 依赖类图](../mermaid/workflow-step-projection-model-layer-dependencies.md)。

## 与 Dynamic Planning 的关系

Step projection 已落地，且默认启用在固定 workflow 上。Dynamic planning 是未来能力，只有在没有固定 workflow、风险低、工具 allowlist 明确、配置显式开启且有专项 eval 的情况下才可能启用。

二者共享 `ExecutionStep` 和 `StepExecutionGraph`，但步骤来源不同：

| 来源 | 生成方式 | 当前状态 |
| --- | --- | --- |
| Workflow step projection | `WorkflowSpec` 确定性投影 | 已落地 |
| Dynamic planning | 模型生成 `DynamicPlan`，再经 validator 转换 | 未默认启用 |

推荐表述：当前项目不是让 LLM 自由生成全局流程，而是把固定 workflow 投影成可恢复、可校验、可审计的步骤；LLM 只参与 query understanding、候选解析、草稿生成、证据重排和低风险单步 ReAct。

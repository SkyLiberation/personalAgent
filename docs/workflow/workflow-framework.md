# 当前 Workflow 框架总览

本文总结当前工程的 workflow 框架：哪些对象是流程真源，哪些流程会进入 LangGraph step execution，以及一次请求如何从入口路由到具体业务链路。

对应核心代码：

- `src/personal_agent/agent/workflow.py`
- `src/personal_agent/agent/workflow_planner.py`
- `src/personal_agent/agent/execution_models.py`
- `src/personal_agent/agent/workflow_validator.py`
- `src/personal_agent/agent/step_projection_validator.py`
- `src/personal_agent/agent/orchestration_graph.py`
- `src/personal_agent/agent/orchestration_nodes/_entry.py`
- `src/personal_agent/agent/orchestration_nodes/_steps.py`
- `src/personal_agent/agent/orchestration_nodes/_react.py`
- `src/personal_agent/agent/orchestration_models.py`

## 一句话结论

当前项目采用 workflow-first 架构。`WorkflowSpec / WorkflowRegistry` 是固定业务流程的声明式真源；`WorkflowStepProjector` 只做确定性投影，不让 LLM 临场生成全局计划；LangGraph 负责把入口路由、step projection workflow、ReAct、ToolGateway、HITL 和 checkpoint 串成可恢复的执行图。

## 分层结构

```text
EntryInput
  -> EntryGraph
       normalize_entry
       route_intent
       optional clarify interrupt/resume
  -> Parent Orchestration Graph
       step_execution_graph
       or fallback branch
  -> finalize_entry_result
```

其中 `step_execution_graph` 的结构是：

```text
project_workflow_steps
  -> validate_projected_steps
  -> prepare_step_execution
  -> select_next_step
  -> execute_step
       -> react_graph?
       -> step_tool_node?
       -> confirm_step?
  -> consume_step_tool_result?
  -> handle_step_success / handle_step_failure
  -> finalize_step_execution
```

`react_graph` 是嵌入某个 step 内部的受控探索子图：

```text
react_init
  -> react_iterate
  -> react_tool_node
  -> consume_react_tool_result
  -> react_finalize
```

## 核心对象

| 对象 | 位置 | 职责 |
| --- | --- | --- |
| `WorkflowSpec` | `workflow.py` | 一个业务 workflow 的声明式契约，包含步骤、投影策略、HITL 策略、恢复策略 |
| `WorkflowStepSpec` | `workflow.py` | workflow 内部节点契约，声明 action、依赖、工具、副作用、风险、失败策略 |
| `WorkflowRegistry` | `workflow.py` | 按 intent 选择固定 workflow，并在需要时投影步骤 |
| `PostgresWorkflowDefinitionStore` | `storage/postgres_workflow_definition_store.py` | 持久化 versioned workflow definitions、deployment pin 和 eval gate |
| `ExecutionStep` | `execution_models.py` | workflow step 的运行时编译结果 |
| `WorkflowPlanner` | `workflow_planner.py` | 将有序 Goals 与 active WorkflowSpec 编译为 ExecutionPlan，不调用 LLM 生成拓扑 |
| `WorkflowSpecValidator` | `workflow_validator.py` | 校验 workflow 声明本身是否自洽 |
| `StepProjectionValidator` | `step_projection_validator.py` | 校验运行时 step 是否可执行、安全、符合 intent 规则 |
| `StepRunState` | `orchestration_models.py` | checkpoint-safe 的单步骤运行态 |
| `StepExecutionState` | `orchestration_models.py` | checkpoint-safe 的步骤执行状态，包含 steps、current index、results |
| `ReactSubState` | `orchestration_models.py` | ReAct 子图的私有状态，包含 iterations、allowed_tools、pending tool、result |
| `WorkflowExecutionProjection` | `workflow_event_projection.py` | 从 append-only `workflow_events` 重建执行读模型 |
| `WorkflowStateMigration` | `workflow_state_migration.py` | workflow 版本间 step 状态映射和 step/dependent reset |
| `GraphContexts` | `orchestration_contexts.py` | Graph Builder 的装配边界，聚合各阶段窄 Context |
| `RoutingContext` | `orchestration_contexts.py` | 只向入口路由节点暴露会话绑定、上下文压缩和 Router |
| `PlanningContext` | `orchestration_contexts.py` | 只向 workflow 编译节点暴露 Planner 与 Validator |
| `DirectAnswerContext` | `orchestration_contexts.py` | 仅供 unknown fallback 与 direct-answer compose 使用 |
| `SummaryContext` | `orchestration_contexts.py` | summarize compose 所需消息加载与总结能力 |
| `StepExecutionContext` | `orchestration_contexts.py` | step 执行、恢复、ask/summary context 与 artifact 能力 |
| `ReactContext` | `orchestration_contexts.py` | ReAct 所需工具、策略和模型配置 |

Context 由 `AgentRuntime` 在启动时显式构造。节点不接收 Runtime，也不通过 `from_runtime()` 动态
抽取依赖；因此新增能力必须先选择明确的阶段边界，而不能继续追加到全局依赖袋。

## Workflow 类型

当前 workflow 以 step projection 为主，`unknown` 和校验失败场景才会落到 fallback branch。

| 类型 | 是否生成 `ExecutionStep` | 是否进入 `StepExecutionGraph` | 典型 intent |
| --- | --- | --- | --- |
| Step projection workflow | 是 | 是 | `capture_*`、`ask`、`summarize_thread`、`delete_knowledge`、`solidify_conversation`、`direct_answer` |
| Fallback branch | 否 | 否 | `unknown`、step projection 校验失败后的澄清/兜底 |

## 当前已注册 Workflow

| Intent | Workflow ID | 当前执行方式 | 主要步骤 |
| --- | --- | --- | --- |
| `capture_text` | `capture_text` | step projection | `cap-structure` |
| `capture_link` | `capture_link` | step projection | `cap-link-fetch -> cap-link-store` |
| `capture_file` | `capture_file` | step projection | `cap-file-read -> cap-file-store` |
| `ask` | `ask` | step projection | `ask-retrieve -> ask-compose -> ask-verify` |
| `summarize_thread` | `summarize_thread` | step projection | `sum-compose` |
| `delete_knowledge` | `delete_knowledge` | step projection | `del-1 -> del-2 -> del-3 -> del-4` |
| `solidify_conversation` | `solidify_conversation` | step projection | `sol-1 -> sol-2` |
| `direct_answer` | `direct_answer` | step projection | `direct-compose` |
| `unknown` | `unknown` | fallback branch | 澄清或兜底回复 |

## Capture / Summarize / Direct Step Workflow

这些轻量流程也进入 `StepExecutionGraph`，但步骤数量少，UI 可以折叠展示。

### Capture

`capture_text / capture_link / capture_file` 由 `WorkflowRegistry` 投影为固定步骤。

```text
route_intent
  -> project_workflow_steps
  -> validate_projected_steps
  -> step_execution_graph
     -> capture_text:
          cap-structure tool_call(capture_text)
     -> capture_link:
          cap-link-fetch tool_call(capture_url)
          cap-link-store tool_call(capture_text)
     -> capture_file:
          cap-file-read tool_call(capture_upload)
          cap-file-store tool_call(capture_text)
  -> finalize_entry_result
```

入口文本、URL、上传文件元数据由 step executor 在 `tool_call` 前动态注入；`capture_url / capture_upload` 产出的正文会在 `handle_step_success` 注入到后续 `capture_text`。capture 的长期写入不绕过业务服务：真正的结构化、chunk、note、graph sync 等动作仍由 capture 服务和存储层负责。

### Summarize / Direct Answer

`summarize_thread` 投影为 `sum-compose`，会优先使用 entry metadata 或 thread messages，再调用 `summarize_chat`。`direct_answer` 投影为 `direct-compose`，用小模型直接回复低风险内容；`unknown` 仍走 fallback branch 转成面向用户的澄清提示。

## Ask Step Projection Workflow

`ask` 当前已经接入 workflow-step。Router 默认设置：

```text
requires_retrieval=True
Goal(intent="ask", input="...")
```

投影出的步骤：

```text
ask-retrieve
  -> ask-compose
  -> ask-verify
```

### ask-retrieve

`ask-retrieve` 执行真正耗时的检索和上下文组装：

```text
build AskRunContext
  -> QueryUnderstanding / RetrievalPlan
  -> multi-source recall
  -> evidence dedupe
  -> candidate enrich
  -> rerank
  -> ContextPack
  -> PostgresAskRunContextStore.put(run_id, ctx)
```

大对象如 evidence pool、ContextPack、matches 不直接放进 checkpoint，而是序列化到 `workflow_artifacts` 中的 ask context artifact；checkpoint 中只保留摘要计数和步骤状态，避免 checkpoint 膨胀。

### ask-compose

`ask-compose` 从 ask context artifact 取出上下文，基于 `ContextPack` 生成回答，并回填 citations / matches。

### ask-verify

`ask-verify` 做 verifier 校验、必要时 retry、必要时 web fallback。web fallback 不是复制一条新链路，而是追加 web evidence 后复用 context assembly、generation 和 verification。

## Delete Knowledge Workflow

`delete_knowledge` 是高风险 step projection workflow。

```text
del-1 retrieve/react
  -> del-2 resolve
  -> del-3 tool_call(delete_note) + HITL
  -> del-4 compose
```

关键点：

- `del-1` 使用 ReAct，但只允许只读 `graph_search`。
- `del-2` 从候选中解析真实 `note_id`，不在投影阶段臆造 ID。
- `del-3` 是高风险删除工具，必须先进入 HITL confirmation。
- 用户确认后从 LangGraph checkpoint resume；拒绝后该步骤和依赖步骤会被跳过或按失败策略处理。

## Solidify Conversation Workflow

`solidify_conversation` 用于把当前会话结论沉淀为长期知识。

```text
sol-1 compose
  -> sol-2 tool_call(capture_text)
```

关键点：

- `sol-1` 从 checkpoint 中的会话消息生成知识草稿。
- `sol-2` 复用 `capture_text` 工具写入长期知识。
- 它不是把“帮我保存一下”这句指令入库，而是从对话上下文中提取用户真正要固化的知识内容。

## Step Projection 的安全边界

Step projection 不是“生成了步骤就可以执行”。执行前必须通过 `StepProjectionValidator`：

- step id 唯一。
- 依赖可解析且无环。
- `action_type / risk_level / on_failure / execution_mode` 合法。
- 工具存在于 `ToolExecutor`。
- 工具输入满足 schema。
- 高风险工具必须要求确认。
- ReAct step 只能使用允许的低风险工具。
- intent-specific 规则必须满足，例如删除必须包含 `delete_note` 且要求确认，固化必须最终调用 `capture_text`。

通过校验后，工具调用仍统一走 ToolGateway。ToolGateway 继续负责 timeout、retry、权限、HITL、幂等、审计和工具结果归一化。

## ReAct 在 Workflow 中的位置

ReAct 不是全局 agent loop，而是某个 step 的执行模式：

```text
ExecutionStep.execution_mode == "react"
```

它的状态在 `ReactSubState` 中，包含：

- `iteration_index`
- `max_iterations`
- `allowed_tools`
- `iterations`
- `pending_tool`
- `pending_input`
- `status`
- `stop_reason`
- `result`

ReAct 每轮都会写 `react_iteration` 事件。工具调用也会写 `tool_called / tool_result`，最终结果写回 `step_execution.results[step_id]`，再回到普通 step success/failure 链路。

## 状态与结果传递

workflow 内部关键结果通过 `step_execution.results` 传递，而不是靠自然语言拼接。

例子：

- `delete_knowledge`：`del-2` 解析出 `note_id` 后，后续 `delete_note` 动态注入目标 ID。
- `solidify_conversation`：`sol-1` 生成 draft 后，后续 `capture_text` 动态注入正文。
- `ask`：`ask-retrieve` 把大对象放入 durable ask context artifact，`ask-compose / ask-verify` 通过 `run_id` 读取并在生成/校验后回写。
- `react`：完成后把结构化 result 写入当前 step result。

这样做的目标是让流程可恢复、可审计，并避免模型在计划阶段编造运行时对象。

## 观测与输出

当前 workflow 框架对外通过以下方式暴露执行状态：

- `AgentEvent`：`steps_projected`、`steps_validated`、`step_started`、`react_iteration`、`tool_called`、`tool_result`、`confirmation_required`、`step_completed`、`step_failed`、`answer_completed`。
- API / SSE：返回最终 answer、steps、pending confirmation、citations、matches、execution trace。
- Run snapshot：查询某个 run 的状态、步骤、错误、待确认 payload。
- Checkpoint export：调试某个 thread 的状态时间线。
- Workflow event log：`workflow_events` 按 `event_id` 去重持久化 `AgentEvent`，用于跨 checkpoint 的问题定位和后续 replay/fork 基础。
- Workflow definition/deployment：`workflow_definitions` 保存 `WorkflowSpec` payload，`workflow_deployments` pin stable/canary/disabled 版本，projector 会优先按 active deployment 投影。
- Eval gate：`workflow_eval_runs` 保存评测结果，`workflow_eval_policies` 定义多 suite/score/metric 阈值；`set_deployment()` 默认要求目标版本通过完整 policy。
- Replay/fork/debug：`workflow_replay_runs` 记录 checkpoint replay/fork；支持 checkpoint fork 和带 `checkpoint_ns` 的 step-level fork；debug bundle 聚合 event log、event-sourced projection、artifact、checkpoint history 和 replay 记录。
- State migration：`workflow_state_migrations` 保存版本间 step mapping，可预览把旧版本已完成步骤迁移到新 definition 的结果。
- Artifact lifecycle：artifact 支持 retention 到期时间、批量 purge 和显式递归 redaction。
- Worker queue：`worker_queue_tasks` 持久化后台任务；`WorkflowWorker / personal-agent worker` 提供常驻消费，支持 heartbeat、per-user concurrency、dead retry。

当前关系是：

```text
AgentGraphState.events
  -> API / SSE public projection
  -> workflow_events durable event log
  -> WorkflowExecutionProjection rebuild
  -> workflow_replay_runs replay/fork metadata
```

`workflow_events` 目前仍由 `AgentEvent` 派生；未来平台化后，应反转为 `WorkflowEvent` 是内部真源，`AgentEvent` 是对外投影。

后台任务当前关系是：

```text
capture chunk graph_sync=pending
  -> worker_queue_tasks(queue="graph", task_type="graph_sync_note")
  -> drain_worker_queue()
  -> sync_note_to_graph()
  -> worker task completed / dead
```

## Model / Layer 图

Workflow / Step Projection 的 Model / Layer 依赖类图见 [Workflow / Step Projection Model / Layer 依赖类图](../mermaid/workflow-step-projection-model-layer-dependencies.md)。

## 和 Dynamic Planning 的区别

步骤来源（workflow 投影 vs dynamic planning）的对照表见 [Dynamic Planning](../topics/dynamic-planning.md)。

当前生产主路径不是开放式 dynamic planning。固定业务流程由 `WorkflowSpec` 声明，启动时同步到 `workflow_definitions`，deployment pin 决定 active version，`WorkflowPlanner` 再确定性编译。LLM 参与的是局部语义任务，例如：

- router intent 分类；
- query understanding；
- ask answer compose；
- verifier retry；
- delete target resolve；
- solidify draft；
- ReAct 单步工具选择。

换句话说，LLM 可以参与“节点内部判断”，但不默认拥有“重新发明整条业务流程”的权力。

## 面试表述

可以这样总结：

> 我们的 workflow 框架是 workflow-first + LangGraph orchestration。Router 只输出有序 Goal；固定业务流程由 `WorkflowSpec / WorkflowRegistry` 维护，再由 `WorkflowPlanner` 生成任务依赖并确定性编译成 `ExecutionPlan / ExecutionStep`，进入 LangGraph step execution graph。工具、风险和确认策略以 WorkflowSpec 与 Tool Governance 为真源。

Phase5/6 后可以补充一句：

> 现在 workflow definition 会同步到 Postgres，并通过稳定 canary 分流选择 active version，execution checkpoint 会 pin 实际版本；deployment 默认受多 suite eval policy 约束。运行中的事件即时进入 `workflow_events` 并可重建 execution projection；每个 step 的 input/output/error 进入支持 retention/redaction 的 `workflow_artifacts`；checkpoint replay 和 step-level fork 会写 `workflow_replay_runs`。debug bundle 因此可以同时看到事件、重建状态、artifact、checkpoint history 和 fork 记录。

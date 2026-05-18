# LangGraph 总编排与 Checkpoint 接入计划

本文说明为什么需要把当前 entry 主流程进一步接入 LangGraph 总图，并给出分阶段实现方案。目标不是替换现有 router、planner、validator、tools、memory 和 Graphiti 能力，而是把它们提升为统一图节点，借助 LangGraph checkpoint / interrupt 能力实现整体流程可中断、可恢复、可追踪。

相关现状代码主要位于：

- [agent/runtime_entry.py](../../src/personal_agent/agent/runtime_entry.py)
- [agent/runtime.py](../../src/personal_agent/agent/runtime.py)
- [agent/graph.py](../../src/personal_agent/agent/graph.py)
- [agent/plan_executor.py](../../src/personal_agent/agent/plan_executor.py)
- [agent/react_runner.py](../../src/personal_agent/agent/react_runner.py)
- [storage/pending_action_store.py](../../src/personal_agent/storage/pending_action_store.py)

## 背景

当前项目已经使用 LangGraph，但它主要承担局部固定流程编排：

- `build_entry_graph()`：根据 intent 路由到 capture / ask / summarize / direct_answer / unknown。
- `build_capture_graph()`：采集、增强、关联、复习调度。
- `build_ask_graph()`：本地问答。

真正的 entry 主流程仍由 `RuntimeEntryMixin.execute_entry()` 和 `PlanExecutor.execute()` 手写驱动：

```text
execute_entry()
  -> plan_for_entry()
     -> DefaultIntentRouter
     -> optional DefaultTaskPlanner
     -> PlanValidator
  -> requires_planning?
     -> PlanExecutor
        -> retrieve / resolve / tool_call / compose / verify
        -> optional ReActStepRunner
        -> optional Replanner
     -> LangGraph entry branch
  -> EntryResult
```

这套结构已经能跑通功能，但长任务恢复、高风险审批、ReAct 轮次追踪和跨入口一致事件模型仍主要靠应用层代码维护。

## 目标

LangGraph 总编排接入后的目标：

- 用一张 entry 总图统一承载 router、planner、validator、plan execution、ReAct、HITL、finalize。
- 用 checkpoint 保存每个节点后的 `AgentGraphState`。
- 用 interrupt/resume 表达删除确认、固化确认等人工介入点。
- 让 SSE、API、CLI、飞书共享同一套 `AgentEvent` 语义。
- 让 plan step、react iteration、tool result、evidence、pending confirmation 和 final answer 都可以从图状态追踪。
- 保留现有业务组件，逐步迁移，不一次性重写所有执行逻辑。

## 非目标

第一阶段不追求：

- 完全删除 `AgentRuntime`。
- 一次性替换所有 capture / ask / graph sync 内部实现。
- 把所有工具都改成 LangGraph ToolNode。
- 把现有 pending action 数据立即废弃。
- 为每个 token delta 做 checkpoint。

`AgentRuntime` 在迁移期仍作为依赖容器和兼容 facade，现有函数逐步变成图节点内部调用。

## 目标图结构

建议新增一张 entry 总图，例如 `build_entry_orchestration_graph()`：

```text
START
  -> normalize_entry
  -> route_intent
  -> should_plan?
     -> plan_task
     -> validate_plan
     -> execute_next_step
        -> should_use_react?
           -> react_thought
           -> react_tool
           -> react_observe
           -> react_continue?
        -> deterministic_step
        -> need_confirmation?
           -> interrupt_for_confirmation
        -> step_completed
        -> more_steps?
           -> execute_next_step
           -> finalize_plan
     -> fixed_entry_branch
        -> capture_branch
        -> ask_branch
        -> summarize_branch
        -> direct_answer_branch
        -> unknown_branch
  -> finalize_response
  -> END
```

迁移过程中可以先把 `PlanExecutor.execute()` 包成单个节点，随后再把 step 执行拆细。这样可以先获得入口级 checkpoint，再逐步获得 step 级 checkpoint。

## 统一图状态

建议新增 `AgentGraphState`，不要直接复用当前所有运行时对象。它应该只保存可序列化、可恢复的运行现场。

建议字段：

```text
run_id
thread_id
user_id
session_id
entry_input
router_decision
intent
execution_path
plan_steps
current_step_id
step_results
react_iterations
tool_results
evidence
citations
matches
pending_confirmation
draft
answer
events
errors
replan_history
created_at
updated_at
```

设计原则：

- `AgentGraphState` 保存“流程现场”。
- `LocalMemoryStore / AskHistoryStore / PendingActionStore / CrossSessionStore` 保存“业务事实”。
- 图状态中保存业务对象的快照和引用，避免 checkpoint 与业务 store 各自成为事实源。

## Checkpoint 策略

### thread_id

建议 checkpoint config 使用稳定 thread id：

```text
thread_id = user_id + ":" + session_id + ":" + run_id
```

其中：

- `user_id` 用于隔离用户。
- `session_id` 用于对话上下文。
- `run_id` 用于区分同一会话中的一次 entry 执行。

如果未来需要“继续上一次未完成 entry”，可在 `CrossSessionStore` 或专门的 run store 中记录 `active_run_id`。

### checkpoint backend

分阶段选择：

1. 开发期：使用内存或本地 sqlite checkpointer，验证状态 schema 和 resume 语义。
2. 单机部署：使用 sqlite checkpointer，保证服务重启后可恢复。
3. 生产/多实例：使用 Postgres checkpointer，与 ask history / pending action 的持久化能力对齐。

### checkpoint 粒度

建议粒度：

- `route_intent` 后保存。
- `plan_task` 后保存。
- `validate_plan` 后保存。
- 每个 plan step 开始前和完成后保存。
- 每个 ReAct iteration 后保存。
- interrupt 前保存。
- resume 后保存。
- `finalize_response` 后保存。

不建议对流式回答的每个 token 都 checkpoint。流式 token 仍通过 SSE 发出，最终完整回答进入状态即可。

## HITL 中断与恢复

当前删除确认使用 `PendingActionStore` 做应用层两阶段确认。LangGraph 接入后建议采用桥接策略，而不是立即删除 pending action。

### 第一阶段：桥接 pending action

在图节点中遇到高风险动作时：

```text
need_confirmation
  -> 创建 PendingAction
  -> 写入 AgentGraphState.pending_confirmation
  -> interrupt(payload)
```

payload 包含：

```text
run_id
action_id
token
action_type
target_id
title
description
expires_at
resume_endpoint
```

前端仍展示 pending action 面板，但确认后不再只调用工具执行，而是调用 resume API。

### 第二阶段：resume 执行

新增或改造确认接口：

```text
POST /api/entry/runs/{run_id}/resume
```

输入：

```text
action_id
token
decision = confirm | reject
```

确认通过后：

```text
validate token
  -> update PendingAction status
  -> graph.resume(command)
  -> continue delete_tool_node
  -> finalize_response
```

拒绝时：

```text
update PendingAction rejected
  -> graph.resume(rejected)
  -> compose cancellation result
  -> finalize_response
```

## ReAct 迁移策略

当前 `ReActStepRunner` 是单个 Python runner，内部循环调用小模型和工具。可以分两阶段迁移。

### 阶段 A：runner 作为图节点

保留 `ReActStepRunner.run()`，将其作为 `execute_react_step` 节点调用。图状态记录最终 result 和压缩后的 iterations。

优点：

- 改动小。
- 保留已有安全边界。
- 先验证 checkpoint 主流程。

不足：

- ReAct 内部轮次不是图节点级 checkpoint。

### 阶段 B：ReAct 内循环图化

将 ReAct 拆为节点：

```text
react_prepare
  -> react_llm
  -> react_parse
  -> react_tool_guard
  -> react_tool_call
  -> react_observe
  -> react_should_continue
```

每轮 observation 写入 `react_iterations`，并自动 checkpoint。

保留现有治理规则：

- 默认只读工具。
- 阻断高风险工具。
- 阻断写长期知识工具。
- 阻断需要确认的工具。
- 限制最大轮数。

## 事件模型

LangGraph 总图接入应与统一 `AgentEvent` 工作并行推进。图节点不直接拼 SSE 文本，而是产出结构化事件：

```text
AgentEvent
  event_id
  run_id
  thread_id
  type
  timestamp
  payload
```

关键事件类型：

```text
entry_started
intent_classified
plan_created
plan_validated
step_started
react_iteration
tool_called
tool_result
confirmation_required
confirmation_resumed
draft_ready
answer_delta
answer_completed
step_completed
step_failed
replan_attempted
replan_completed
run_completed
run_failed
```

Web SSE、CLI 和飞书入口都从 `AgentEvent` 转换自己的输出格式。

## 分阶段实施计划

### 阶段 0：状态与事件准备

目标：先把状态和事件模型定下来，不改变执行路径。

任务：

- 新增 `AgentGraphState` 数据模型。
- 新增 `AgentRunStatus`、`AgentRunSnapshot` 等查询模型。
- 新增 `AgentEvent` 类型。
- 给现有 `EntryResult.plan_steps / execution_trace` 建立到 `AgentEvent` 的转换函数。
- 增加 run_id 生成和透传。

验收：

- 现有 `/api/entry` 和 `/api/entry/stream` 行为不变。
- 单测覆盖状态序列化、事件转换、run_id/thread_id 生成。

### 阶段 1：入口总图外壳

目标：让 entry 主流程先进入 LangGraph 总图，但节点内部复用现有函数。

任务：

- 新增 `agent/orchestration_graph.py`。
- 节点包括 `normalize_entry`、`route_intent`、`plan_or_trace`、`execute_existing_path`、`finalize_response`。
- `execute_existing_path` 内部暂时调用现有 `PlanExecutor` 或 `build_entry_graph()`。
- 接入 checkpointer。
- `AgentRuntime.execute_entry()` 改为调用总图，保留旧方法作为 fallback。

验收：

- 普通 ask/capture/direct 和 delete/solidify 结果与现有路径一致。
- 能按 run_id 查询 checkpoint snapshot。
- 服务重启后，已完成 run 的最终状态可读取。

### 阶段 2：PlanExecutor 拆成图节点

目标：把计划执行从单个 Python 循环拆成可 checkpoint 的图状态机。

任务：

- 用图节点表达 `select_next_step`、`execute_step`、`mark_step_completed`、`handle_step_failure`。
- 每个 step 前后写 checkpoint。
- step result 写入 `AgentGraphState.step_results`。
- 将 retry/replan 逻辑变成显式节点。
- 将 `PlanValidator` 复用于初始 plan 和 revised plan。

验收：

- 执行到任意 step 后可以恢复。
- step 失败后 resume 不会重复执行已完成的副作用步骤。
- revised steps 经过统一校验。

### 阶段 3：HITL interrupt 接入

目标：删除确认和后续高风险操作用 LangGraph interrupt/resume 表达。

任务：

- 新增 `confirmation_required` 节点。
- 在高风险 tool_call 前创建 `PendingAction` 并 interrupt。
- 新增 resume API。
- 确认/拒绝后恢复同一个 graph run。
- 对 pending action store 增加 `run_id/thread_id/checkpoint_id` 字段。

验收：

- 删除请求可以停在确认点。
- 服务重启后仍可确认并继续原 run。
- 拒绝后图能生成明确取消结果。
- 过期 pending action resume 会失败并写入审计。

### 阶段 4：ReAct 内循环图化

目标：让 ReAct 每轮 thought/action/observation 都可追踪和恢复。

任务：

- 将 `ReActStepRunner` 拆成图节点或子图。
- 每轮输出 `react_iteration` 事件。
- 工具治理逻辑保留在统一 guard 节点。
- ReAct 子图结束后写入当前 plan step result。

验收：

- 中断后不会重复调用已经完成的工具轮次。
- 非法工具请求被 guard 节点阻断并写入事件。
- 达到最大轮数后可生成可解释的部分结果。

### 阶段 5：入口统一与旧路径收敛

目标：让 Web、CLI、飞书入口都走统一 graph run。

任务：

- `/api/entry`、`/api/entry/stream`、飞书消息处理、CLI entry 共用总图。
- 将 `execution_trace` 由 `AgentEvent` 派生。
- 将 `plan_steps` 由 `AgentGraphState.plan_steps` 派生。
- 旧 `PlanExecutor` 保留一段兼容期后收敛。

验收：

- 各入口同一 intent 的事件序列一致。
- 前端 timeline 可展示完整 run。
- README 和 topic 文档更新为图优先架构。

## 风险与防护

### 副作用重复执行

风险：resume 后重复执行 `delete_note`、`capture_text` 等写操作。

防护：

- 每个 tool_call step 增加 idempotency key：`run_id + step_id + tool_name`。
- tool result checkpoint 后，resume 时先检查 step 是否 completed。
- 写操作工具必须记录 tool result。

### 状态漂移

风险：checkpoint、pending action、local memory store 各自保存不同事实。

防护：

- checkpoint 保存流程状态和引用。
- 业务 store 保存最终事实。
- 所有恢复动作先校验业务 store 当前状态。

### 图状态过大

风险：matches、evidence、tool results 过大导致 checkpoint 膨胀。

防护：

- 大文本和文件只保存引用。
- evidence 保存摘要、id、source_ref。
- 对 Graphiti refs 和 web results 设置数量上限。

### 双轨迁移复杂

风险：旧 runtime 和新 graph 同时存在，行为分叉。

防护：

- 每阶段设置开关。
- 用回归测试对比旧路径和新路径输出。
- 先迁移只读/低风险路径，再迁移高风险路径。

## 测试计划

最低测试覆盖：

- `AgentGraphState` 可序列化/反序列化。
- ask/capture/direct 通过总图后结果与旧路径一致。
- delete 计划执行到确认点后产生 interrupt。
- resume confirm 后继续执行 delete tool。
- resume reject 后生成取消结果。
- 服务重启模拟后可从 checkpoint 读取 pending run。
- ReAct 非法工具被 guard 阻断。
- 已完成 tool_call 在 resume 后不会重复执行。
- revised steps 必须经过 `PlanValidator`。
- SSE 可以从 `AgentEvent` 稳定转换。

## 演进方向

- 将 LangGraph 总图作为 entry 唯一编排入口。
- 将 checkpoint backend 从开发期 sqlite 迁移到 Postgres。
- 将 pending action 与 graph interrupt 完成双向绑定。
- 将 ReAct 内循环图化，提供轮次级恢复和追踪。
- 将前端计划面板升级为 run timeline，展示 intent、plan、step、tool、confirmation、answer 全链路。

## 下一步实现方案：入口总图外壳

第一步建议选择“总图外壳”而不是直接拆掉 `PlanExecutor`。

### 1. 新增图状态

新增 `AgentGraphState`，先覆盖 entry 级字段：

```text
run_id
thread_id
user_id
session_id
entry_input
router_decision
execution_path
plan_steps
execution_trace
entry_result
events
errors
```

### 2. 新增 orchestration graph

新增 `agent/orchestration_graph.py`：

```text
build_entry_orchestration_graph(runtime, checkpointer=None)
```

初版节点：

```text
normalize_entry
route_and_plan
execute_current_runtime_path
finalize_entry_result
```

其中 `execute_current_runtime_path` 暂时复用现有 `PlanExecutor` 和 `build_entry_graph()`。

### 3. 接入 checkpointer

开发期先接 sqlite 或内存 checkpointer。配置项建议：

```text
PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_ENABLED=false
PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_BACKEND=sqlite
PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_PATH=./data/langgraph_checkpoints.sqlite
```

默认关闭，通过环境变量启用。

### 4. Runtime 开关

在 `AgentRuntime.execute_entry()` 中增加开关：

```text
if settings.langgraph_checkpoint_enabled:
    return self._entry_orchestration_graph.invoke(...)
return self._execute_entry_legacy(...)
```

为避免递归，迁移时可将当前 `execute_entry()` 主体提取为 `_execute_entry_legacy()`。

### 5. API 查询能力

新增只读接口：

```text
GET /api/entry/runs/{run_id}
```

返回当前 run snapshot、状态、最后事件和最终结果。

### 6. 验收测试

- 开关关闭时现有测试全绿。
- 开关开启时 `/api/entry` 可正常返回。
- ask/capture/direct/delete/solidify 至少各有一条总图路径测试。
- checkpoint 文件生成。
- run snapshot 可查询。

# LangGraph 总编排与 Checkpoint

本文说明当前工程中已经落地的 LangGraph entry 总编排与 checkpoint 能力。对应代码主要位于：

- [agent/orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)
- [agent/orchestration_nodes.py](../../src/personal_agent/agent/orchestration_nodes.py)
- [agent/orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py)
- [agent/runtime.py](../../src/personal_agent/agent/runtime.py)
- [agent/runtime_entry.py](../../src/personal_agent/agent/runtime_entry.py)
- [web/api.py](../../src/personal_agent/web/api.py)
- [core/config.py](../../src/personal_agent/core/config.py)
- [tests/test_orchestration.py](../../tests/test_orchestration.py)

## 设计目标

当前 LangGraph 改造的目标是为 `entry` 主流程提供统一的图编排外壳，并在图节点边界上获得 checkpoint 与 run snapshot 查询能力。

已落地能力：

- `entry` 默认进入 LangGraph orchestration graph。
- 图状态使用 `AgentGraphState` 表达，支持序列化和 checkpoint。
- 每次 entry 执行生成独立 `run_id`，同一用户会话复用稳定 `thread_id`。
- 同一 thread 的用户/助手对话通过 `messages` 通道和 `add_messages` reducer 持续累积，供后续路由与回答生成读取。
- checkpoint 使用 LangGraph checkpointer 保存图节点状态。
- API 可查询已执行 run 的 snapshot。

## 配置

相关配置位于 [core/config.py](../../src/personal_agent/core/config.py)。

```env
PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_BACKEND=sqlite
PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_PATH=./data/langgraph_checkpoints.sqlite
```

说明：

- `PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_BACKEND`：checkpoint backend。开发环境推荐 `sqlite`，以便跨进程调试和恢复。
- `PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_PATH`：sqlite backend 的数据库文件路径。

当前 `_build_checkpointer()` 支持：

- `memory`：使用 `MemorySaver`。
- `sqlite`：使用 `langgraph.checkpoint.sqlite.SqliteSaver` 持久化 checkpoint。

调试脚本：

- `uv run python scripts/draw_entry_graph.py`：生成 `scripts/assets/entry-orchestration.md`。
- `uv run python scripts/export_thread_checkpoints.py <thread_id>`：生成 `scripts/assets/checkpoints-<thread_id>.json`，包含该会话 thread 内多次 run 的完整应用 state 时间线，默认不输出 `channel_versions` 等 LangGraph 内部存储字段。
- `uv run python scripts/export_thread_checkpoints.py <thread_id> --raw`：仅在底层调试时导出原始 checkpoint tuple 与内部版本/写入信息，默认另存为 `*-raw.json`。
- `MemorySaver` 中已经生成的历史 checkpoint 不存在于数据库中，切换到 SQLite 后仅新执行的 run 可由独立脚本导出。

## 总体执行路径

`AgentRuntime.execute_entry()` 是统一入口。

```text
AgentRuntime.execute_entry()
  -> _get_orch_graph()
  -> build AgentGraphState
  -> graph.invoke(initial_state, {"configurable": {"thread_id": thread_id}})
  -> map AgentGraphState back to EntryResult
```

entry 会先进入 orchestration graph。图内部复用现有 router、planner、validator、tool registry、memory、capture、ask 和 summarize 能力；普通分支与计划步骤执行逻辑均由 orchestration nodes 推进。

## Orchestration Graph

图构建函数位于 [agent/orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)：

```text
build_entry_orchestration_graph(deps, checkpointer=None)
```

当前图结构：

```text
START
  -> normalize_entry
  -> route_intent
     -> prepare_clarify_entry
        -> interrupt_clarify_entry
           -> route_intent
           -> finalize_entry_result
     -> capture_branch
     -> ask_branch
     -> summarize_branch
     -> direct_answer_branch
     -> plan_task
        -> validate_plan
           -> prepare_plan_execution
           -> direct_answer_branch
  -> finalize_entry_result

prepare_plan_execution
     -> select_next_step
        -> execute_plan_step
           -> confirm_step
           -> react_step
           -> handle_step_success
           -> handle_step_failure
        -> finalize_plan_execution
  -> finalize_entry_result
  -> END
```

`route_and_plan` 复合节点已拆分为 4 个独立节点，每个节点边界都有 checkpoint 保护。

### 1. `normalize_entry`

节点函数：`_node_normalize_entry()`

职责：

- 补齐 `run_id`。
- 从 `entry_input` 中读取 `user_id`、`session_id`、`text`。
- 生成 `thread_id`。
- 写入 `entry_started` 事件。
- 把当前用户输入追加到 reducer 管理的 `messages` 会话历史中；不会清空已有对话。

`thread_id` 生成规则（同一 session 的多次 run 复用）：

```text
thread_id = user_id + ":" + session_id
```

`run_id` 仍保存在 `AgentGraphState` 中，用于区分和查询 thread 内的单次执行。

### 2. `route_intent`

节点函数：`_node_route_intent()`

职责：

- 执行 session bind 和 conversation summary refresh。
- 调用 `runtime._intent_router.classify(entry_input)` 完成意图分类。
- 将当前消息之前的 `messages` 对话历史作为上下文传入 router。
- 将包含 `requires_clarification`、`missing_information`、`clarification_prompt` 的 `RouterDecision` 写入 state。
- 写入 `intent_classified` 事件。

条件边 `_route_by_intent()`：如果 `requires_clarification=True` 则进入 `prepare_clarify_entry`；否则如果 `requires_planning=True` 则进入 `plan_task`，其余根据 intent 进入普通分支。

### 3. `prepare_clarify_entry` 与 `interrupt_clarify_entry`

节点函数：`_node_prepare_clarify()`、`_node_interrupt_clarify()`

职责：

- `prepare_clarify_entry` 读取 router 已判定缺失的信息，构造 `kind="clarification_required"` 的 payload，并将其写入 `pending_confirmation` 与事件列表。
- payload 的写入发生在 `interrupt()` 之前，因此 checkpoint 可以保存前端需要展示的澄清内容和缺失项。
- `interrupt_clarify_entry` 通过 `interrupt()` 暂停 run，并等待 resume API 传入补充文本。
- runtime 构造等待态响应时读取该 checkpoint 的 state values，因此 `EntryResult.events` 能保留暂停前的 `intent_classified` 与 `clarification_required` 事件。
- 用户补充后，更新 `entry_text` 与 `entry_input.text`、清空旧路由决策，再重新进入 `route_intent`。
- 用户取消或补充为空时，直接进入 `finalize_entry_result` 结束。

### 4. `plan_task`

节点函数：`_node_plan_task()`

职责：

- 调用 `runtime._planner.plan(intent, entry_text)` 生成计划步骤。
- 将步骤转换为 dict 并写入 `state.plan_steps`。
- 写入 `plan_created` 事件。

### 5. `validate_plan`

节点函数：`_node_validate_plan()`

职责：

- 从 state 重建 `RouterDecision` 和 `PlanStep` 列表。
- 调用 `runtime._plan_validator.validate(steps, decision)`。
- 处理校验结果：
  - 通过：保持 plan_steps 不变。
  - blocking 且有 `corrected_steps`：使用修正后的步骤。
  - blocking 且无 corrected steps：调用 `runtime._planner.fallback_plan()`。
  - fallback 仍 blocking：降级为 `unknown` intent，进入澄清提示路径。
  - non-blocking warning：保留 warning，继续执行。
- 写入 `plan_validated` 事件。

条件边 `_after_validate_plan()`：如果计划有效且 `requires_planning=True` 则进入 `prepare_plan_execution`，否则进入 `direct_answer_branch` 生成澄清提示。

### 6. 普通分支节点

普通非计划路径已经并入 entry 总图，不再维护单独的 entry 子图：

- `capture_branch`：处理 `capture_text / capture_link / capture_file`。
- `ask_branch`：调用 `execute_ask()`。
- `summarize_branch`：处理群聊/文本总结。
- `direct_answer_branch`：处理低风险直接回复；当 `intent=unknown` 时，根据 classify 结果生成让用户补充信息的澄清提示。
- `ask_branch` 与 `direct_answer_branch` 均读取 thread 内已累积的对话消息，避免后续追问脱离上下文。

### 7. 计划执行节点

计划驱动路径由图节点直接执行，不再把整个计划交给旧的单个 `PlanExecutor` 黑盒。

主要节点：

- `prepare_plan_execution`：对计划步骤做拓扑排序，初始化 step 执行状态。
- `select_next_step`：选择下一个 `planned` 步骤，并写入 `step_started` 事件。
- `execute_plan_step`：执行当前步骤；普通步骤走确定性分发，`execution_mode="react"` 的步骤转入 ReAct 子图，高风险确认步骤转入 `confirm_step`。
- `confirm_step`：处理 LangGraph interrupt/resume 后的确认或拒绝结果。
- `handle_step_success`：处理成功步骤的结果注入、状态推进和事件记录。
- `handle_step_failure`：处理失败、retry、replan 和依赖跳过。
- `finalize_plan_execution`：汇总计划执行结果，生成最终回答和 execution trace。

### 8. ReAct 子图

`react_step` 是一个 LangGraph 子图，用于 `execution_mode="react"` 的计划步骤。

当前子图结构：

```text
START
  -> react_init
  -> react_iterate
     -> continue?
        -> react_iterate
        -> react_finalize
  -> END
```

职责：

- `react_init`：读取当前 plan step，解析 allowed tools，初始化 ReAct prompt 和轮次状态。
- `react_iterate`：执行一轮 LLM thought / tool action / observation，并写入 `react_iteration` 事件。
- `react_finalize`：把 ReAct 结果写入 `step_results`，标记当前 step completed。

### 8. `finalize_entry_result`

节点函数：`_node_finalize_entry_result()`

职责：

- 如果 `errors` 非空，写入 `run_failed` 事件。
- 否则写入 `run_completed` 事件。
- 结束当前 graph run。

## 图状态模型

图状态定义在 [agent/orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py)。

### `AgentGraphState`

`AgentGraphState` 是 checkpoint-safe 的 Pydantic 模型，保存 entry orchestration run 的流程状态。

核心字段：

- `run_id`
- `thread_id`
- `user_id`
- `session_id`
- `entry_input`
- `entry_text`
- `messages`（通过 `add_messages` reducer 在同一 thread 跨 run 累积）
- `intent`
- `intent_reason`
- `router_decision`
- `requires_planning`
- `plan_steps`
- `current_step_index`
- `step_results`
- `react_iterations`
- `tool_results`
- `execution_trace`
- `evidence_summary`
- `citations`
- `matches`
- `pending_confirmation`
- `draft`
- `answer`
- `answer_completed`
- `events`
- `errors`
- `replan_history`
- `created_at`
- `updated_at`

其中，`messages` 是会话级持久状态；`router_decision`、`plan_steps`、`answer`、`events`、`pending_confirmation` 等是单次 run 的执行状态，新一轮开始时会重置，防止上一轮产物冒充当前轮结果。

辅助方法：

- `add_event()`：追加结构化事件，并刷新 `updated_at`。
- `update_step_status()`：更新 `plan_steps` 中指定 step 的状态。
- `to_run_snapshot()`：转换为只读查询模型 `AgentRunSnapshot`。

### `AgentEvent`

`AgentEvent` 表示图执行过程中的结构化事件。

字段：

- `event_id`
- `run_id`
- `thread_id`
- `type`
- `timestamp`
- `payload`

当前事件类型集合包括：

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

当前 orchestration graph 已实际写入：

- `entry_started`
- `intent_classified`
- `plan_created`
- `plan_validated`
- `step_started`
- `step_completed`
- `step_failed`
- `tool_called`
- `tool_result`
- `confirmation_required`
- `confirmation_resumed`
- `react_iteration`
- `answer_completed`
- `run_completed`
- `run_failed`

其余事件类型是统一事件模型中的已定义类型，当前节点按需写入。

### `AgentRunSnapshot`

`AgentRunSnapshot` 是 API 查询用只读模型。

字段：

- `run_id`
- `thread_id`
- `user_id`
- `session_id`
- `status`
- `intent`
- `entry_text`
- `plan_steps`
- `execution_trace`
- `answer`
- `last_event`
- `errors`
- `created_at`
- `updated_at`

`status` 由 `_infer_status()` 根据状态推断：

- `failed`：`errors` 非空。
- `completed`：`answer_completed=True`。
- `waiting_confirmation`：`pending_confirmation` 非空。
- `running`：intent 已识别。
- `pending`：默认状态。

## Runtime 集成

相关代码位于 [agent/runtime.py](../../src/personal_agent/agent/runtime.py)。

### `_get_orch_graph()`

懒加载 orchestration graph：

```text
_get_orch_graph()
  -> _build_checkpointer(settings)
  -> OrchestrationDeps.from_runtime(self)
  -> build_entry_orchestration_graph(deps, checkpointer=checkpointer)
  -> cache in self._orch_graph
```

图在首次调用 entry 时构建。

### `execute_entry()`

当前逻辑：

```text
graph = self._get_orch_graph()
initial_state = AgentGraphState(...)
invoke_result = graph.invoke(initial_state, config)
if invoke_result["__interrupt__"]:
    return waiting_confirmation EntryResult
result_state = AgentGraphState.model_validate(invoke_result)
return EntryResult(...)
```

为了兼容现有 API，最终仍映射回 `EntryResult`。

### `get_run_snapshot()`

通过 checkpointer 查询指定 `run_id` 的 checkpoint，并转换为 `AgentRunSnapshot`。

匹配规则：

```text
state.run_id == requested_run_id
```

### `list_run_snapshots()`

从 checkpointer 中列出最近 checkpoint，并按 `run_id` 去重、按 `user_id` 可选过滤，返回 `AgentRunSnapshot` 列表。同一 `thread_id` 下的多个 run 会分别返回。

## HITL 中断与恢复流程

当前 HITL 主要在计划执行路径中处理高风险工具确认，核心节点是 `confirm_step`。

### 触发确认

计划步骤进入 `execute_plan_step` 后，如果工具返回 `pending_confirmation`，节点会：

- 写入 `state.pending_confirmation`。
- 将当前 plan step 状态标记为 `awaiting_confirmation`。
- 写入 `confirmation_required` 事件。

随后条件边 `_after_step_execution()` 根据当前步骤状态把流程路由到 `confirm_step`。

### 中断点

`confirm_step` 会根据 `state.pending_confirmation` 和当前 plan step 构造 `confirm_payload`，然后调用 LangGraph 的 `interrupt()`：

```text
resume_value = interrupt(confirm_payload)
```

第一次执行到这里时，graph run 会暂停。`graph.invoke()` 返回值中会包含：

```text
__interrupt__[0].value == confirm_payload
```

`AgentRuntime.execute_entry()` 从 `invoke_result["__interrupt__"]` 读取 payload，并转换为：

```text
EntryResult.pending_confirmation
EntryResult.run_status = waiting_confirmation
```

API / SSE 再把该确认信息交给前端。前端会在“需要你确认的操作”面板中展示这条 LangGraph run。

### 恢复执行

用户确认或拒绝后，后端使用原 run 的 `thread_id` 恢复 graph：

```text
graph.invoke(Command(resume=...), {"configurable": {"thread_id": thread_id}})
```

恢复后会重新进入同一个 `interrupt()` 调用位置。这次 `interrupt()` 不再暂停，而是返回外部传入的 resume value：

```text
{"decision": "confirm" | "reject", "user_id": "..."}
```

如果 decision 是 `confirm`：

- `confirm_step` 带上 `confirmed=True`、`action_id` 和 `token` 再次调用对应工具。
- 工具成功后写入 `state.step_results`。
- 当前步骤标记为 `completed`。
- 写入 `confirmation_resumed` 和 `step_completed` 事件。
- 后续进入 `handle_step_success`，再回到计划步骤循环。

如果 decision 是 `reject`：

- 当前步骤标记为 `skipped`。
- 依赖该步骤的后续步骤会被递归标记为 `skipped`。
- 写入 `confirmation_resumed` 和 `step_failed` 事件。
- 后续进入 `handle_step_failure`。

### checkpoint 的作用

HITL 流程依赖 checkpoint 保存以下现场：

- `thread_id`：恢复同一个 graph run。
- `current_step_index`：恢复到等待确认的计划步骤。
- `plan_steps`：保存每个步骤的状态。
- `pending_confirmation`：保存确认 payload。
- `step_results`：避免恢复后重复执行已完成步骤。
- `events`：保留确认前后的可观测事件。

因此，确认不是应用层临时返回，而是 graph run 的一个可 checkpoint、可 resume 的暂停点。

## 与现有流程的关系

当前 LangGraph 总图是 entry 主流程的默认编排器。普通 entry 分支仍复用既有 capture / ask / summarize / direct_answer 实现；计划驱动路径已经在图内拆成 step-level 状态机。

已复用的现有能力：

- `DefaultIntentRouter`
- `DefaultTaskPlanner`
- `PlanValidator`
- `execute_capture()`
- `execute_ask()`
- `AnswerVerifier`
- `ToolRegistry`
- `MemoryFacade`

因此，路由、规划、普通 entry 分支仍沿用已有业务行为；计划步骤、确认、ReAct 轮次和最终输出由 LangGraph 统一推进，并通过 graph state、checkpoint 和 run snapshot 查询。

## 当前边界

当前实现边界如下：

- checkpoint 粒度覆盖 orchestration graph 节点、计划步骤节点和 ReAct 子图节点。
- 普通 `capture / ask / summarize / direct_answer` 分支仍调用既有 runtime 方法。
- `GET /api/entry/stream` 的所有 intent（包含 `ask`）均进入 orchestration graph 并写入 checkpoint。
- 所有 entry 路径均已统一进入 orchestration graph 并写入 checkpoint。
- `EntryResult` 仍是 Web API 的兼容返回模型。

这些是当前已实现行为的边界，不在本文中作为待办展开。

## 测试覆盖

测试位于 [tests/test_orchestration.py](../../tests/test_orchestration.py)。

覆盖内容：

- `AgentGraphState` 默认值、序列化、事件追加、step 状态更新和 snapshot 转换。
- `AgentEvent` 序列化。
- `AgentRunSnapshot` 默认值。
- `run_id` 和 `thread_id` 生成。
- `plan_steps_to_plan_created_events()`。
- `execution_trace_to_events()`。
- orchestration graph 构建与 checkpointer 存在性。
- `direct_answer`、`ask`、`capture_text` 通过总图执行。
- HITL confirm/reject 路由、interrupt/resume 和 run 状态字段。
- ReAct helper、ReAct 单轮迭代、ReAct 子图和主图 ReAct 路由。
- `EntryResult.events` 透传、execution trace 从事件派生、事件到 SSE tuple 转换。
- run snapshot 列表和单个 snapshot 查询。

当前验证命令：

```bash
uv run pytest tests/test_orchestration.py
```

最近一次检查结果：

```text
67 passed
```

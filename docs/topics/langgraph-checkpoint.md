# LangGraph 总编排与 Checkpoint

本文说明当前工程中已落地的 LangGraph entry 总编排与 checkpoint 能力。对应代码主要位于：

- [agent/orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)
- [agent/orchestration_nodes/](../../src/personal_agent/agent/orchestration_nodes/)
- [agent/orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py)
- [agent/runtime.py](../../src/personal_agent/agent/runtime.py)
- [agent/runtime_entry.py](../../src/personal_agent/agent/runtime_entry.py)
- [web/api.py](../../src/personal_agent/web/api.py)
- [core/config.py](../../src/personal_agent/core/config.py)
- [tests/test_orchestration.py](../../tests/test_orchestration.py)

## 设计目标

- `entry` 默认进入 LangGraph orchestration graph，统一编排外壳
- 图状态使用 `AgentGraphState` 表达，支持序列化和 checkpoint
- 每次 entry 执行生成独立 `run_id`，同一用户会话复用稳定 `thread_id`
- 同一 thread 的对话通过 `messages` 通道（`add_messages` reducer）持续累积
- `tool_messages` 通道为覆盖式，只保存当前工具交换内容，不混入跨轮历史
- checkpoint 使用 LangGraph `PostgresSaver` 持久化图节点状态
- API 可查询已执行 run 的 snapshot

## 配置

相关配置位于 [core/config.py](../../src/personal_agent/core/config.py)。

```env
PERSONAL_AGENT_POSTGRES_URL=postgresql://postgres:postgres@127.0.0.1:5432/personal_agent?sslmode=disable
```

- `PERSONAL_AGENT_POSTGRES_URL` 同时承载业务数据和 checkpoint，是必填配置
- checkpoint 不提供内存或 SQLite fallback

`_build_checkpointer()`（位于 [orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)）使用 `langgraph.checkpoint.postgres.PostgresSaver`，首次连接通过 `setup()` 建立所需表结构。所有子图继承父图的同一个 Postgres saver。

调试脚本：

- `uv run python scripts/draw_entry_graph.py`：生成 `scripts/assets/entry-orchestration.md`（含父图、子图独立视图、xray 组合视图）
- `uv run python scripts/export_thread_checkpoints.py <thread_id>`：导出该 thread 内多次 run 的完整 state 时间线
- `uv run python scripts/export_thread_checkpoints.py <thread_id> --raw`：导出原始 checkpoint tuple（仅底层调试用）

## 图结构总览

入口图由 `build_entry_orchestration_graph()` 构建，包含 **一个父图 + 四个子图**，全部使用 `AgentGraphState` 作为统一状态类型。

### 父图：Entry Orchestration Graph

```
START → entry_graph → 路由分发 → 分支节点 → finalize_entry_result → END
```

父图有 5 个分支节点（均为普通节点，非子图）：

| 节点 | 职责 |
|---|---|
| `capture_branch` | 处理 `capture_text / capture_link / capture_file` |
| `ask_branch` | 调用 `execute_ask()` 执行知识问答 |
| `summarize_branch` | 处理群聊/文本总结 |
| `direct_answer_branch` | 低风险直接回复或澄清提示 |
| `finalize_entry_result` | 汇总结果、生成 `execution_trace`、结束 run |

路由由 `_route_by_intent()` 根据 `entry_graph` 产出的 `RouterDecision` 决定：

- `requires_clarification=True` 或 `answer_completed=True` → 直接进入 `finalize_entry_result`
- `requires_planning=True` → `plan_execution_graph`
- 其他按 intent 进入对应分支（capture / ask / summarize / direct_answer）

`plan_execution_graph` 退出后，若计划被拒绝且无回答，回退到 `direct_answer_branch`；否则进入 `finalize_entry_result`。

### 子图 1：EntryGraph

```
START → normalize_entry → route_intent → prepare_clarify_entry ⇄ interrupt_clarify_entry → END
```

**节点职责：**

- **`normalize_entry`**：补齐 `run_id`/`thread_id`，读取 `user_id`/`session_id`/`text`，追加用户输入到 `messages` 历史，写入 `entry_started` 事件
- **`route_intent`**：执行 session bind、conversation summary refresh，调用 `IntentRouter.classify()` 完成意图分类，写入 `RouterDecision` 到 state
- **`prepare_clarify_entry`**：读取 router 判定的缺失信息，构造 `clarification_required` payload 写入 `pending_confirmation`
- **`interrupt_clarify_entry`**：通过 `interrupt()` 暂停 run，等待 resume API 传入补充文本。用户补充后更新 `entry_text` 重新进入 `route_intent`；取消或补充为空则结束

`thread_id` 生成规则：`thread_id = user_id + ":" + session_id`，同一 session 多次 run 复用。

### 子图 2：PlanExecutionGraph

```
START → plan_task → validate_plan → prepare_plan_execution
       → select_next_step ⇄ execute_plan_step → [路由分发] → handle_step_success/handle_step_failure
       → finalize_plan_execution → END
```

**Phase 1 — 计划生成与校验：**

- **`plan_task`**：调用 Planner 生成 `plan_steps` 列表
- **`validate_plan`**：PlanValidator 校验；blocking 时尝试修正或 fallback，仍不通过则退回 `direct_answer_branch`
- **`prepare_plan_execution`**：拓扑排序步骤，初始化 `current_step_index`、`step_results`、`plan_retry_counts`

**Phase 2 — 步骤循环：**

- **`select_next_step`**：找第一个 `planned` 状态步骤，标记 `running`
- **`execute_plan_step`**：按 `action_type` 分发执行：

| action_type | 行为 |
|---|---|
| `tool_call` | 生成 `AIMessage(tool_calls=[...])`，由 `plan_tool_node` 执行 |
| `react` | 种子 ReAct 状态，路由到 `react_graph` 子图 |
| `retrieve` | 调用 `graph_store.ask()` 检索知识图谱 |
| `resolve` | 解析删除目标（图 episode 反查 → LLM 候选匹配） |
| `compose` | 调用 `execute_ask()` 生成回答；solidify 场景做 LLM 范围判断后知识提取 |
| `verify` | 调用 verifier 校验当前 `answer` |

`tool_call` 步骤具有幂等性保护：`step_results` 中已有结果的步骤自动跳过。

**Phase 3 — 结果路由（`_after_step_execution`）：**

| 步骤状态 | 路由目标 |
|---|---|
| `awaiting_confirmation` | `confirm_step`（HITL 中断） |
| `failed` | `handle_step_failure` |
| `react` + `running` | `react_graph` 子图 |
| `tool_call` + `running` | `plan_tool_node` |
| 其他 | `handle_step_success` |

**`handle_step_success`**：注入依赖关系（`resolve` 产出的 `note_id` 注入下游 `tool_call`；`compose` 产出的草稿注入下游 `capture_text`），标记上游草稿固化，回到 `select_next_step`

**`handle_step_failure`**：按 `on_failure` 策略处理：

| 策略 | 行为 |
|---|---|
| `retry`（未耗尽） | 等待 1s → 状态重置为 `planned` → 回到循环 |
| `retry`（已耗尽） | 调用 replanner 重新规划 → 验证新步骤 → 追加到步骤列表 |
| `skip` | 跳过当前及依赖步骤 → 回到循环 |
| `abort` | `plan_aborted=True` → `finalize_plan_execution` |

**HITL 确认（`confirm_step`）：**

1. 构建确认 payload（step_id、action_type、note_id 等）
2. 调用 `interrupt()` 暂停图执行，payload 通过 `__interrupt__` 返回给调用方
3. 用户通过 `Command(resume={"decision": "confirm"|"reject"})` 恢复：
   - confirm → 带上 `confirmed=True` 重新进入 `plan_tool_node` 执行实际操作
   - reject → 标记步骤 `skipped`，跳过依赖步骤

**`finalize_plan_execution`**：生成默认回答（如尚无），从 events 导出 `execution_trace`，标记 `answer_completed=True`

### 子图 3：ReactGraph

`execution_mode="react"` 的计划步骤进入独立的受限 ReAct 循环。ReactGraph 是 PlanExecutionGraph 的嵌套子图。

```
START → react_init → react_iterate ⇄ react_tool_node → consume_react_tool_result
                   → react_finalize → END
```

**节点职责：**

- **`react_init`**：读取当前 plan step，解析 allowed tools，构建初始 prompt（步骤描述 + 上下文 + 可用工具列表），初始化轮次状态
- **`react_iterate`**：执行一轮 LLM thought → parse JSON → 三种结果：
  - `done=true` → 进入 `react_finalize`
  - 解析出 tool → 生成 `AIMessage` 由 `react_tool_node` 执行 → `consume_react_tool_result` 记录 observation → 回到 `react_iterate`
  - 解析失败 → 记录错误，自循环重试（`iterate` → `react_iterate`）
- **`react_finalize`**：将结果写入 `step_results`，清理循环工作数据；`completed` 状态路由到 `handle_step_success`，`failed/exhausted` 路由到 `handle_step_failure`

**安全限制：** 只允许只读检索工具（`graph_search`/`web_search`），高风险写操作被 `_is_react_tool_blocked()` 阻断。默认最多 `_REACT_MAX_ITERATIONS_CAP`（3）轮迭代，达到上限后状态为 `exhausted`。

### Capture 分支

Capture 不再维护独立 LangGraph 子图。`execute_capture()` 直接调用 `run_capture_flow()` 执行确定性业务节点：采集归一 → 结构 chunk 草案 → LangExtract 预抽取 → chunk 调和 → 增强 → 关联 → 复习调度。entry orchestration 父图只负责路由到 `_node_capture_branch()`，不会为 capture 额外 compile 子图。

---

## 图状态模型

图状态定义在 [agent/orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py)。

### `AgentGraphState`

`AgentGraphState` 是 checkpoint-safe 的 Pydantic 模型，所有子图共用。核心字段按职责分组：

**会话级持久字段（跨 run 通过 reducer 累积）：**
- `messages`：通过 `add_messages` reducer 在同一 thread 跨 run 累积的对话历史

**单次 run 执行状态（新一轮重置）：**
- `run_id`、`thread_id`、`user_id`、`session_id`
- `entry_input`、`entry_text`
- `router_decision`（含 `route`、`requires_clarification`、`requires_planning`）
- `plan_steps`：`PlanStepState` 列表
- `current_step_index`、`step_results`、`plan_retry_counts`、`plan_aborted`
- `tool_messages`：当前工具动作的临时消息交换
- `active_tool_context`、`pending_tool_step_id`、`pending_tool_call_id`、`pending_react_iteration`
- `tool_results`、`react_iterations`、`react_status`、`react_stop_reason`
- `execution_trace`、`evidence_summary`、`citations`、`matches`
- `pending_confirmation`、`confirmation_decision`
- `answer`、`answer_completed`、`draft`
- `events`、`errors`、`replan_history`
- `created_at`、`updated_at`

辅助方法：`add_event()`、`update_step_status()`、`to_run_snapshot()`

### `AgentEvent`

结构化事件，字段：`event_id`、`run_id`、`thread_id`、`type`、`timestamp`、`payload`

当前 graph 实际写入的事件类型：
`entry_started`、`intent_classified`、`plan_created`、`plan_validated`、`step_started`、`step_completed`、`step_failed`、`tool_called`、`tool_result`、`confirmation_required`、`confirmation_resumed`、`react_iteration`、`draft_ready`、`answer_completed`、`run_completed`、`run_failed`

### `AgentRunSnapshot`

API 查询用只读模型。状态推断逻辑：

- `failed`：`errors` 非空
- `completed`：`answer_completed=True`
- `waiting_confirmation`：`pending_confirmation` 非空
- `running`：intent 已识别
- `pending`：默认状态

## Runtime 集成

相关代码位于 [agent/runtime.py](../../src/personal_agent/agent/runtime.py)。

### `_get_orch_graph()`

懒加载，首次 entry 时构建并缓存：

```text
_get_orch_graph()
  -> _build_checkpointer(settings)
  -> OrchestrationDeps.from_runtime(self)
  -> build_entry_orchestration_graph(deps, checkpointer=checkpointer)
  -> cache in self._orch_graph
```

### `execute_entry()`

```text
graph = self._get_orch_graph()
initial_state = AgentGraphState(...)
invoke_result = self._stream_entry_graph(graph, initial_state, config, on_progress)
if invoke_result["__interrupt__"]:
    return waiting_confirmation EntryResult
result_state = AgentGraphState.model_validate(invoke_result)
return EntryResult(...)
```

最终映射回 `EntryResult` 兼容现有 Web API。

### `get_run_snapshot()` / `list_run_snapshots()`

通过 checkpointer 查询指定 `run_id` 或列出最近 checkpoint，按 `run_id` 去重，按 `user_id` 可选过滤。同一 `thread_id` 下多个 run 分别返回。

## HITL 中断与恢复流程

HITL 在计划执行路径中处理高风险工具确认，核心在 `confirm_step`。

### 触发 → 中断 → 恢复

1. 工具返回 `pending_confirmation` → `execute_plan_step` 写入 `state.pending_confirmation`，步骤标记 `awaiting_confirmation`
2. 条件边路由到 `confirm_step`，调用 `interrupt(confirm_payload)` 暂停图
3. `__interrupt__[0].value` 返回给 API 层，转为 `EntryResult.pending_confirmation`（`run_status=waiting_confirmation`）
4. 用户确认/拒绝后，通过 `Command(resume={"decision": "confirm"|"reject"})` 恢复同一 `thread_id`
5. `interrupt()` 返回 resume value，`confirm_step` 处理决定：
   - **confirm**：带上 `confirmed=True` 重新执行工具 → `handle_step_success`
   - **reject**：标记步骤 `skipped`，递归跳过依赖步骤 → `handle_step_failure`

checkpoint 保存的现场：`thread_id`、`current_step_index`、`plan_steps`、`pending_confirmation`、`step_results`、`events`。确认不是应用层临时返回，而是 graph run 的可 checkpoint、可 resume 的暂停点。

## 测试覆盖

测试位于 [tests/test_orchestration.py](../../tests/test_orchestration.py)。

覆盖内容：

- `AgentGraphState` 默认值、序列化、事件追加、step 状态更新和 snapshot 转换
- `AgentEvent` 序列化、`AgentRunSnapshot` 默认值
- `run_id`/`thread_id` 生成
- orchestration graph 构建与 checkpointer 存在性
- `direct_answer`、`ask`、`capture_text` 通过总图执行
- HITL confirm/reject 路由、interrupt/resume 和 run 状态字段
- ReAct helper、单轮迭代、独立 ToolNode 返回消费、退出状态和子图路由
- `EntryResult.events` 透传、execution trace 派生、事件到 SSE tuple 转换
- run snapshot 列表和单个 snapshot 查询

```bash
uv run pytest tests/test_orchestration.py
```

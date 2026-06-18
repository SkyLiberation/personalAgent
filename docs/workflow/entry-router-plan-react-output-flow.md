# Entry / Checkpoint / 输出整体流程

本文说明一次 `entry` 请求如何从 Web / CLI / 飞书入口进入系统，经过 LangGraph 总编排、router、workflow projection、ReAct、HITL、工具、记忆、SSE / API 输出，并如何通过 Postgres checkpoint 支持跨 run 对话、暂停确认、恢复执行和 run snapshot 查询。

对应代码主要位于：

- [entry_orchestrator.py](../../src/personal_agent/agent/entry_orchestrator.py)
- [orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)
- [orchestration_nodes/](../../src/personal_agent/agent/orchestration_nodes/)
- [orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py)
- [workflow.py](../../src/personal_agent/agent/workflow.py)
- [step_projector.py](../../src/personal_agent/agent/step_projector.py)
- [step_projection_validator.py](../../src/personal_agent/agent/step_projection_validator.py)
- [router.py](../../src/personal_agent/agent/router.py)
- [web/api.py](../../src/personal_agent/web/api.py)

## 核心结论

当前后端以 `AgentRuntime` 为组合根，`EntryOrchestrator` 持有并缓存 LangGraph entry 总图。每次 `execute_entry()` 都生成新的 `run_id`，但同一 `user_id:session_id` 复用稳定 `thread_id`，因此同一 thread 的 `messages` 和 `thread_summary` 会通过 LangGraph checkpoint 延续，而单次 run 的 router、plan、tool、answer、events 等状态会在新入口初始化时重置。

```text
Web / Feishu / CLI
  -> AgentService.entry()
  -> AgentRuntime.entry()
  -> EntryOrchestrator.execute_entry()
  -> LangGraph Entry Orchestration Graph
     -> EntryGraph: normalize_entry -> route_intent -> optional clarification interrupt/resume
     -> step workflow: project_workflow_steps -> validate_projected_steps -> step loop -> ReAct / ToolGateway / HITL
        or fallback branch
     -> finalize_entry_result
  -> EntryResult / SSE / run snapshot
```

关键边界：

- Router 是所有 entry 的共同入口；除 `unknown` / fallback 外，业务 workflow 统一进入步骤投影。
- `WorkflowStepProjector` 从 `WorkflowRegistry` 确定性投影 `ExecutionStep`，不是 LLM planner。
- `capture / ask / summarize / delete_knowledge / solidify_conversation / direct_answer` 都是 step projection workflow，会生成真实 `steps`，进入 checkpoint-safe 的步骤执行。
- ReAct 只嵌在某个 step 内，用于受控检索探索，不是全局自主 agent loop。
- checkpoint 是短期执行现场和恢复机制，不是长期事实库；长期知识仍在 `knowledge_notes`。

## Checkpoint 配置与调试

`PERSONAL_AGENT_POSTGRES_URL` 同时承载业务数据和 LangGraph checkpoint：

```env
PERSONAL_AGENT_POSTGRES_URL=postgresql://postgres:postgres@127.0.0.1:5432/personal_agent?sslmode=disable
```

`_build_checkpointer()` 使用 `langgraph.checkpoint.postgres.PostgresSaver`，首次连接会调用 `setup()` 创建 checkpoint 表。当前不提供内存或 SQLite fallback；生产与测试都应显式提供 Postgres URL。

相关调试脚本：

- `uv run python scripts/draw_entry_graph.py`：生成 `docs/mermaid/entry-orchestration.md`，用于查看父图、子图和 xray 组合视图。
- `uv run python scripts/export_thread_checkpoints.py <thread_id>`：导出某个 thread 的 state 时间线。
- `uv run python scripts/export_thread_checkpoints.py <thread_id> --raw`：导出原始 checkpoint tuple，适合底层调试。

## 图结构

入口总图由 `build_entry_orchestration_graph()` 构建，使用一个统一状态模型 `AgentGraphState`。

```text
START
  -> entry_graph
  -> route by RouterDecision
     -> step_execution_graph
     -> direct_answer_branch fallback
  -> finalize_entry_result
  -> END
```

### EntryGraph

```text
START
  -> normalize_entry
  -> route_intent
  -> prepare_clarify_entry?
  -> interrupt_clarify_entry?
  -> END
```

- `normalize_entry`：补齐 `run_id/thread_id/user_id/session_id`，追加用户输入到 `messages`，写入 `entry_started`。
- `route_intent`：绑定 session，读取受限短期对话线索，调用 `DefaultIntentRouter.classify()`，写入 `RouterDecision`。
- `prepare_clarify_entry`：当 router 判断缺信息时，构造 `clarification_required` payload 写入 `pending_confirmation`。
- `interrupt_clarify_entry`：通过 `interrupt()` 暂停；resume 后用补充文本更新 `entry_text` 并重新路由，取消则结束。

`thread_id` 规则是：

```text
thread_id = f"{user_id}:{session_id}"
```

因此同一用户会话的多次 entry 会共享 checkpoint thread，而每次 entry 有独立 `run_id`。

### Fallback Branch

普通分支现在主要承担 `unknown`、clarification、step projection 校验失败后的兜底路径。业务 workflow 的常规路径都先进入 `StepExecutionGraph`。

### StepExecutionGraph

业务 workflow 会进入步骤执行图，执行由固定 `WorkflowSpec` 投影出的 steps：

```text
START
  -> project_workflow_steps
  -> validate_projected_steps
  -> prepare_step_execution
  -> select_next_step
  -> execute_step
     -> react_graph?
     -> step_tool_node?
     -> confirm_step?
  -> handle_step_success / handle_step_failure
  -> finalize_step_execution
  -> END
```

- `project_workflow_steps`：调用`WorkflowStepProjector`，从 `WORKFLOW_REGISTRY` 确定性投影 steps。
- `validate_projected_steps`：用 `StepProjectionValidator` 校验 action、依赖、工具、风险、确认要求和 intent-specific 规则。
- `prepare_step_execution`：拓扑排序，初始化 `StepExecutionState`。
- `select_next_step`：选择第一个 `planned` step，标记为 `running`。
- `execute_step`：按 `action_type` 分发。
- `handle_step_success`：注入动态依赖结果，例如把 resolve 得到的 `note_id` 注入 `delete_note`，把 solidify 草稿或 URL/file 提取正文注入 `capture_text`。
- `handle_step_failure`：按 `retry / skip / abort` 处理，可调用 `Replanner` 追加替代步骤。
- `finalize_step_execution`：生成默认回答、派生 `execution_trace`、标记 `answer_completed=True`。

`tool_call` 步骤不会在 `_dispatch_step()` 内直接执行，而是生成 tool-call message 交给 `ToolExecutor.graph_node()`。这样工具调用统一经过 ToolGateway 的权限、timeout、retry、HITL、幂等和审计边界。

### ReactGraph

`execution_mode="react"` 的 step 才进入 ReAct 子图：

```text
START
  -> react_init
  -> react_iterate
  -> react_tool_node
  -> consume_react_tool_result
  -> react_finalize
  -> END
```

约束：

- 默认只允许 `graph_search / web_search` 等只读检索工具。
- 高风险、写长期记忆、删除类、capture 类工具会被 `_is_react_tool_blocked()` 阻断。
- 迭代数受 step `max_iterations` 和全局 cap 共同限制。
- ReAct 结果写入 `state.step_execution.results[step_id]`，再回到普通 step success/failure 处理。

## 状态模型

`AgentGraphState` 是所有子图共用的 checkpoint-safe Pydantic 模型。它保存运行现场，不保存长期事实。

主要字段：

| 字段 | 生命周期 | 说明 |
| --- | --- | --- |
| `run_id` | 单次 run | 每次 entry 新建 |
| `thread_id` | 同一 user/session | LangGraph checkpoint key |
| `messages` | 跨 run 累积 | `add_messages` reducer 保存用户/助手对话 |
| `thread_summary` | 跨 run 更新 | 结构化短期摘要，只作对话线索 |
| `router_decision` | 单次 run | 当前 entry 的路由结果 |
| `plan` | 单次 run | `StepExecutionState`，含 steps、current index、step_results、aborted |
| `react` | 单个 ReAct step | `ReactSubState`，含 iterations、pending tool、status |
| `tool_tracking` | 当前工具交换 | ToolGateway pending call 上下文 |
| `tool_messages` | 当前工具交换 | 覆盖式通道，不累积到历史对话 |
| `tool_results` | 单次 run | 工具 artifact 摘要 |
| `pending_confirmation` | 暂停周期 | clarification 或高风险确认 payload |
| `answer / answer_completed` | 单次 run | 最终输出 |
| `events` | 单次 run | `AgentEvent` 结构化事件 |

`AgentEvent` 字段是：

```text
event_id / run_id / thread_id / type / timestamp / payload
```

常见事件包括：`entry_started`、`clarification_required`、`clarification_resumed`、`intent_classified`、`steps_projected`、`steps_validated`、`step_started`、`react_iteration`、`tool_called`、`tool_result`、`confirmation_required`、`confirmation_resumed`、`draft_ready`、`step_completed`、`step_failed`、`answer_completed`、`run_completed`、`run_failed`。

## Router

`DefaultIntentRouter` 输入 `EntryInput`，输出 `RouterDecision`。

关键字段：

- `route`
- `confidence`
- `requires_tools`
- `requires_retrieval`
- `requires_step_projection`（表示是否需要 step projection）
- `risk_level`
- `requires_confirmation`
- `requires_clarification`
- `missing_information`
- `clarification_prompt`
- `candidate_tools`
- `user_visible_message`

策略：

1. `source_type="file"` 直接进入 `capture_file`。
2. 文本请求优先调用小模型输出 JSON intent。
3. LLM 结果再与 `_default_router_decision()` 合并，补齐控制字段。
4. LLM 不可用或输出无效时返回明确不可用/未知结果，不用关键词静默猜测。

默认控制语义：

- `ask`：需要检索，候选工具是 `graph_search / web_search`。
- `capture_text / capture_link / capture_file`：需要 step projection，候选工具是 capture 系列工具。
- `summarize_thread`：需要 step projection，通过 compose step 加载会话消息并总结。
- `delete_knowledge`：需要工具、检索、step projection，高风险，需要确认。
- `solidify_conversation`：需要 step projection，低风险写入。
- `direct_answer`：需要 step projection，不检索、不调用工具。

## Workflow Step Projection

当前 `WorkflowStepProjector` 是确定性的 workflow step projector，不再让 LLM 生成拓扑。这里保留 `Planner` 类名只是历史兼容，不能理解成已经启用了通用 autonomous planner。

```text
WorkflowStepProjector.plan(intent)
  -> WORKFLOW_REGISTRY.select(intent)
  -> spec.project() if projection_policy == "step_projection"
  -> list[ExecutionStep]
```

当前以下 workflow 会投影成步骤：

| Workflow | Steps | 说明 |
| --- | --- | --- |
| `capture_text` | `tool_call(capture_text)` | 将入口文本写入长期知识 |
| `capture_link` | `tool_call(capture_url) -> tool_call(capture_text)` | 抓取 URL 正文后写入长期知识 |
| `capture_file` | `tool_call(capture_upload) -> tool_call(capture_text)` | 解析上传文件后写入长期知识 |
| `ask` | `retrieve -> compose -> verify` | 检索、生成、校验三段式 RAG |
| `summarize_thread` | `compose` | 加载 thread messages 并总结 |
| [`delete_knowledge`](delete-knowledge-workflow.md) | `retrieve -> resolve -> tool_call(delete_note) -> compose` | 高风险删除，必须候选解析 + HITL |
| [`solidify_conversation`](solidify-conversation-workflow.md) | `compose -> tool_call(capture_text)` | 从 checkpoint 对话生成草稿，再写入长期知识 |
| `direct_answer` | `compose` | 低风险直接回复 |

`ExecutionStep` 是 runtime projection，关键字段包括：

- `step_id`
- `action_type`
- `description`
- `tool_name`
- `tool_input`
- `depends_on`
- `expected_output`
- `success_criteria`
- `risk_level`
- `requires_confirmation`
- `on_failure`
- `execution_mode`
- `allowed_tools`
- `max_iterations`
- `workflow_id / workflow_version / workflow_step_id / projection_kind`

## HITL 中断与恢复

当前有两类 interrupt：

1. Clarification：router 判断缺信息，`interrupt_clarify_entry` 暂停等待用户补充。
2. Confirmation：高风险工具确认，`confirm_step` 暂停等待用户确认或拒绝。

确认流程：

```text
delete_note first call
  -> artifact.data.pending_confirmation=True
  -> state.pending_confirmation
  -> confirmation_required event
  -> confirm_step interrupt(payload)
  -> API returns run_status=waiting_confirmation
  -> POST /api/entry/runs/{run_id}/resume
  -> graph.invoke(Command(resume={decision,...}), same thread_id)
  -> confirm: re-dispatch tool with confirmed=True
     reject: mark step skipped and skip dependents
```

checkpoint 保存的是完整 graph 现场：`thread_id`、`run_id`、`step_execution.steps`、`current_step_index`、`step_execution.results`、`pending_confirmation`、`events`、`tool_tracking` 等。确认不是 Web 层临时状态，而是 LangGraph run 的可恢复暂停点。

## 输出层

`EntryOrchestrator.execute_entry()` 将最终 `AgentGraphState` 映射回 `EntryResult`：

- `intent`
- `reason`
- `reply_text`
- `capture_result`
- `ask_result`
- `steps`
- `execution_trace`
- `run_id`
- `thread_id`
- `pending_confirmation`
- `run_status`
- `events`

输出语义：

- `steps`：真实步骤投影视图，只用于 `requires_step_projection=True`（即需要 step projection）的 workflow。
- `execution_trace`：普通分支和最终结果的轻量路径说明。
- `events`：图内结构化事件，Web 层可转换为 SSE。
- `pending_confirmation`：当前 run 暂停时返回给 API / 前端。

`GET /api/entry/stream` 会统一进入 `service.entry()`，并把 graph events 转成 SSE。常见事件包括：

- `intent`
- `metadata`
- `steps_projected`
- `step_started`
- `react_iteration`
- `tool_result`
- `confirmation_required`
- `draft_ready`
- `execution_trace`
- `capture_result`
- `answer_delta`
- `done`
- `error`

## Run Snapshot

`EntryOrchestrator.get_run_snapshot()` 和 `list_run_snapshots()` 通过 checkpointer 查询最近 checkpoint，并转为 `AgentRunSnapshot`。

状态推断：

- `failed`：`errors` 非空
- `completed`：`answer_completed=True`
- `waiting_confirmation`：`pending_confirmation` 非空
- `running`：intent 已识别
- `pending`：默认

多个 run 可以共享同一个 `thread_id`；snapshot 按 `run_id` 去重，返回每个 run 的最新 checkpoint。

## Model 使用表

| 阶段 | 代码位置 | model 配置 | 默认值 | 作用 |
| --- | --- | --- | --- | --- |
| Router 意图识别 | `agent/router.py` | `openai_small_model` | `gpt-4.1-nano` | 将 entry 文本分类成 intent，并输出 risk / clarification |
| ReAct 单步循环 | `orchestration_nodes/_react.py` | `openai_small_model` | `gpt-4.1-nano` | 在受控工具集合内做检索探索 |
| Replanner | `agent/restep_projector.py` | `openai_small_model` | `gpt-4.1-nano` | 步骤失败且重试耗尽后生成替代步骤 |
| Direct Answer | `orchestration_nodes/_entry.py` | `openai_small_model` | `gpt-4.1-nano` | 简单问题、问候、无法识别时的短回复 |
| Solidify 草稿 | `orchestration_nodes/_steps.py` | `openai_small_model` | `gpt-4.1-nano` | 从 checkpoint 对话中选择并整理可入库知识 |
| Ask 最终回答 | `runtime_llm.py`, `runtime_ask.py` | `openai_model` | `gpt-4.1-mini` | 基于 graph/local/web evidence 生成回答 |
| 群聊总结 | `thread_summarizer.py` / runtime | `openai_model` 或小模型封装 | 依配置 | 显式总结 thread messages |
| Graphiti 抽取 | `graphiti/llm_strategies.py` | `graphiti_llm_model`，回退 `openai_model` | 与 OpenAI 配置一致 | Graphiti 内部实体/关系抽取 |
| Embedding | `graphiti/store.py` | `openai_embedding_model` | `text-embedding-3-small` | episode / graph 检索 embedding |

注意：Planner 不再调用模型生成步骤；它只选择并投影固定 `WorkflowSpec`。需要语义判断的部分被推迟到执行期 decision node。

## 典型请求

### ask

```text
EntryInput("xxx 是什么？")
  -> entry_graph
  -> route_intent: ask
  -> project_workflow_steps: ask-retrieve -> ask-compose -> ask-verify
  -> step_execution_graph
     -> ask-retrieve: query understanding / retrieval / ContextPack artifact
     -> ask-compose: answer generation
     -> ask-verify: verifier / retry / web fallback
  -> finalize_entry_result
```

### delete_knowledge

```text
EntryInput("删除那条关于 xxx 的笔记")
  -> route_intent: delete_knowledge
  -> project_workflow_steps: del-1..del-4
  -> validate_projected_steps
  -> del-1 retrieve, optional ReAct graph_search
  -> del-2 resolve, graph episode / local candidate selection
  -> del-3 tool_call delete_note
     -> pending_confirmation
     -> interrupt
     -> resume confirm/reject
  -> del-4 compose
  -> finalize_entry_result
```

### solidify_conversation

```text
EntryInput("把刚才结论沉淀成知识")
  -> route_intent: solidify_conversation
  -> project_workflow_steps: sol-1..sol-2
  -> sol-1 compose
     -> render checkpoint dialogue turns
     -> LLM selects scope and emits draft JSON
     -> draft_ready event
  -> sol-2 tool_call capture_text
     -> reuse capture pipeline
  -> finalize_entry_result
```

## 测试覆盖

主要测试位于 [tests/test_orchestration.py](../../tests/test_orchestration.py)、[tests/test_step_projector.py](../../tests/test_step_projector.py)、[tests/test_step_projection_validator.py](../../tests/test_step_projection_validator.py) 和 [tests/test_checkpoint_scripts.py](../../tests/test_checkpoint_scripts.py)。

覆盖重点：

- `AgentGraphState` 序列化、事件追加、snapshot 转换。
- `run_id / thread_id` 生成与同 thread 消息累积。
- checkpointer 构建、连接关闭后重建。
- entry graph 构建和普通分支执行。
- clarification interrupt/resume。
- HITL confirmation interrupt/resume。
- ReAct 受控工具、迭代、ToolNode 结果消费。
- workflow projection 和 StepProjectionValidator。
- checkpoint 导出脚本。

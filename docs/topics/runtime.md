# 运行时与编排层说明

本文汇总当前项目运行时与编排层的职责划分、执行路径、当前能力、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/agent/runtime.py](../../src/personal_agent/agent/runtime.py)、[src/personal_agent/agent/orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)、[src/personal_agent/agent/orchestration_nodes/](../../src/personal_agent/agent/orchestration_nodes/)、[src/personal_agent/agent/capture_flow.py](../../src/personal_agent/agent/capture_flow.py)、[src/personal_agent/agent/graph_capture_flow.py](../../src/personal_agent/agent/graph_capture_flow.py)、[src/personal_agent/agent/nodes.py](../../src/personal_agent/agent/nodes.py) 和 [src/personal_agent/agent/service.py](../../src/personal_agent/agent/service.py)。

## 设计目标

运行时与编排层负责把入口、路由、Workflow / Step Projection、工具、记忆、检索、校验和反馈串成稳定执行链路：

- `AgentService` 保持薄 facade
- `AgentRuntime` 拥有核心运行时依赖
- LangGraph entry 总图承担路由、固定分支、workflow 步骤投影、ReAct、HITL 和 checkpoint 编排
- 统一返回 Web、CLI、飞书可消费的结果对象

## 组件分层

### 1. `AgentService`

代码位置：[service.py](../../src/personal_agent/agent/service.py)

作用：

- 装配 settings、store、graph store、ask history store 和 capture service
- 暴露稳定 public API
- 将具体执行委托给 `AgentRuntime`

### 2. `AgentRuntime`

代码位置：[runtime.py](../../src/personal_agent/agent/runtime.py)

作用：

- 持有工具注册表
- 持有记忆门面
- 持有 verifier、workflow step projector（历史类名仍为 planner）、validator、replanner
- 执行 capture、ask、digest、entry、graph sync 等核心流程

### 3. LangGraph 编排

代码位置：[orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)、[orchestration_nodes/](../../src/personal_agent/agent/orchestration_nodes/)、[capture_flow.py](../../src/personal_agent/agent/capture_flow.py)、[graph_capture_flow.py](../../src/personal_agent/agent/graph_capture_flow.py)、[nodes.py](../../src/personal_agent/agent/nodes.py)

作用：

- `build_entry_orchestration_graph()`：entry 父图，组合 `EntryGraph`、普通分支与步骤执行子图
- `build_entry_graph()`：归一化、意图路由与澄清 interrupt/resume
- `build_step_execution_graph()`：负责确定性步骤、HITL、重试与最终汇总
- `build_react_graph()`：受限 ReAct 轮次及其工具执行边界
- `run_capture_flow()`：capture 分支的确定性业务流，不单独 compile LangGraph
- `GraphCaptureFlow`：capture 后的图谱摄取、graph sync 状态回写、批量同步和质量指标
- `execute_ask()`：ask 运行时 pipeline，负责 graph/local/web 检索、rerank、生成和校验

## 当前执行路径

### `execute_capture`

```text
text/source
  -> run_capture_flow()
  -> PostgresMemoryStore
  -> GraphCaptureFlow optional Graphiti sync
  -> CaptureResult
```

### `execute_ask`

```text
question
  -> bind session / refresh memory
  -> graph ask
  -> local/vector retrieval and evidence pipeline
  -> verifier
  -> optional retry
  -> record turn
  -> AskResult
```

### `execute_entry`

```text
EntryInput
  -> AgentRuntime.execute_entry()
  -> build_entry_orchestration_graph()
  -> EntryGraph: normalize_entry -> route_intent / clarification
  -> capture / ask / summarize / direct_answer
     或 StepExecutionGraph: project_workflow_steps -> validate_projected_steps -> step loop / HITL
        -> ReactGraph（仅 react 步骤）
  -> finalize_entry_result
  -> EntryResult
```

## 当前能力

- 已以 `AgentRuntime` 作为核心运行时
- 已将 `AgentService` 收敛为薄 facade
- 已支持 capture、ask、digest、entry 等统一运行时方法
- 已支持 LangGraph entry 总编排
- 已支持 workflow 投影步骤在 orchestration graph 内执行
- 已支持图谱失败时本地回退
- 已支持 verifier 校验和低置信度重试
- 已支持图谱异步/手动同步重试
- 已支持 Graph HITL 确认和拒绝
- 已支持 LangGraph checkpoint 历史查询和基于历史 checkpoint 的 fork 回放
- 已支持 health 和开发环境全量数据 reset
- 已支持 projected `steps` 与 `execution_trace` 分离，避免普通 branch workflow 生成伪步骤

## 新增公开方法（v0.2+）

为减少 Web 层对 runtime 内部方法的直接访问，新增以下公开 API：

### `classify_intent(entry_input: EntryInput) -> RouterDecision`

意图分类的公开封装，供入口层在不需要完整 `execute_entry()` 时快速获得路由决策。

### `workflow_planner / step_projection_validator`

运行时通过只读属性暴露 `WorkflowPlanner` 和 `StepProjectionValidator` 给 orchestration deps。Router 产出的 Goal 会统一进入 WorkflowPlanner；Planner 选择 WorkflowSpec 并编译 ExecutionPlan，Validator 只校验 workflow 编译结果，不读取 Router 执行策略。

### `list_run_history(run_id: str, limit: int = 100) -> list[dict]`

基于 LangGraph `get_state_history()` 返回某次 run 的 checkpoint 时间线摘要，包括 checkpoint id、父 checkpoint id、线程、状态、intent、下一步节点、事件数量、工具结果数量和 pending confirmation。它用于调试和运营后台查看“这次执行是如何走到当前状态的”，不直接暴露完整 checkpoint payload。

这个接口不只是在给 `replay_from_checkpoint()` 提供 `checkpoint_id`，更重要的是帮助人或管理后台**选择应该从哪个历史点回放**。如果只返回一串 checkpoint id，使用者无法判断哪个点是“路由刚完成”、哪个点是“步骤刚投影出来”、哪个点是“删除确认前”、哪个点已经执行过工具。轻量摘要会保留足够的判断信息：

```json
{
  "checkpoint_id": "1f0...",
  "parent_checkpoint_id": "0e9...",
  "thread_id": "user:dns-session",
  "run_id": "abc123",
  "status": "waiting_confirmation",
  "intent": "delete_knowledge",
  "next": ["confirm_step"],
  "event_count": 7,
  "tool_result_count": 1,
  "pending_confirmation": {
    "kind": "tool_confirmation",
    "tool_name": "delete_note",
    "step_id": "delete-1"
  }
}
```

同时它避免直接暴露完整 checkpoint state。完整 state 里可能包含 `messages`、`tool_messages`、`tool_results`、检索结果、用户原文和工具输入输出；直接返回会过大、敏感且难以稳定序列化。摘要只保留选择回放点所需字段。

### `replay_from_checkpoint(thread_id, checkpoint_id, updates, as_node=None) -> EntryResult`

基于 LangGraph `update_state()` 从历史 checkpoint fork 出一条新执行线，先应用指定 state updates，再继续 graph invoke。该能力的核心价值是**现网问题复现**：按用户、run、thread 找到某次失败记录，再从失败前后的真实 checkpoint 分叉重放，保留当时的消息、投影步骤、工具归属、工具结果、pending confirmation 和 errors，而不是只拿用户输入重新跑一遍。对带副作用流程的重放依赖工具层的持久幂等账本保护，避免二次删除或二次写入。

执行过程：

```text
GET /api/entry/runs/{run_id}/history
  -> graph.get_state_history({"configurable": {"thread_id": latest.thread_id}})
  -> 返回轻量 checkpoint 摘要，供人选择 checkpoint_id

POST /api/entry/threads/{thread_id}/checkpoints/{checkpoint_id}/replay
  body: {"updates": {...}, "as_node": "..."}
  -> graph.update_state({"thread_id": thread_id, "checkpoint_id": checkpoint_id}, updates, as_node=...)
  -> 生成 fork_config
  -> graph.invoke(None, fork_config)
  -> 如果再次 interrupt，返回 waiting_confirmation；否则返回新的 EntryResult
```

关键点是：`update_state()` 修改的是 LangGraph checkpoint 中的 `AgentGraphState`，不是业务数据库。它适合修正流程状态后重放，比如 `pending_confirmation`、`step_execution.results`、`answer`、`errors`、`tool_tracking` 等；它不等价于“恢复已删除的知识笔记”。

典型应用场景：现网删除流程复现

```text
用户：DNS 是什么？
系统：回答 DNS 概念。
用户：把这段知识固化下来。
系统：生成并写入 DNS 知识笔记。
用户：删除刚才 DNS 这部分知识。
系统：进入 delete_knowledge 流程，并在删除前产生 HITL 确认。
```

如果这时发现 planner 选错了候选 note，或者确认 payload 里的 `note_id` 不对，管理员可以：

1. 调 `GET /api/entry/runs/{run_id}/history`，找到 `status=waiting_confirmation`、`intent=delete_knowledge`、`pending_confirmation.tool_name=delete_note` 的 checkpoint。
2. 调 replay 接口，从该 checkpoint fork。
3. 先不改或只做最小 `updates`，重放确认是否能复现用户反馈的卡住、误选或状态异常。
4. 修代码、prompt 或策略后，再用同一个 checkpoint 重放验证修复是否有效。
5. 必要时在受控管理后台中用白名单 `updates` 修正候选结果或清空 transient error，让图从修正后的状态继续执行。

这比“拿用户那句话重新跑一遍”更可靠，因为 Agent 失败常常依赖当时的执行现场：历史 `messages`、router/projector 中间状态、`step_execution.steps`、ReAct 轮次、`tool_tracking`、`tool_results`、`pending_confirmation`、`errors` 和下一步 graph node。checkpoint replay 保留的是这些现场，而不是只保留入口文本。

不适用场景：

- 用户在确认阶段反悔：应走普通 `resume_entry(decision="reject")`，不需要 replay。
- 删除已经真实执行后想恢复数据：需要删除前快照、软删除、回收站或补偿恢复能力；`replay_from_checkpoint()` 只能回放流程状态，不能自动还原 `knowledge_notes` 表。
- 普通用户自助功能：replay 是现网复现 / 管理后台能力，不应裸露给用户随意传 `updates`。
- 生产自动恢复：replay 可能重新经过工具节点，应作为调试 / 管理能力使用；带副作用工具依赖 `tool_idempotency_ledger` 防止重复执行。

对应 Web API：

- `GET /api/entry/runs/{run_id}/history`
- `POST /api/entry/threads/{thread_id}/checkpoints/{checkpoint_id}/replay`

## 已知限制

### 1. `AgentRuntime` 职责过重

当前 `AgentRuntime` 仍同时承担依赖装配、public API facade、entry graph 调用、capture、ask、digest、tool registry、graph sync、LLM 调用和 admin 操作等职责。虽然 mixin 已经把文件拆小，但对象边界仍然偏“上帝类”：node 已经成为 LangGraph 编排单元，很多业务能力却仍要通过 runtime 方法或 runtime 私有字段间接触达。

这会带来几个问题：

- ~~orchestration nodes 仍依赖 `OrchestrationDeps.from_runtime()` 从 runtime 抽取大量私有字段。~~ **已修复**：`OrchestrationDeps.from_runtime()` 现在通过 `@property` 公开属性访问（`runtime.intent_router`、`runtime.planner` 等），不再直接访问私有字段。
- 工具由 `build_capture_text_tool(capture_executor)` 创建，通过注入 callable 调用采集能力，并由 `ToolNode` 执行。
- Runtime 修改容易影响多个入口和测试面，局部能力难以单独替换或复用。
- LangGraph 已经表达流程，但业务执行边界还没有完全下沉到 node/service 层。

期望方向是：`AgentRuntime` 逐步收敛为应用级 facade 和依赖装配器，具体能力下沉到明确的 node dependency 或领域 service。

### 2. 普通分支事件粒度仍可增强

普通 `capture / ask / summarize / direct_answer` 已进入 entry 总编排，但分支内部仍主要返回 answer、citations、matches 等结果字段。后续可继续补充更细粒度的 `AgentEvent`，让普通分支和计划步骤在前端反馈上更一致。

### 3. ReAct 单步策略仍处于受控首版

当前 entry 总编排已在 `execution_mode="react"` 的步骤内执行有限轮 Thought / Action / Observation 循环。运行时由 orchestration nodes 维护 step 状态、进度事件、失败处理、replan 和最终 `EntryResult`，ReAct 只负责单个步骤内部的观察式工具调用。

当前约束：

- 默认只允许 `graph_search / web_search` 等只读检索工具
- 高风险、写长期知识和需要确认的工具会被阻断
- `max_iterations` 有固定上限
- 每轮迭代发出 `react_iteration` 事件

它仍是首版能力，后续需要继续收敛事件 schema 和扩展适用步骤。

## 演进方向

- 将 `AgentRuntime` 收敛为薄 facade / dependency provider，业务执行下沉到 node/service
- 为普通分支和计划步骤建立统一 `AgentEvent` schema
- 为 runtime 增加更系统的集成测试和回归评测

## 下一步实现方案：Runtime 职责下沉

### 目标边界

保留在 `AgentRuntime` 的职责：

- 入口级 public API：`entry()`、`capture()`、`ask()` 等兼容方法。
- 依赖装配：settings、store、graph store、memory、tool registry、checkpointer。
- LangGraph graph 构建与 run/snapshot/resume 管理。
- Web/CLI/飞书需要的结果模型兼容转换。

下沉出 `AgentRuntime` 的职责：

- `capture` 执行细节：下沉为 `CaptureNodeDeps` 或 `CaptureServiceFacade`。
- `ask` 检索、证据组装、回答生成、verifier retry：下沉为 `AskService` / `AskNodeDeps`。
- direct answer / summarize 的 LLM 调用：下沉为独立 response service。
- tool 执行依赖：工具不再持有 runtime，改持有明确 service 或 callable。
- admin/reset/graph sync：保持 mixin 短期兼容，后续迁移为应用 service。

### 分阶段迁移

1. 定义 `EntryOrchestrationDeps` 的最终形态：只包含 node 需要的显式 service/callable，不再从 runtime 私有字段直接读。
2. 抽出 `AskService`：先迁移 `execute_ask()` 的主体逻辑，runtime 只保留转发方法。
3. 抽出 `CaptureServiceFacade`：把 `execute_capture()` 对 capture flow、store、Graphiti sync 的编排移出 runtime。
4. 工具对 runtime 的依赖已通过 `build_capture_text_tool(capture_executor)` 的依赖注入消除。
5. ~~清理旧 entry 兼容方法。~~ **已完成**：已删除旧入口死代码，runtime entry 路径收敛到当前 LangGraph 编排。
6. 最后压缩 `AgentRuntime.__init__()`：只装配依赖容器和 graph，不再承载具体业务流程。

### 验收标准

- ~~orchestration nodes 不访问 runtime 私有字段。~~ **已完成**：`OrchestrationDeps.from_runtime()` 使用公开属性。
- 工具不持有 `AgentRuntime` 实例；LangChain 工具工厂接收所需 callable。
- runtime public 方法仍兼容现有 Web/CLI/飞书调用。
- 所有核心回归测试通过。

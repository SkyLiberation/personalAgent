# 运行时与编排层说明

本文汇总当前项目运行时与编排层的职责划分、执行路径、当前能力、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/agent/runtime.py](../../src/personal_agent/agent/runtime.py)、[src/personal_agent/agent/orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)、[src/personal_agent/agent/orchestration_nodes.py](../../src/personal_agent/agent/orchestration_nodes.py)、[src/personal_agent/agent/graph.py](../../src/personal_agent/agent/graph.py)、[src/personal_agent/agent/nodes.py](../../src/personal_agent/agent/nodes.py) 和 [src/personal_agent/agent/service.py](../../src/personal_agent/agent/service.py)。

## 设计目标

运行时与编排层负责把入口、路由、规划、工具、记忆、检索、校验和反馈串成稳定执行链路：

- `AgentService` 保持薄 facade
- `AgentRuntime` 拥有核心运行时依赖
- LangGraph entry 总图承担路由、固定分支、计划步骤、ReAct、HITL 和 checkpoint 编排
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
- 持有 verifier、planner、validator、replanner
- 执行 capture、ask、digest、entry、graph sync、pending action 等核心流程

### 3. LangGraph 编排

代码位置：[orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)、[orchestration_nodes.py](../../src/personal_agent/agent/orchestration_nodes.py)、[graph.py](../../src/personal_agent/agent/graph.py)、[nodes.py](../../src/personal_agent/agent/nodes.py)

作用：

- `build_entry_orchestration_graph()`：entry 总编排，覆盖 route、普通分支、plan、step、ReAct、HITL、finalize
- `build_capture_graph()`：采集、增强、关联、复习调度
- `build_ask_graph()`：本地问答

## 当前执行路径

### `execute_capture`

```text
text/source
  -> capture graph
  -> LocalMemoryStore
  -> optional Graphiti sync
  -> CaptureResult
```

### `execute_ask`

```text
question
  -> bind session / refresh memory
  -> graph ask
  -> graph answer or local ask graph fallback
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
  -> normalize_entry
  -> route_intent
  -> capture / ask / summarize / direct_answer
     或 plan_task -> validate_plan -> step loop / ReAct / HITL
  -> finalize_entry_result
  -> EntryResult
```

## 当前能力

- 已以 `AgentRuntime` 作为核心运行时
- 已将 `AgentService` 收敛为薄 facade
- 已支持 capture、ask、digest、entry 等统一运行时方法
- 已支持 LangGraph entry 总编排
- 已支持计划步骤在 orchestration graph 内执行
- 已支持图谱失败时本地回退
- 已支持 verifier 校验和低置信度重试
- 已支持图谱异步/手动同步重试
- 已支持 pending action 确认和拒绝
- 已支持 health 和 reset 用户数据
- 已支持 `plan_steps` 与 `execution_trace` 分离，避免非计划任务生成伪计划

## 新增公开方法（v0.2+）

为减少 Web 层对 runtime 内部方法的直接访问，新增以下公开 API：

### `classify_intent(entry_input: EntryInput) -> RouterDecision`

意图分类的公开封装，供入口层在不需要完整 `execute_entry()` 时快速获得路由决策。

### `plan_for_entry(entry_input: EntryInput) -> tuple[RouterDecision, list[PlanStep], list[dict]]`

运行会话绑定和意图路由。只有 `RouterDecision.requires_planning=True` 时才继续规划和校验，并填充 `WorkingMemory.plan_steps`；普通意图返回空计划，由执行阶段生成 `execution_trace`。

### `execute_ask_stream(question, user_id, session_id)`

流式问答的正式公开 API，封装了图谱/本地检索、prompt 构建、token 流式输出和 turn 记录。生成器产出 SSE 兼容的 `(event_type, payload)` 元组：`status`、`metadata`、`answer_delta`、`answer_complete`、`answer_error`、`done`。Web 层通过 `_stream_events()` 桥接为异步 SSE 帧即可。

## 已知限制

### 1. 普通分支事件粒度仍可增强

普通 `capture / ask / summarize / direct_answer` 已进入 entry 总编排，但分支内部仍主要返回 answer、citations、matches 等结果字段。后续可继续补充更细粒度的 `AgentEvent`，让普通分支和计划步骤在前端反馈上更一致。

### 2. ReAct 单步策略仍处于受控首版

当前 entry 总编排已在 `execution_mode="react"` 的步骤内执行有限轮 Thought / Action / Observation 循环。运行时由 orchestration nodes 维护 step 状态、进度事件、失败处理、replan 和最终 `EntryResult`，ReAct 只负责单个步骤内部的观察式工具调用。

当前约束：

- 默认只允许 `graph_search / web_search` 等只读检索工具
- 高风险、写长期知识和需要确认的工具会被阻断
- `max_iterations` 有固定上限
- 每轮迭代发出 `react_iteration` 事件

它仍是首版能力，后续需要继续收敛事件 schema 和扩展适用步骤。

## 演进方向

- 为普通分支和计划步骤建立统一 `AgentEvent` schema
- 为 runtime 增加更系统的集成测试和回归评测

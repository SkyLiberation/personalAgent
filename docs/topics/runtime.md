# 运行时与编排层说明

本文汇总当前项目运行时与编排层的职责划分、执行路径、当前能力、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/agent/runtime.py](../../src/personal_agent/agent/runtime.py)、[src/personal_agent/agent/graph.py](../../src/personal_agent/agent/graph.py)、[src/personal_agent/agent/nodes.py](../../src/personal_agent/agent/nodes.py) 和 [src/personal_agent/agent/service.py](../../src/personal_agent/agent/service.py)。

## 设计目标

运行时与编排层负责把入口、路由、规划、工具、记忆、检索、校验和反馈串成稳定执行链路：

- `AgentService` 保持薄 facade
- `AgentRuntime` 拥有核心运行时依赖
- LangGraph 承担稳定分支编排
- `PlanExecutor` 承担复杂计划执行
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

### 3. LangGraph 固定流程

代码位置：[graph.py](../../src/personal_agent/agent/graph.py)、[nodes.py](../../src/personal_agent/agent/nodes.py)

作用：

- `build_capture_graph()`：采集、增强、关联、复习调度
- `build_ask_graph()`：本地问答
- `build_entry_graph()`：根据 intent 路由到固定分支

### 4. Plan-driven 流程

代码位置：[plan_executor.py](../../src/personal_agent/agent/plan_executor.py)

作用：

- 对 `requires_planning=True` 的任务执行结构化计划
- 当前主要服务 `delete_knowledge` 和 `solidify_conversation`

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
  -> bind session / refresh memory
  -> DefaultIntentRouter
  -> requires_planning?
     -> yes: DefaultTaskPlanner -> PlanValidator -> WorkingMemory.plan_steps -> PlanExecutor
     -> no: LangGraph branch -> WorkingMemory.execution_trace
  -> EntryResult
```

## 当前能力

- 已以 `AgentRuntime` 作为核心运行时
- 已将 `AgentService` 收敛为薄 facade
- 已支持 capture、ask、digest、entry 等统一运行时方法
- 已支持 LangGraph 固定流程
- 已支持 PlanExecutor 计划驱动流程
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

### 1. 固定图和计划执行仍是双轨

普通 `capture / ask / summarize / direct_answer / unknown` 主要走 LangGraph 固定分支；`delete_knowledge / solidify_conversation` 走 `PlanExecutor`。当前已经通过 `execution_trace` 区分非计划路径，但固定图和计划执行仍是两套执行机制，行为一致性和事件模型仍需维护。

### 2. ReAct 单步策略仍处于受控首版

当前 `PlanExecutor` 已接入 `ReActStepRunner`，可以在 `execution_mode="react"` 的步骤内执行有限轮 Thought / Action / Observation 循环。运行时仍由 `PlanExecutor` 统一维护 `WorkingMemory`、进度事件、失败处理、replan 和最终 `EntryResult`，ReAct 只负责单个步骤内部的观察式工具调用。

当前约束：

- 默认只允许 `graph_search / web_search` 等只读检索工具
- 高风险、写长期知识和需要确认的工具会被阻断
- `max_iterations` 有固定上限
- 每轮迭代发出 `react_iteration` 事件

它仍是首版能力，后续需要继续收敛事件 schema、扩展适用步骤，并评估是否用 LangGraph `StateGraph` 表达 runner 内部状态。

### 3. LangGraph checkpoint 尚未引入

当前长任务、审批恢复和中断续接主要依赖应用层持久化模型。多段审批或长时间恢复场景增多后，需要重新评估 checkpoint。

## 演进方向

- 明确哪些 intent 应逐步迁移到 PlanExecutor
- 为固定图和计划执行建立统一 `AgentEvent` schema
- 评估 LangGraph checkpoint 在多段审批中的价值
- 为 runtime 增加更系统的集成测试和回归评测

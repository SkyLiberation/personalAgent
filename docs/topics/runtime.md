# 运行时与编排层说明

本文汇总当前项目运行时与编排层的职责划分、执行路径、当前能力、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/agent/runtime.py](../../src/personal_agent/agent/runtime.py)、[src/personal_agent/agent/orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)、[src/personal_agent/agent/orchestration_nodes/](../../src/personal_agent/agent/orchestration_nodes/)、[src/personal_agent/agent/capture_flow.py](../../src/personal_agent/agent/capture_flow.py)、[src/personal_agent/agent/graph_capture_flow.py](../../src/personal_agent/agent/graph_capture_flow.py)、[src/personal_agent/agent/nodes.py](../../src/personal_agent/agent/nodes.py) 和 [src/personal_agent/agent/service.py](../../src/personal_agent/agent/service.py)。

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
- 执行 capture、ask、digest、entry、graph sync 等核心流程

### 3. LangGraph 编排

代码位置：[orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)、[orchestration_nodes/](../../src/personal_agent/agent/orchestration_nodes/)、[capture_flow.py](../../src/personal_agent/agent/capture_flow.py)、[graph_capture_flow.py](../../src/personal_agent/agent/graph_capture_flow.py)、[nodes.py](../../src/personal_agent/agent/nodes.py)

作用：

- `build_entry_orchestration_graph()`：entry 父图，组合 `EntryGraph`、普通分支与 `PlanExecutionGraph`
- `build_entry_graph()`：归一化、意图路由与澄清 interrupt/resume
- `build_plan_execution_graph()`：计划、确定性步骤、HITL、重试与最终汇总
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
     或 PlanExecutionGraph: plan_task -> validate_plan -> step loop / HITL
        -> ReactGraph（仅 react 步骤）
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
- 已支持 Graph HITL 确认和拒绝
- 已支持 health 和开发环境全量数据 reset
- 已支持 `plan_steps` 与 `execution_trace` 分离，避免非计划任务生成伪计划

## 新增公开方法（v0.2+）

为减少 Web 层对 runtime 内部方法的直接访问，新增以下公开 API：

### `classify_intent(entry_input: EntryInput) -> RouterDecision`

意图分类的公开封装，供入口层在不需要完整 `execute_entry()` 时快速获得路由决策。

### `plan_for_entry(entry_input: EntryInput) -> tuple[RouterDecision, list[PlanStep], list[dict]]`

运行会话绑定和意图路由。只有 `RouterDecision.requires_planning=True` 时才继续规划和校验，并写入 checkpoint 中的 `AgentGraphState.plan`；普通意图返回空计划，由执行阶段生成 `execution_trace`。

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
5. ~~清理 `RuntimeEntryMixin.plan_for_entry()` 等 LangGraph 改造后的兼容遗留方法。~~ **已完成**：`plan_for_entry()` 已删除（118 行死代码），`runtime_entry.py` 从 163 行精简到 40 行。
6. 最后压缩 `AgentRuntime.__init__()`：只装配依赖容器和 graph，不再承载具体业务流程。

### 验收标准

- ~~orchestration nodes 不访问 runtime 私有字段。~~ **已完成**：`OrchestrationDeps.from_runtime()` 使用公开属性。
- 工具不持有 `AgentRuntime` 实例；LangChain 工具工厂接收所需 callable。
- runtime public 方法仍兼容现有 Web/CLI/飞书调用。
- 所有核心回归测试通过。

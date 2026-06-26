# 执行与反馈层说明

本文汇总当前项目执行与反馈层的职责划分、当前能力、已知限制和后续改进方向。

## 设计目标

执行与反馈层负责把 Agent 内部执行过程转成用户和前端可以理解的结果：

- 同步 API 返回结构化结果
- SSE 推送流式回答和计划事件
- 前端可展示 step panel、citations 和 Graph 确认面板
- 高风险操作通过 HITL 确认闭环
- 图谱失败、低置信度和执行失败要有可感知反馈

## 主要反馈通道

### 1. 同步 API

当前同步接口覆盖：

- capture
- ask
- entry
- digest
- notes
- tools
- ask history

### 2. SSE

当前 SSE 覆盖：

- `GET /api/entry/stream`

事件包括：

- `status`
- `metadata`
- `answer_delta`
- `intent`
- `steps_projected`
- `step_started`
- `step_completed`
- `step_failed`
- `plan_step_retry`
- `plan_replan_attempt`
- `plan_replanned`
- `execution_trace`
- `confirmation_required`
- `capture_result`
- `draft_ready`
- `done`
- `error`

### 3. Graph HITL 确认

高风险删除采用 LangGraph interrupt/resume 两阶段 HITL：

1. 工具先返回 `pending_confirmation`
2. 前端展示确认面板
3. 用户确认或拒绝
4. Graph resume 后执行真实删除或跳过后续步骤

## 当前能力

- 已支持同步 API 返回结构化结果
- 已支持 `entry_stream` ask 路径的模型 token 流式输出
- 已支持 `execution_trace` 事件，用于展示非计划驱动路径的执行轨迹
- 已支持 entry SSE 事件
- 已支持计划创建和步骤状态回传
- 已支持 Graph HITL 确认和拒绝
- 已支持 `draft_ready` 事件
- 已支持 citation 元数据返回
- 已支持图谱同步手动重试
- 已补事件回归样本：orchestration/API 回归覆盖 `draft_ready`、`confirmation_required`、计划步骤状态和 ReAct dispatch 事件

## 已知限制

### 1. 事件 schema 仍未形式化

当前 SSE 已覆盖 `status / metadata / answer_delta / plan_* / execution_trace / confirmation_required / capture_result / draft_ready / done / error` 等事件。`AgentEvent` 已定义在 [orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py) 中（包含 `event_id`、`run_id`、`thread_id`、`type`、`timestamp`、`payload` 字段），但 orchestration graph 与 SSE 之间的转换桥 `_sse_event()` 还在按事件名分发，未完全收敛为统一模型驱动。不同入口和前端仍依赖事件名与 payload 约定协作。

### 2. 计划执行事件主要服务 Web

飞书和 CLI 当前无法获得与 Web 前端同等粒度的计划执行反馈。

### 3. HITL 确认只由 checkpoint 承载

Postgres checkpoint 保存可恢复的 graph 状态和 `pending_confirmation`；复杂多段审批后续也应优先扩展 Graph state，而不是新增并行业务状态表。

### 4. 错误反馈还可以更结构化

部分失败仍以文本 message 或 HTTPException 返回，后续可以统一错误码、可恢复性、用户动作建议和审计字段。

## 演进方向

- 将 SSE / execution trace / plan progress 抽象为统一 `AgentEvent` schema
- 将计划事件扩展到飞书和 CLI
- 为 Graph HITL 增加更完整的状态机视图
- 为错误反馈增加结构化错误码和恢复建议

## 下一步实现方案：完善 `AgentEvent` 收敛

目标：把 Web SSE、计划执行进度、普通 ask/capture 的 `execution_trace`、Graph HITL、草稿固化事件和错误反馈收敛为同一套结构化事件模型，避免不同入口各自解释事件名和 payload。

当前 `AgentEvent` 已定义在 [orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py)（字段：`event_id`、`run_id`、`thread_id`、`type`、`timestamp`、`payload`），orchestration graph 节点已在写入事件。剩余工作是将 Web SSE 桥 `_sse_event()` 从按事件名分发改为基于 `AgentEvent.type` 驱动，以及为 CLI/飞书入口补充事件消费。

### 1. 当前事件模型

### 2. Runtime 统一产出事件

在 `AgentRuntime` 内增加轻量事件工厂方法，例如 `make_event()` / `emit_event()`，负责填充 `event_id / trace_id / user_id / session_id / created_at` 等公共字段。

同步改造以下路径：

- `execute_entry()` / graph plan execution nodes：计划创建、步骤开始/完成/失败都输出 `AgentEvent`
- 非计划路径：把 `execution_trace` 从字符串数组逐步改为 `execution_trace` 事件
- `confirmation_required` 与 `draft_ready`：保留现有 payload，但包进统一事件 envelope

### 3. Web / CLI / 飞书复用同一事件语义

Web 层 `_sse_event()` 只做 `AgentEvent -> SSE frame` 转换，不再维护私有事件 shape。

CLI 和飞书入口按自身能力消费同一事件：

- CLI：默认打印 `status / done / error`，调试模式打印 plan 和 trace
- 飞书：发送用户可见的 `status / confirmation_required / draft_ready / done / error`
- Web：继续展示完整 step panel、execution trace、citation 和确认面板

### 4. 错误与恢复建议结构化

新增统一错误 payload：

```text
code
message
recoverable
suggested_action
details
```

优先覆盖工具失败、图谱同步失败、网络搜索失败、HITL resume 错误和权限/限流错误。

### 5. 测试落点

- 为 `AgentEvent` 序列化和默认字段补单元测试
- 为 graph plan execution 事件补 plan 事件测试
- 为 Web SSE bridge 补 `AgentEvent -> SSE` 转换测试
- 为 CLI/飞书事件降级展示补轻量回归测试

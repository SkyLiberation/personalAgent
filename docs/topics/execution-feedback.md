# 执行与反馈层说明

本文汇总当前项目执行与反馈层的职责划分、当前能力、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/web/api.py](../../src/personal_agent/web/api.py)、[src/personal_agent/agent/runtime.py](../../src/personal_agent/agent/runtime.py) 和 [src/personal_agent/agent/plan_executor.py](../../src/personal_agent/agent/plan_executor.py)。

## 设计目标

执行与反馈层负责把 Agent 内部执行过程转成用户和前端可以理解的结果：

- 同步 API 返回结构化结果
- SSE 推送流式回答和计划事件
- 前端可展示 plan panel、citations、pending actions
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
- pending actions

### 2. SSE

当前 SSE 覆盖：

- `GET /api/ask/stream`
- `GET /api/entry/stream`

事件包括：

- `status`
- `metadata`
- `answer_delta`
- `citation`
- `intent`
- `plan_created`
- `plan_step_started`
- `plan_step_completed`
- `plan_step_failed`
- `plan_step_retry`
- `plan_replan_attempt`
- `plan_replanned`
- `pending_action_created`
- `draft_ready`
- `done`
- `error`

### 3. Pending Action

高风险删除采用应用层两阶段 HITL：

1. 工具先创建 `PendingAction`
2. 前端展示确认面板
3. 用户确认或拒绝
4. 后端执行真实删除或结束 pending action

## 当前能力

- 已支持同步 API 返回结构化结果
- 已支持 `ask_stream` 和 `entry_stream` ask 路径的模型 token 流式输出
- 已统一 `ask_stream` 和 `entry_stream` ask 路径的底层公开 API：`AgentRuntime.execute_ask_stream()`
- 已支持 `execution_trace` 事件，用于展示非计划驱动路径的执行轨迹
- 已支持 entry SSE 事件
- 已支持计划创建和步骤状态回传
- 已支持 pending action 创建、确认和拒绝
- 已支持 `draft_ready` 事件
- 已支持 citation 元数据返回
- 已支持图谱同步手动重试
- 已支持问答历史搜索、单条删除和按会话删除
- 已补事件回归样本：`test_plan_executor.py` 覆盖 `draft_ready`、`pending_action_created`、计划步骤状态和 ReAct dispatch 事件

## 已知限制

### 1. 事件 schema 仍未形式化

当前 SSE 已覆盖 `status / metadata / answer_delta / citation / plan_* / execution_trace / pending_action_created / draft_ready / done / error` 等事件，但还没有统一的 `AgentEvent` 类型模型。不同入口和前端仍依赖事件名与 payload 约定协作。

### 2. 计划执行事件主要服务 Web

飞书和 CLI 当前无法获得与 Web 前端同等粒度的计划执行反馈。

### 3. Pending action 仍是应用层确认

当前没有 LangGraph checkpoint，复杂多段审批和中断恢复仍需要更明确的持久化流程。

### 4. 错误反馈还可以更结构化

部分失败仍以文本 message 或 HTTPException 返回，后续可以统一错误码、可恢复性、用户动作建议和审计字段。

## 演进方向

- 将 SSE / execution trace / plan progress 抽象为统一 `AgentEvent` schema
- 将计划事件扩展到飞书和 CLI
- 为 pending action 增加更完整的状态机视图
- 为错误反馈增加结构化错误码和恢复建议

## 下一步实现方案：统一 `AgentEvent`

目标：把 Web SSE、计划执行进度、普通 ask/capture 的 `execution_trace`、pending action、草稿固化事件和错误反馈收敛为同一套结构化事件模型，避免不同入口各自解释事件名和 payload。

### 1. 新增事件模型

在 `core/models.py` 或独立 `core/events.py` 中新增 `AgentEvent`，字段保持稳定、可序列化：

```text
event_id
event_type
user_id
session_id
trace_id
intent
step_id
status
message
payload
created_at
```

`event_type` 首批覆盖：

```text
status
metadata
answer_delta
answer_complete
plan_created
plan_step_started
plan_step_completed
plan_step_failed
execution_trace
react_iteration
pending_action_created
draft_ready
error
done
```

### 2. Runtime 统一产出事件

在 `AgentRuntime` 内增加轻量事件工厂方法，例如 `make_event()` / `emit_event()`，负责填充 `event_id / trace_id / user_id / session_id / created_at` 等公共字段。

同步改造以下路径：

- `execute_ask_stream()`：由 `(event_type, payload)` 元组升级为 `AgentEvent`，Web 层只负责序列化为 SSE
- `execute_entry()` / `PlanExecutor` progress callback：计划创建、步骤开始/完成/失败都输出 `AgentEvent`
- 非计划路径：把 `execution_trace` 从字符串数组逐步改为 `execution_trace` 事件
- pending action 与 `draft_ready`：保留现有 payload，但包进统一事件 envelope

### 3. Web / CLI / 飞书复用同一事件语义

Web 层 `_stream_events()` 只做 `AgentEvent -> SSE frame` 转换，不再维护私有事件 shape。

CLI 和飞书入口按自身能力消费同一事件：

- CLI：默认打印 `status / done / error`，调试模式打印 plan 和 trace
- 飞书：发送用户可见的 `status / pending_action_created / draft_ready / done / error`
- Web：继续展示完整 plan panel、execution trace、citation 和 pending action 面板

### 4. 错误与恢复建议结构化

新增统一错误 payload：

```text
code
message
recoverable
suggested_action
details
```

优先覆盖工具失败、图谱同步失败、网络搜索失败、pending action token 错误和权限/限流错误。

### 5. 测试落点

- 为 `AgentEvent` 序列化和默认字段补单元测试
- 为 `execute_ask_stream()` 补事件序列回归测试
- 为 `PlanExecutor` progress callback 补 plan 事件测试
- 为 Web SSE bridge 补 `AgentEvent -> SSE` 转换测试
- 为 CLI/飞书事件降级展示补轻量回归测试

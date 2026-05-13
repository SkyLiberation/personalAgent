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
- 已支持 entry SSE 事件
- 已支持计划创建和步骤状态回传
- 已支持 pending action 创建、确认和拒绝
- 已支持 `draft_ready` 事件
- 已支持 citation 元数据返回
- 已支持图谱同步手动重试
- 已支持问答历史搜索、单条删除和按会话删除

## 已知限制

### 1. `ask_stream` 与 `entry_stream` 事件模型仍需收敛

`ask_stream` 和 `entry_stream` 的 ask 路径已经都是模型 token 流。后续需要继续收敛两者的事件模型、metadata/citation 表达和执行路径边界。

### 2. 计划执行事件主要服务 Web

飞书和 CLI 当前无法获得与 Web 前端同等粒度的计划执行反馈。

### 3. Pending action 仍是应用层确认

当前没有 LangGraph checkpoint，复杂多段审批和中断恢复仍需要更明确的持久化流程。

### 4. 错误反馈还可以更结构化

部分失败仍以文本 message 或 HTTPException 返回，后续可以统一错误码、可恢复性、用户动作建议和审计字段。

## 演进方向

- 统一 `ask_stream` 和 `entry_stream` 的事件模型与执行路径边界
- 建立统一 Agent event schema
- 将计划事件扩展到飞书和 CLI
- 为 pending action 增加更完整的状态机视图
- 为错误反馈增加结构化错误码和恢复建议


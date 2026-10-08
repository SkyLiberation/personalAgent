# 入口层说明

本文拥有 Web、CLI 和飞书入口的适配职责与当前调用路径，具体 HTTP 字段由 [API](../api.md)拥有。
入口只做协议适配、身份解析和输入校验；开放语义由 Conversation 模型提出 typed Proposal，
权限与机械不变量由治理代码判断，入口不得补业务语义。

## 设计目标

入口层的目标是让不同来源的请求都能进入同一个 Agent 运行时，而不是各入口各写一套业务逻辑：

- Web API 负责 HTTP 参数接收、鉴权、响应和 SSE 推送
- 前端工作台通过 Web API 使用采集、问答、图谱、记忆和确认能力
- CLI 提供文本对话、周期研究、复习简报和固定流程管理入口
- 飞书长连接把 IM 事件转为内部 `EntryInput`
- `AgentService` 保持薄 facade，最终委托 `AgentRuntime` 中明确的 Conversation 或 Application
  use case

## 组件分层

### 1. Web API

代码位置：[api.py](../../src/personal_agent/adapters/web/api.py)、
[routes/](../../src/personal_agent/adapters/web/routes)、
[context.py](../../src/personal_agent/adapters/web/context.py)

作用：

- 创建 FastAPI 应用
- 初始化 settings 和 logging
- 通过 `WebAppContext` 装配 `CaptureService`、`AgentService`、`FeishuService` 和 Review Digest 运行依赖
- 通过 `routes.register_api_routes()` 注册分组 API 路由
- 启用可选 API Key 鉴权和限流
- 配置 CORS
- 通过 FastAPI lifespan 拉起飞书长连接监听和 Review Digest scheduler
- 托管构建后的前端静态资源

### 2. `AgentService`

代码位置：[service.py](../../src/personal_agent/orchestration/service.py)

作用：

- 作为入口层和 `AgentRuntime` 之间的薄 facade
- 由 Composition Root 注入运行依赖，不拥有领域事实
- 暴露稳定方法给 Web、CLI、飞书等入口调用

当前入口层主要通过这些方法进入运行时：

- `execute_capture()`
- `digest()`
- `converse()`
- `list_notes()`
- `list_tools()`
- `execute_tool()`

### 3. `cli/main.py`

代码位置：[cli/main.py](../../src/personal_agent/adapters/cli/main.py)

作用：

- 提供本地命令行入口
- 按命令装配 `AgentService` 或对应领域执行依赖
- 文本 `entry` 转换成 `ConversationMessage` 并调用 `converse()`
- 输出 JSON 或文本结果

当前 CLI 命令：

- `entry`：文本对话
- `worker`：持久任务队列消费
- `research-once`、`research-subscribe`、`research-schedule`：一次性研究、订阅和调度
- `review-digest`：复习简报生成与投递
- `procedure-eval-record`、`procedure-deploy`、`procedure-dry-run`：固定流程评测登记、部署与试运行

### 4. `FeishuService`

代码位置：[service.py](../../src/personal_agent/adapters/feishu/service.py)

作用：

- 使用飞书官方 SDK 长连接接收消息事件
- 将飞书消息标准化为 `FeishuIncomingMessage`
- 下载飞书文件并写入本地 uploads
- 注册飞书群聊消息加载端口，由明确的业务入口按需调用
- 文本对话转换成 canonical Conversation contract；文件和固定业务命令进入对应 Application
  use case
- 将结果回复到飞书消息或群聊

## Web API 入口

当前 Web 层覆盖的主要能力：

- `GET /api/health`
- `GET /api/tools`
- `POST /api/tools/{name}/execute`
- `GET /api/notes`
- `POST /api/notes/{note_id}/graph-sync`
- `GET /api/notes/{note_id}/chunks`
- `POST /api/notes/{note_id}/delete-commands` 及对应确认、恢复接口
- `POST /api/knowledge/ingest-upload`
- `POST /api/conversation/turn`
- `GET /api/digest`
- `GET /api/entry/stream`
- `POST /api/debug/reset-database`

旧 `/api/entry/runs` 与 resume 路径已经移除并返回 404。更完整的接口说明见
[api.md](../api.md)。

## 统一入口路径

### Web entry

标准 entry 路径：

```text
HTTP request
  -> web/routes/entry.py
  -> ConversationMessage + authenticated principal
  -> AgentService.converse()
  -> ConversationService.respond()
```

适用于：

- `GET /api/entry/stream`

### 飞书 entry

飞书消息路径：

```text
Feishu long connection event
  -> FeishuIncomingMessage
  -> optional file download
  -> text conversation: AgentService.converse()
  -> file/group/business command: corresponding explicit Application use case
  -> Feishu reply
```

### CLI entry

CLI 文本 `entry` 是 canonical Conversation contract 的适配器：

```text
CLI command
  -> ConversationMessage
  -> AgentService.converse(source_platform="cli")
  -> ConversationService.respond()
```

## 当前能力

- 已具备 FastAPI Web API
- 已具备前端静态资源托管
- 已具备 Conversation SSE 入口；当前 SSE 是对完整回复的协议分块，不声称是模型 token 原生流
- 已具备 tools、notes、digest 与 Conversation trace 查询接口
- 已具备 API Key 鉴权和 token bucket 限流
- 已具备 CORS 配置
- 已具备 CLI 本地入口
- 已具备飞书官方 SDK 长连接入口
- 已具备飞书事件短时去重
- 已具备飞书文件下载和群聊消息按需加载
- Web SSE、CLI 文本和飞书文本对话进入同一个 `AgentService.converse()` 合约；固定业务能力保留
  明确 use case，不为形式统一塞进通用图

## 已知限制

### 1. 统一的是契约与边界，不是一个总编排图

Conversation 使用统一消息、身份、scope 与结果契约；`digest`、capture 和周期 Research 拥有各自 Application 入口。依赖装配与状态责任见[当前核心架构](../summary/core-architecture-current-state.md)。

### 2. CLI 与 HTTP 的操作范围不同

CLI 命令见上文。文件上传、知识生命周期确认和图谱重同步由 HTTP API 提供，CLI 没有对应管理命令。

### 3. 飞书入口是后台线程处理，缺少更完整的任务状态反馈

飞书长连接需要快速接收事件，因此当前实现采用事件线程快速接收、后台线程处理。它可以完成回复，但还没有 Web 侧类似的结构化进度事件或步骤面板反馈。

### 4. 用户身份模型仍较轻量

Web 侧通过 API Key 映射用户，SSE 也支持 query 参数传 key；飞书侧可配置是否使用默认用户。当前适合个人或轻量多用户场景，更复杂的组织级权限、租户隔离和审计策略还需要继续增强。

### 5. 流式语义仍有限

`entry_stream` 当前先完成一次 Conversation turn，再将最终文本切片为 SSE。若用户 E2E 证明
首 token 延迟或中途取消不满足要求，才应定义原生流式事件与恢复边界；不能仅为“更像现代
Agent”引入另一套 event schema。

## 证据与后续准入

当前已执行的用户结果与限制见[评测盘点](../evals/02-current-case-inventory.md)。已确认且尚未解决的问题由 [Future 队列](../future/design-optimization-backlog.md)维护；入口能力列表只描述代码存在的调用路径。

# 入口层说明

本文汇总当前项目入口层的职责划分、已有入口、统一调用路径、现有能力、已知限制和后续改进方向。

## 设计目标

入口层的目标是让不同来源的请求都能进入同一个 Agent 运行时，而不是各入口各写一套业务逻辑：

- Web API 负责 HTTP 参数接收、鉴权、响应和 SSE 推送
- 前端工作台通过 Web API 使用采集、问答、图谱、记忆和确认能力
- CLI 提供最小本地操作入口
- 飞书长连接把 IM 事件转为内部 `EntryInput`
- `AgentService` 保持薄 facade，最终委托 `AgentRuntime` 执行

## 组件分层

### 1. Web API

代码位置：[api.py](../../src/personal_agent/web/api.py)、[routes/](../../src/personal_agent/web/routes)、[context.py](../../src/personal_agent/web/context.py)

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

代码位置：[service.py](../../src/personal_agent/agent/service.py)

作用：

- 作为入口层和 `AgentRuntime` 之间的薄 facade
- 负责装配 settings、store、graph store、ask history store 和 capture service
- 暴露稳定方法给 Web、CLI、飞书等入口调用

当前入口层主要通过这些方法进入运行时：

- `execute_capture()`
- `execute_ask()`
- `digest()`
- `entry()`
- `list_notes()`
- `list_tools()`
- `execute_tool()`

### 3. `cli/main.py`

代码位置：[cli/main.py](../../src/personal_agent/cli/main.py)

作用：

- 提供本地命令行入口
- 每次命令构造 `AgentService`
- 将命令行文本统一转换成 `EntryInput(source_platform="cli")` 并调用 `entry()`
- 输出 JSON 或文本结果

当前 CLI 命令：

- `entry`

### 4. `FeishuService`

代码位置：[service.py](../../src/personal_agent/feishu/service.py)

作用：

- 使用飞书官方 SDK 长连接接收消息事件
- 将飞书消息标准化为 `FeishuIncomingMessage`
- 下载飞书文件并写入本地 uploads
- 向 Agent 注册飞书群聊消息加载能力，由 `summarize_thread` 分支在路由完成后按需调用
- 转换成 `EntryInput`
- 调用 `AgentService.entry()`
- 将结果回复到飞书消息或群聊

## Web API 入口

当前 Web 层覆盖的主要能力：

- `GET /api/health`
- `GET /api/tools`
- `POST /api/tools/{name}/execute`
- `GET /api/notes`
- `POST /api/notes/{note_id}/graph-sync`
- `GET /api/notes/{note_id}/chunks`
- `DELETE /api/notes/{note_id}`
- `GET /api/digest`
- `GET /api/entry/stream`
- `POST /api/entry/upload`
- `GET /api/entry/runs`
- `POST /api/entry/runs/{run_id}/resume`
- `POST /api/debug/reset-database`

更完整的接口说明见 [api.md](../api.md)。

## 统一入口路径

### Web entry

标准 entry 路径：

```text
HTTP request
  -> web/routes/entry.py
  -> EntryInput
  -> AgentService.entry()
  -> AgentRuntime.execute_entry()
```

适用于：

- `GET /api/entry/stream`
- `POST /api/entry/upload`

### 飞书 entry

飞书消息路径：

```text
Feishu long connection event
  -> FeishuIncomingMessage
  -> optional file download
  -> EntryInput(source_platform="feishu")
  -> AgentService.entry()
  -> AgentRuntime.execute_entry()
     -> route_intent: summarize_thread 时按需加载飞书群聊消息
  -> Feishu reply
```

### CLI entry

CLI 当前统一进入 Agent 编排：

```text
CLI command
  -> EntryInput(source_platform="cli")
  -> AgentService.entry()
  -> AgentRuntime.execute_entry()
```

## 当前能力

- 已具备 FastAPI Web API
- 已具备前端静态资源托管
- 已具备同步问答、同步 entry 和 SSE entry
- `entry_stream` 的所有意图已统一进入 LangGraph entry pipeline；ask 回答通过 SSE 分块输出并纳入 checkpoint
- 已具备文件上传入口
- 已具备 tools、notes、digest、ask history 等管理接口
- 已具备 API Key 鉴权和 token bucket 限流
- 已具备 CORS 配置
- 已具备 CLI 本地入口
- 已具备飞书官方 SDK 长连接入口
- 已具备飞书事件短时去重
- 已具备飞书文件下载和群聊消息按需加载
- Web、飞书、CLI 和部分上传入口已经统一进入 `AgentService.entry()`

## 已知限制

### 1. 入口已基本统一

`entry()` 已成为统一的入口方向。`/api/digest` 作为独立摘要接口仍然保留，但 capture 和 ask 流程已整合进入 orchestration graph 的对应分支。

### 2. CLI 能力仍偏基础

CLI 当前只覆盖：

- `entry`

还没有覆盖：

- 上传文件
- 上传文件
- ask history 查询和删除
- graph sync

### 3. 飞书入口是后台线程处理，缺少更完整的任务状态反馈

飞书长连接需要快速接收事件，因此当前实现采用事件线程快速接收、后台线程处理。它可以完成回复，但还没有 Web 侧类似的结构化进度事件或步骤面板反馈。

### 4. 用户身份模型仍较轻量

Web 侧通过 API Key 映射用户，SSE 也支持 query 参数传 key；飞书侧可配置是否使用默认用户。当前适合个人或轻量多用户场景，更复杂的组织级权限、租户隔离和审计策略还需要继续增强。

### 5. 入口层和业务层边界还可以继续收敛

`entry_stream` 统一进入 LangGraph entry pipeline，以保证路由、事件、checkpoint 与恢复语义一致。后续可在 LangGraph 节点内引入原生流式事件，以同时保留 checkpoint 与实时 token 输出。

## 演进方向

- 进一步收敛 `digest` 等专项入口到 `entry()` 编排内
- 将流式问答、metadata、citation、plan events 和 execution trace 抽象成统一 `AgentEvent` schema
- 为 CLI 增加 history、upload 和 graph sync 能力
- 为飞书入口补更清晰的处理中/失败反馈
- 强化用户身份、权限、租户隔离和审计能力

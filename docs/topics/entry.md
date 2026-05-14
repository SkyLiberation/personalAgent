# 入口层说明

本文汇总当前项目入口层的职责划分、已有入口、统一调用路径、现有能力、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/web/api.py](../../src/personal_agent/web/api.py)、[src/personal_agent/feishu/service.py](../../src/personal_agent/feishu/service.py)、[src/personal_agent/cli/main.py](../../src/personal_agent/cli/main.py) 和 [src/personal_agent/agent/service.py](../../src/personal_agent/agent/service.py)。

## 设计目标

入口层的目标是让不同来源的请求都能进入同一个 Agent 运行时，而不是各入口各写一套业务逻辑：

- Web API 负责 HTTP 参数接收、鉴权、响应和 SSE 推送
- 前端工作台通过 Web API 使用采集、问答、图谱、记忆和确认能力
- CLI 提供最小本地操作入口
- 飞书长连接把 IM 事件转为内部 `EntryInput`
- `AgentService` 保持薄 facade，最终委托 `AgentRuntime` 执行

## 组件分层

### 1. `web/api.py`

代码位置：[api.py](../../src/personal_agent/web/api.py)

作用：

- 创建 FastAPI 应用
- 初始化 settings、logging、`CaptureService`、`AgentService` 和 `FeishuService`
- 注册 API 路由
- 启用可选 API Key 鉴权和限流
- 配置 CORS
- 在启动时拉起飞书长连接监听
- 托管构建后的前端静态资源

### 2. `AgentService`

代码位置：[service.py](../../src/personal_agent/agent/service.py)

作用：

- 作为入口层和 `AgentRuntime` 之间的薄 facade
- 负责装配 settings、store、graph store、ask history store 和 capture service
- 暴露稳定方法给 Web、CLI、飞书等入口调用

当前入口层主要通过这些方法进入运行时：

- `capture()`
- `ask()`
- `digest()`
- `entry()`
- `list_notes()`
- `list_tools()`
- `execute_tool()`
- `list_pending_actions()`
- `confirm_pending_action()`
- `reject_pending_action()`

### 3. `cli/main.py`

代码位置：[cli/main.py](../../src/personal_agent/cli/main.py)

作用：

- 提供本地命令行入口
- 每次命令构造 `AgentService`
- 调用 capture、ask、digest 等核心能力
- 输出 JSON 或文本结果

当前 CLI 命令：

- `capture`
- `ask`
- `digest`

### 4. `FeishuService`

代码位置：[service.py](../../src/personal_agent/feishu/service.py)

作用：

- 使用飞书官方 SDK 长连接接收消息事件
- 将飞书消息标准化为 `FeishuIncomingMessage`
- 下载飞书文件并写入本地 uploads
- 为群聊总结预取最近消息
- 转换成 `EntryInput`
- 调用 `AgentService.entry()`
- 将结果回复到飞书消息或群聊

## Web API 入口

当前 Web 层覆盖的主要能力：

- `GET /api/health`
- `GET /api/tools`
- `POST /api/tools/{name}/execute`
- `GET /api/notes`
- `GET /api/digest`
- `GET /api/ask-history`
- `POST /api/capture`
- `POST /api/capture/upload`
- `POST /api/ask`
- `GET /api/ask/stream`
- `GET /api/entry/stream`
- `POST /api/entry/upload`
- `POST /api/entry`
- `GET /api/ask-history/search`
- `DELETE /api/ask-history/{record_id}`
- `DELETE /api/ask-history/session/{session_id}`
- `POST /api/debug/reset-user-data`
- `GET /api/pending-actions`
- `POST /api/pending-actions/{action_id}/confirm`
- `POST /api/pending-actions/{action_id}/reject`

更完整的接口说明见 [api.md](../api.md)。

## 统一入口路径

### Web entry

标准 entry 路径：

```text
HTTP request
  -> web/api.py
  -> EntryInput
  -> AgentService.entry()
  -> AgentRuntime.execute_entry()
```

适用于：

- `POST /api/entry`
- `GET /api/entry/stream`
- `POST /api/entry/upload`

### 飞书 entry

飞书消息路径：

```text
Feishu long connection event
  -> FeishuIncomingMessage
  -> optional file download / thread prefetch
  -> EntryInput(source_platform="feishu")
  -> AgentService.entry()
  -> AgentRuntime.execute_entry()
  -> Feishu reply
```

### CLI direct calls

CLI 当前主要是直接调用 `AgentService` 的专项方法：

```text
CLI command
  -> AgentService.capture() / ask() / digest()
  -> AgentRuntime
```

CLI 还没有统一走 `entry()`。

## 当前能力

- 已具备 FastAPI Web API
- 已具备前端静态资源托管
- 已具备同步问答、同步 entry 和 SSE entry
- 已具备 `ask_stream` 和 `entry_stream` ask 路径的模型 token 流式输出
- `ask_stream` 已收敛为 `AgentRuntime.execute_ask_stream()` 公开 API，Web 层不再直接访问 runtime 私有方法
- `entry_stream` ask 路径已从伪分块升级为 `execute_ask_stream()` 真实 token 流，与 `ask_stream` 使用相同底层 API
- 已具备文件上传入口
- 已具备 tools、notes、digest、ask history、pending actions 等管理接口
- 已具备 API Key 鉴权和 token bucket 限流
- 已具备 CORS 配置
- 已具备 CLI 本地入口
- 已具备飞书官方 SDK 长连接入口
- 已具备飞书事件短时去重
- 已具备飞书文件下载和群聊消息预取
- Web、飞书和部分上传入口已经统一进入 `AgentService.entry()`

## 已知限制

### 1. 入口仍存在双轨

虽然 `entry()` 是统一入口方向，但当前仍保留不少专项 API：

- `/api/capture`
- `/api/ask`
- `/api/digest`
- CLI `capture / ask / digest`

这让兼容性更好，但也意味着有些能力会绕过 `execute_entry()` 中的 router、planner、plan panel 或 execution trace。

### 2. CLI 能力仍偏基础

CLI 当前只覆盖：

- `capture`
- `ask`
- `digest`

还没有覆盖：

- `entry`
- 上传文件
- pending action 确认/拒绝
- ask history 查询和删除
- graph sync

### 3. 飞书入口是后台线程处理，缺少更完整的任务状态反馈

飞书长连接需要快速接收事件，因此当前实现采用事件线程快速接收、后台线程处理。它可以完成回复，但还没有 Web 侧类似的结构化进度事件或计划面板反馈。

### 4. 用户身份模型仍较轻量

Web 侧通过 API Key 映射用户，SSE 也支持 query 参数传 key；飞书侧可配置是否使用默认用户。当前适合个人或轻量多用户场景，更复杂的组织级权限、租户隔离和审计策略还需要继续增强。

### 5. 入口层和业务层边界还可以继续收敛

`ask_stream`、`entry_stream` ask 路径已收敛为 `AgentRuntime.execute_ask_stream()` 公开 API。该公开 API 封装了图谱/本地/网络检索、prompt 构建、token 流和 turn 记录，Web 层已不再直接访问 runtime 私有方法。后续可将更多专项能力（capture、digest 等）以类似方式收敛，并抽象统一的 `AgentEvent` 模型。

## 演进方向

- 将更多专项入口逐步收敛到 `entry()`，减少双轨执行
- 将流式问答、metadata、citation、plan events 和 execution trace 抽象成统一 `AgentEvent` schema
- 为 CLI 增加 `entry`、pending action、history 和 upload 能力
- 为飞书入口补更清晰的处理中/失败反馈
- 强化用户身份、权限、租户隔离和审计能力

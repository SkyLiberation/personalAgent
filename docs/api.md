# 后端接口

主要接口定义位于 [api.py](../src/personal_agent/web/api.py)。

## `GET /api/health`

返回服务状态、Graphiti 配置状态，以及问答历史存储是否可用。

说明：

- `graphiti.configured=true` 只表示配置项齐全
- Neo4j 是否真正可连，需要结合运行日志或实际问答表现判断

示例响应：

```json
{
  "status": "ok",
  "graphiti": {
    "enabled": true,
    "configured": true,
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "embedding_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "embedding_model": "text-embedding-v4"
  },
  "ask_history": {
    "configured": true
  }
}
```

## `GET /api/notes`

返回指定用户的本地笔记列表。

查询参数：

- `user_id`

## `GET /api/digest`

返回最近笔记和到期复习任务摘要。

查询参数：

- `user_id`

## `GET /api/ask-history`

返回指定用户的问答历史。

查询参数：

- `user_id`
- `limit`
- `session_id`

说明：

- 传入 `session_id` 时，只返回该会话下的历史
- 不传 `session_id` 时，返回该用户最近的全量历史

示例响应：

```json
{
  "items": [
    {
      "id": "0f0b8fe7-3e4d-4b95-8bb5-2ab4e6f0c99a",
      "user_id": "default",
      "session_id": "11dd2242-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "question": "支付系统重构项目第一阶段方案包括什么？",
      "answer": "第一阶段方案主要围绕拆分核心链路、隔离高风险模块以及补齐监控展开。",
      "citations": [],
      "graph_enabled": true,
      "created_at": "2026-05-08T15:10:00.000000Z"
    }
  ]
}
```

## `POST /api/capture`

用于文本或网页链接采集。

请求体：

```json
{
  "text": "Bob 在搜索系统升级项目里决定先上 BM25 + 向量召回",
  "source_type": "text",
  "user_id": "default"
}
```

或：

```json
{
  "text": "https://example.com/article",
  "source_type": "link",
  "user_id": "default"
}
```

说明：

- `source_type=text` 时，直接采集文本
- `source_type=link` 时，会先抓取网页正文，再进入 capture 流程

## `GET /api/uploads/conflict`

检查上传文件名是否已存在。

查询参数：

- `filename`

## `POST /api/capture/upload`

使用 `multipart/form-data` 上传文件。

表单字段：

- `file`
- `user_id`
- `overwrite`

说明：

- 文本类文件会优先提取正文后进入 capture
- PDF 会优先提取文本后进入 capture
- 图片、音频等文件当前先保存为元信息笔记
- 上传接口会先返回本地 capture 结果
- 如果 Graphiti 已配置，图谱同步会在后台继续执行
- 返回的 `note.graph_sync_status` 初始通常为 `pending`
- 后续可通过 `GET /api/notes` 观察是否变为 `synced` 或 `failed`

## `POST /api/notes/{note_id}/graph-sync`

手动重试某条笔记的图谱同步。

行为：

- 先把笔记状态置为 `pending`
- 然后在后台执行图谱同步

示例响应：

```json
{
  "note": {
    "id": "76ac8451-3c16-4259-80d8-256a072e0304",
    "graph_sync_status": "pending"
  },
  "queued": true
}
```

## `POST /api/ask`

用于普通问答。

请求体：

```json
{
  "question": "搜索系统升级项目里，Bob 先决定采用什么方案？",
  "user_id": "default",
  "session_id": "11dd2242-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

说明：

- 后端优先尝试图谱问答；当 Neo4j 不可达或 Graphiti 不可用时，会快速回退到本地问答链
- 同一 `session_id` 下会自动携带最近对话上下文，支持多轮问答
- 如果配置了 `Postgres`，历史会持久化到 `ask_history`
- 即使没有 `Postgres`，本地仍会写入 `data/conversations.json`

## `GET /api/ask/stream`

基于 `SSE` 返回实时问答结果。

查询参数：

- `question`
- `user_id`
- `session_id`

事件类型：

- `status`
- `metadata`
- `answer_delta`
- `done`

说明：

- 当前 SSE 仍然是服务端按段推送已有回答
- 不是直接透传上游模型 token 流

## `POST /api/debug/reset-user-data`

用于快速清空当前用户调试数据。

请求体：

```json
{
  "user_id": "default"
}
```

会清理：

- `data/notes.json` 中该用户笔记
- `data/reviews.json` 中关联复习任务
- `data/conversations.json` 中该用户会话
- `data/uploads/` 中该用户笔记引用到的上传源文件
- `Postgres.ask_history` 中该用户历史
- Graphiti / Neo4j 中该用户对应的图谱分组数据

示例响应：

```json
{
  "user_id": "default",
  "deleted_notes": 12,
  "deleted_reviews": 12,
  "deleted_conversations": 8,
  "deleted_upload_files": 4,
  "deleted_ask_history": 8,
  "deleted_graph_episodes": 12
}
```

## `GET /api/tools`

返回当前所有已注册的工具及其描述。

示例响应：

```json
[
  {"name": "capture_url", "description": "抓取指定网页的正文内容，返回提取后的纯文本。"},
  {"name": "capture_upload", "description": "解析上传的文件（支持 PDF、文本文件），返回提取后的正文内容。"},
  {"name": "graph_search", "description": "在个人知识图谱中搜索与问题相关的实体、关系和笔记..."}
]
```

---

## `POST /api/tools/{name}/execute`

执行指定名称的工具。

请求体：

```json
{
  "kwargs": {
    "url": "https://example.com/article"
  }
}
```

示例响应：

```json
{
  "ok": true,
  "data": {"url": "https://example.com/article", "text": "..."},
  "error": null
}
```

可用工具：

- `capture_url` — 入参：`url` (string)
- `capture_upload` — 入参：`file_path` (string), `filename` (string), `content_type` (string, 可选)
- `graph_search` — 入参：`question` (string), `user_id` (string, 可选, 默认 "default")

---

## `POST /api/integrations/feishu/webhook`

用于接收飞书 HTTP 事件订阅回调。

说明：

- 当前项目默认推荐使用“长连接接收事件”，因此这个接口主要作为 webhook 模式兼容入口保留
- `url_verification` 会直接原样返回 `challenge`
- 文本消息会先进入统一入口路由 graph，再分流到 `capture` 或 `ask`
- 当前已支持：
  - 文本记录路由到 `capture_text`
  - 含链接消息路由到 `capture_link`
  - 普通问题路由到 `ask`
- `file` 消息会先识别成 `capture_file`，但文件下载与正文提取还没有接上
- 群聊总结意图会先识别成 `summarize_thread`，但消息回溯还未实现

部署时需要配合环境变量：

- `PERSONAL_AGENT_FEISHU_ENABLED`
- `FEISHU_VERIFICATION_TOKEN`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

## 飞书长连接

当前默认飞书接入方式不是 HTTP webhook，而是飞书官方 SDK 长连接。

行为说明：

- FastAPI 启动时会自动调用飞书长连接监听器
- 已订阅 `im.message.receive_v1`
- 收到事件后，会把消息转成内部 `FeishuIncomingMessage`
- 再复用统一入口 `AgentService.entry(...)`
- 最终优先使用 `message_id` 回复原消息

日志关键字：

- `Feishu long connection startup requested`
- `Feishu long connection thread started`
- `connected to wss://...`
- `Feishu long connection event accepted`
- `Feishu reply sent`

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
    "configured": true,
    "base_url": "https://api.moonshot.cn/v1",
    "model": "kimi-k2.5",
    "embedding_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "embedding_model": "text-embedding-v4",
    "search_strategy": "hybrid_rrf"
  },
  "ask_history": {
    "configured": true
  }
}
```

## `GET /api/notes`

返回指定用户的知识笔记列表。

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
      "created_at": "2026-05-08T15:10:00.000000Z"
    }
  ]
}
```

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

## `POST /api/debug/reset-database`

用于开发调试时清空所有持久化数据。该操作影响所有用户且不可撤销。

会清理：

- `PERSONAL_AGENT_POSTGRES_URL` 指向的当前 schema 中全部普通表数据，包括业务表与 LangGraph checkpoint 表
- `data/uploads/` 中全部上传源文件
- 配置的 Graphiti / Neo4j 数据库中的全部节点和关系

`checkpoint_migrations` 同样会被清空；操作完成后服务会立即重新写入 LangGraph 所需的迁移版本记录。

示例响应：

```json
{
  "deleted_notes": 12,
  "deleted_reviews": 12,
  "deleted_upload_files": 4,
  "deleted_ask_history": 8,
  "deleted_graph_nodes": 12,
  "deleted_pending_actions": 3,
  "deleted_cross_session_artifacts": 6,
  "deleted_checkpoints": 24,
  "deleted_checkpoint_blobs": 35,
  "deleted_checkpoint_writes": 90,
  "deleted_checkpoint_migrations": 10,
  "truncated_postgres_tables": 9,
  "deleted_postgres_rows": 200
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
- `capture_text` — 入参：`text` (string), `user_id` (string, 可选, 默认 "default")
- `delete_note` — 入参：`note_id` (string), `user_id` (string, 可选), `confirmed` (bool), `action_id` (string, 确认时提供), `token` (string, 确认时提供)

---

## `GET /api/pending-actions`

返回指定用户的待处理操作列表（HITL 确认队列）。

查询参数：

- `user_id`
- `status`（可选：`pending` / `confirmed` / `rejected` / `expired` / `executed`）

示例响应：

```json
{
  "items": [
    {
      "id": "f3a2b1c4-...",
      "user_id": "default",
      "action_type": "delete_note",
      "target_id": "76ac8451-...",
      "title": "删除笔记「过时的会议记录」",
      "description": "将删除笔记「过时的会议记录」及其关联的复习卡片。",
      "status": "pending",
      "created_at": "2026-05-12T10:30:00",
      "expires_at": "2026-05-12T11:30:00",
      "resolved_at": null,
      "audit_log": [
        {"timestamp": "...", "event": "created", "actor": "system", "detail": "..."}
      ]
    }
  ]
}
```

## `POST /api/pending-actions/{action_id}/confirm`

确认执行某个待处理操作。

请求体：

```json
{
  "token": "a1b2c3d4",
  "user_id": "default"
}
```

说明：

- 需要提供正确的 `token`（由创建 pending action 时返回）
- 过期或已处理的 action 会返回 404

## `POST /api/pending-actions/{action_id}/reject`

拒绝某个待处理操作。

请求体：

```json
{
  "user_id": "default",
  "reason": "这不是我要删除的笔记"
}
```

---

## 入口执行（Entry）

统一的入口接口，支持文本、链接、文件等多类型输入，由 Agent 自动路由到合适的处理链路。

### `GET /api/entry/stream`

SSE 流式入口执行，逐步返回 intent 分类、计划步骤、执行进度和最终结果。

LangGraph HITL 或补充信息场景下会返回：

```text
event: confirmation_required
data: {
  "run_id": "...",
  "pending_confirmation": {
    "step_id": "...",
    "action_type": "delete_note",
    "action_id": "...",
    "token": "...",
    "note_id": "...",
    "title": "...",
    "summary": "...",
    "message": "..."
  }
}

event: done
data: {
  "waiting_confirmation": true,
  "run_id": "...",
  "reply": "..."
}
```

当 router 判断输入缺少必要信息时，`pending_confirmation` 的澄清 payload 形态如下；前端可展示 `message`、`missing_information` 与 `options`，再使用 resume API 提交用户补充内容：

```json
{
  "kind": "clarification_required",
  "action_type": "clarify_entry",
  "step_id": "clarify_entry",
  "title": "需要补充信息",
  "message": "请补充你希望我处理的具体内容。",
  "summary": "输入缺少明确目标。",
  "missing_information": ["具体目标或待处理内容"],
  "options": [
    {"id": "capture", "label": "记录内容", "prompt": "请补充要写入知识库的具体内容。"},
    {"id": "ask", "label": "提出问题", "prompt": "请补充你想查询或追问的问题。"}
  ]
}
```

### `POST /api/entry/upload`

上传文件并触发入口处理。表单字段：`file`、`user_id`、`session_id`、`text`（可选）。

### `GET /api/entry/runs`

查询最近的 LangGraph run 快照列表。

查询参数：

- `user_id`（可选）：过滤用户
- `limit`（默认 50）

响应：

```json
{
  "items": [
    {
      "run_id": "run_xxx",
      "thread_id": "user:session:run_xxx",
      "user_id": "default",
      "session_id": "default",
      "status": "waiting_confirmation",
      "intent": "delete_knowledge",
      "entry_text": "删除过期笔记",
      "plan_steps": [],
      "execution_trace": [],
      "answer": null,
      "errors": [],
      "created_at": "2026-05-19T00:00:00",
      "updated_at": "2026-05-19T00:00:01",
      "last_event": null
    }
  ]
}
```

### `POST /api/entry/runs/{run_id}/resume`

恢复处于 `waiting_confirmation` 状态的 LangGraph run。

请求体：

```json
{
  "decision": "confirm",
  "user_id": "default",
  "text": "",
  "option_id": ""
}
```

字段说明：

- `decision`：必须是 `confirm`、`reject` 或 `clarify`。
- `user_id`：当前用户，省略时使用默认用户解析逻辑。
- `text`：`decision="clarify"` 时必填，表示用户补充的内容。
- `option_id`：可选，表示补充类型，例如 `capture`、`ask`、`summarize`、`action`。

行为：

- 后端会先通过 `run_id` 查询 run snapshot。
- 如果 run 不存在，返回 `404 Run not found.`。
- 如果 run 不是 `waiting_confirmation`，返回 `400`。
- 校验通过后，后端使用 snapshot 中的 `thread_id` 恢复 LangGraph run。
- 返回恢复后的 `EntryResponse`。

---

## 飞书长连接

当前飞书接入方式使用飞书官方 SDK 长连接（非 HTTP webhook）。

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

# 后端接口

主要接口定义位于 [api.py](../src/personal_agent/web/api.py)。

## `GET /api/health`

返回服务状态以及 Graphiti 配置状态。

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
  }
}
```

## `GET /api/notes`

返回指定用户的知识笔记列表。

查询参数：

- `user_id`
- `flat`（bool，默认 false）：为 true 时同时返回 chunk notes

## `DELETE /api/notes/{note_id}`

软删除指定笔记。删除会生成 `knowledge_delete_snapshots` 快照，默认查询和检索不再返回该 note；如果目标是 parent note，会一并软删除其子 chunk。

查询参数：

- `user_id`
- `delete_reason`（string，可选）：删除原因，写入删除快照和删除元数据
- `cascade`（bool，保留参数）：当前 parent note 删除会根据实际 chunk 自动级联

响应：

```json
{"ok": true, "deleted_note_id": "76ac8451-...", "snapshot_id": "kdel-..."}
```

## `POST /api/memory/notes/{note_id}/restore`

按 note id 或指定删除快照恢复笔记。恢复会通过 `restore_note` 工具进入 ToolGateway、PolicyEngine、幂等账本和工具审计。

请求体：

```json
{
  "user_id": "default",
  "snapshot_id": "kdel-...",
  "idempotency_key": "restore:kdel-..."
}
```

## `POST /api/memory/delete-snapshots/{snapshot_id}/restore`

按删除快照恢复 note、子 chunk 和 review card。请求体同上，`snapshot_id` 可省略，因为路径参数已指定。

## `GET /api/notes/{note_id}/chunks`

返回指定 parent note 的所有子 chunk notes。

## `GET /api/digest`

返回最近笔记和到期复习任务摘要。

查询参数：

- `user_id`

## Review Digest 管理接口

用于管理“复习 Digest -> 飞书”的主动触达订阅。普通 API key 只能管理自身 `user_id` 的订阅；admin key 可以指定 `user_id`。

### `GET /api/review/digest/subscriptions`

查询 Digest 订阅。

查询参数：

- `enabled_only`（bool，默认 false）：只返回启用订阅

### `POST /api/review/digest/subscriptions`

创建或覆盖 Digest 订阅。

请求体：

```json
{
  "id": "morning-default",
  "channel": "feishu",
  "target_type": "chat_id",
  "target_id": "oc_xxx",
  "schedule_time": "09:00",
  "timezone": "Asia/Shanghai",
  "enabled": true
}
```

### `PATCH /api/review/digest/subscriptions/{subscription_id}`

更新订阅。可更新 `channel`、`target_type`、`target_id`、`schedule_time`、`timezone`、`enabled`；非 admin 请求不能改 `user_id`。

### `POST /api/review/digest/subscriptions/{subscription_id}/send-now`

立即为该订阅生成并投递当天 Digest。后端会写入 `digest_deliveries`，并按 `subscription_id + digest_date` 做幂等；同一天重复调用会返回 `skipped=true` 和同一个 `delivery_id`。

### `GET /api/review/digest/deliveries`

查询 Digest 投递记录。

查询参数：

- `subscription_id`
- `user_id`（仅 admin 可指定）
- `limit`（默认 50）

## `POST /api/notes/{note_id}/graph-sync`

手动重试某条笔记的图谱同步。

行为：

- 先把笔记状态置为 `pending`
- 然后同步执行图谱同步（含重试/退避）

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

用于开发调试时清空持久化调试数据。该操作影响所有用户且不可撤销。

会清理：

- `PERSONAL_AGENT_POSTGRES_URL` 指向的当前 schema 中全部普通表数据，包括业务表与 LangGraph checkpoint 表
- `data/uploads/` 中全部上传源文件
- 配置的 Graphiti / Neo4j 数据库中除 eval manifest 缓存分组外的节点和关系

Neo4j 清理会读取 `evals/**/*manifest*.json` 中的 Graphiti eval manifest；当其中的
`graphiti_group_prefix` 与当前配置匹配且存在 `episode_to_note_id` 时，该 `user_id`
对应的 Graphiti `group_id` 会被保留，以便 `--reuse-graphiti` 渐进式评估缓存继续复用。

`checkpoint_migrations` 同样会被清空；操作完成后服务会立即重新写入 LangGraph 所需的迁移版本记录。

示例响应：

```json
{
  "deleted_notes": 12,
  "deleted_reviews": 12,
  "deleted_upload_files": 4,
  "deleted_graph_nodes": 12,
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
- `web_search` — 入参：`question` (string), `user_id` (string, 可选)
- `capture_text` — 入参：`text` (string), `user_id` (string, 可选, 默认 "default")
- `delete_note` — 入参：`note_id` (string), `user_id` (string, 可选), `confirmed` (bool), `idempotency_key` (string), `delete_reason` (string, 可选)
- `restore_note` — 入参：`note_id` (string, 可选), `snapshot_id` (string, 可选), `user_id` (string, 可选), `confirmed` (bool), `idempotency_key` (string)

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
      "steps": [],
      "execution_trace": [],
      "answer": null,
      "pending_confirmation": null,
      "confirmation_decision": null,
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

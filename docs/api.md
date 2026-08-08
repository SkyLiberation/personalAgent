# 后端接口

主要接口定义位于
[adapters/web/routes/](../src/personal_agent/adapters/web/routes)，应用装配位于
[adapters/web/api.py](../src/personal_agent/adapters/web/api.py)。

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

## Durable Investigation Project

该资源只用于“路径会根据 Observation 动态变化，并且需要跨进程、用户轮次或审批边界维持
交付契约”的调查任务。普通用户可直接从 Conversation 描述结果和持续性要求；明确知道业务动作的
UI、自动化与集成方可使用下列资源 API。两种入口都调用同一 Project Application Service。

### `POST /api/investigation-projects`

持久化 immutable Project definition 和第一版 UserRequirement 后返回 `202`。Planner 和
Provider 不在请求内执行。请求必须包含 `tenant_id`、`owner_id`、`user_id`、`title`、
`goal`、非空 `requirements`、`budget` 和 `idempotency_key`。鉴权启用时 tenant/user 必须与
API key 的 typed principal 一致。

### `GET /api/investigation-projects/{project_id}`

按 tenant/personal knowledge/user scope 返回只读 projection。查询不会调用模型、重新规划或推进 worker。

### Project 控制入口

- `POST .../{project_id}/steering`：基于 expected plan version 修改尚未冻结的工作；
- `POST .../{project_id}/commands/{command_id}/decision`：提交绑定 AuthorizationDigest 的审批；
- `POST .../{project_id}/pause`：记录 `user_paused`；
- `POST .../{project_id}/resume`：只允许恢复 `user_paused`，不能绕过预算、能力、审批或修复暂停；
- `POST .../{project_id}/cancel`：取消关联 child，并 quarantine 终态后的 late Artifact。

Project worker 使用 `personal-agent worker --queue investigation` 消费 durable queue。

## `GET /api/notes`

返回指定用户的知识笔记列表。

查询参数：

- `user_id`
- `flat`（bool，默认 false）：为 true 时同时返回 chunk notes

## Knowledge Lifecycle

删除和恢复使用固定的两阶段 Application Use Case，不提供直接 DELETE 或 snapshot restore 入口。
Conversation 可通过 `prepare_knowledge_delete` 准备同一种 delete command，但确认和执行仍使用本节
canonical lifecycle API；Conversation 不复制 operation 或 Receipt。

### `POST /api/notes/{note_id}/delete-commands`

prepare 一个删除操作。此调用只持久化 immutable command，不修改 Knowledge
Item/Claim。

```json
{
  "user_id": "default",
  "owner_id": "default",
  "reason": "内容已过期",
  "idempotency_key": "delete:note-123"
}
```

响应包含 `command`、`status=awaiting_confirmation` 和 `receipt=null`。
`command.command_digest` 是 canonical command payload 的一致性指纹。

### `POST /api/knowledge-delete-commands/{command_id}/decision`

```json
{
  "user_id": "default",
  "decision": "confirm",
  "command_digest": "<64-char sha256>",
  "confirmation_ref": "ui-confirmation-123"
}
```

`confirm` 成功后返回 `status=executed` 与唯一 Receipt；相同 command replay
返回同一 Receipt。`reject` 不要求 `confirmation_ref`，且被拒绝的 command
不能再次执行。错误身份、scope 或 digest 均 fail closed。

### `GET /api/knowledge-delete-commands/{command_id}`

按当前用户读取持久化 operation，供重启后恢复确认页面。

### `POST /api/knowledge-delete-commands/{delete_command_id}/restore-commands`

为一个已执行 delete command prepare restore。请求体字段与 delete prepare
相同，`idempotency_key` 应属于 restore 操作。

### `POST /api/knowledge-restore-commands/{command_id}/decision`

请求体与 delete decision 相同。确认后依据 delete receipt 中的 previous
Item/Claim states 恢复，并返回唯一 restore Receipt。

### `GET /api/knowledge-restore-commands/{command_id}`

按当前用户读取持久化 restore operation。

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

### `GET /api/review/cards`

查询复习卡。

查询参数：

- `user_id`（仅 admin 可指定）
- `due_only`（bool，默认 false）：只返回已到期复习卡

### `POST /api/review/cards/{review_card_id}/feedback`

提交复习反馈，并更新该卡片的下一次复习时间。请求体：

```json
{
  "outcome": "remembered"
}
```

`outcome` 可为：

- `remembered`：记得，扩大复习间隔
- `forgotten`：忘了，明天再复习
- `later`：稍后，明天重新提醒

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
鉴权启用时仅管理员 API key 可调用。

会清理：

- `PERSONAL_AGENT_POSTGRES_URL` 指向的当前 schema 中全部普通表数据，包括业务表与可能残留的
  历史 LangGraph checkpoint 表；后者不是当前 Conversation 真源
- `data/uploads/` 中全部上传源文件
- 配置的 Graphiti / Neo4j 数据库中除 eval manifest 缓存分组外的节点和关系

Neo4j 清理会读取 `evals/**/*manifest*.json` 中的 Graphiti eval manifest；当其中的
`graphiti_group_prefix` 与当前配置匹配且存在 `episode_to_note_id` 时，该 `user_id`
对应的 Graphiti `group_id` 会被保留，以便 `--reuse-graphiti` 渐进式评估缓存继续复用。

如果 schema 仍含历史 `checkpoint_migrations`，它也会被清空；该运维行为不表示当前主链使用
LangGraph checkpoint。

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

---

## Conversation

普通用户目标使用 canonical Conversation contract。模型从当前 EffectiveCapabilities 选择粗粒度
业务能力；文件摄取等有独立交互的产品功能仍可进入明确 Personal Knowledge API，不由关键词 Router 猜测。

### `POST /api/conversation/turn`

请求示例：

```json
{
  "conversation_id": "personal knowledge-1",
  "messages": [
    {"role": "user", "content": "总结我已经保存的知识"}
  ],
  "interaction_run_ref": null,
  "user_id": "default"
}
```

响应由 `ConversationTurnView` 定义，包含 `interaction_run_ref`、`conversation_id`、
`disposition` 和一条 assistant `message`。保存或删除需要确认时返回 `pending_confirmation`；
durable 调查创建后返回
`project_reference={project_id,tenant_id,owner_id,user_id,state,title,goal}`，供客户端只读查询
原 Project projection。`disposition` 可能为
`answer`、`clarification_required`、`confirmation_required`、`background_started`、`limitation`
或 `failed`。

当前 goal-entry capability：

- `list_personal_knowledge`：读取当前 principal 的 active/conflicted canonical KnowledgeItem 引用；
- `prepare_conversation_knowledge_save`：冻结 exact user span；
- `prepare_knowledge_delete`：准备 lifecycle delete command，确认前零副作用；
- `start_durable_investigation`：创建 Project 并返回引用，不把创建视为报告完成。

### `GET /api/entry/stream`

SSE 是 canonical Conversation loop 的传输适配器。它先返回处理状态，再流式返回 answer delta，
最终 `done` 事件包含 `disposition`、`interaction_run_ref`、`conversation_id`，以及适用时的
`pending_confirmation` 或 `project_reference`。前端使用 ProjectReference 查询 projection 并提供
刷新、暂停和恢复控件，不从 UI 推进模型。该入口不再创建
Task/GoalGraph，也不提供旧计划步骤和 checkpoint snapshot。

需要补充信息时会返回：

```text
event: done
data: {
  "reply": "...",
  "answer": "...",
  "disposition": "answer | clarification_required | limitation | failed",
  "interaction_run_ref": "...",
  "conversation_id": "..."
}
```

缺少必要用户信息时，`ConversationService` 返回
`disposition="clarification_required"`，`reply/answer` 中包含一个具体问题；客户端使用下一次
Conversation 请求提交补充信息。旧 `pending_confirmation/clarify_entry/step_id/options` 形态不再
属于该入口。

### Conversation trace 与知识保存确认

- `GET /api/conversation/runs/{interaction_run_ref}` 读取已提交的 Interaction trace；
- `POST /api/conversation/runs/{interaction_run_ref}/knowledge-save-decision` 接受或拒绝已冻结的
  exact-span 保存 Command，确认必须绑定 `owner_id`、`command_digest` 和
  `confirmation_ref`。

旧 `POST /api/entry/upload`、`GET /api/entry/runs` 和
`POST /api/entry/runs/{run_id}/resume` 已删除并返回 `404`。文件上传使用
`POST /api/knowledge/ingest-upload`；Conversation 恢复事实由 Interaction journal 与公开
`interaction_run_ref` 合约拥有，不再暴露 LangGraph run snapshot。

---

## 飞书长连接

当前飞书接入方式使用飞书官方 SDK 长连接（非 HTTP webhook）。

行为说明：

- FastAPI 启动时会自动调用飞书长连接监听器
- 已订阅 `im.message.receive_v1`
- 收到事件后，会把消息转成内部 `FeishuIncomingMessage`
- 文本对话调用 `AgentService.converse(...)`，文件和固定业务命令调用对应 Application use case
- 最终优先使用 `message_id` 回复原消息

日志关键字：

- `Feishu long connection startup requested`
- `Feishu long connection thread started`
- `connected to wss://...`
- `Feishu long connection event accepted`
- `Feishu reply sent`

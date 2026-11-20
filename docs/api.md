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

## `GET /api/notes`

返回指定用户的 active `KnowledgeItem` 列表，当前最多 200 条。

查询参数：

- `user_id`
- `flat`（bool，默认 false）：当前保留该参数，但不改变返回内容

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
  "confirmation_ref": "ui-confirmation-123"
}
```

`confirm` 成功后返回 `status=executed` 与唯一 Receipt；相同 command replay
返回同一 Receipt。`reject` 不要求 `confirmation_ref`，且被拒绝的 command
不能再次执行。客户端用 path 中的 `command_id` 选择待确认操作；服务端按 authenticated principal、
scope、状态和 `confirmation_ref` fail closed，并从 immutable Command 读取内部 `command_digest`，不接受
客户端回传或覆盖 digest。

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

将指定知识项的 `EvidenceSpan` 转成 `KnowledgeNote` 兼容视图返回；这些视图来自证据片段，不能作为独立知识事实写回。

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
    "graph_sync": {"status": "synced"}
  },
  "queued": false
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

返回当前已注册工具的名称、描述与 `exposure`。注册清单不代表普通 Conversation 的可调用清单；曝光与准入规则见[工具专题](topics/tools.md#注册与曝光)。

示例响应：

```json
[
  {"name": "capture_url", "description": "抓取网页正文", "exposure": "workflow_activity"},
  {"name": "graph_search", "description": "搜索个人知识图谱", "exposure": "public_agent"}
]
```

---

## `POST /api/tools/{name}/execute`

执行指定名称的工具，仍经过 Gateway 与 Policy。请求严格校验字段；鉴权启用时，请求的 `tenant_id`、`user_id` 必须与已认证身份一致。

请求体：

```json
{
  "tenant_id": "default",
  "user_id": "default",
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

工具集合由运行时注册表返回，参数由各工具的 `ArgsSchema` 校验。例如 `web_search` 接受 `query` 与可选 `limit`，`graph_search` 接受 `question` 与 `user_id`。完整契约与代码入口见[工具专题](topics/tools.md)。

---

## Conversation

普通对话按认证主体和 `session_id` 接续。请求只提交本轮用户原话。历史来源见 [Session、Turn 与 Step 生命周期](optimization/to_verify/conversation-loop-boundaries.md#320-sessionturn-与-step-生命周期)。

普通用户目标使用 canonical Conversation contract。模型从当前 EffectiveCapabilities 选择粗粒度
业务能力；文件摄取等有独立交互的产品功能仍可进入明确 Personal Knowledge API，不由关键词 Router 猜测。

### `POST /api/conversation/turns`

请求示例：

```json
{
  "session_id": "personal-knowledge-1",
  "text": "总结我已经保存的知识",
  "create_session": true,
  "client_request_id": "question-1",
  "user_id": "default"
}
```

Web 响应由 `ConversationTurnResponse` 定义，包含 `turn_id`、`session_id`、
`disposition` 和一条 assistant `message`。需要确认的知识或工作区动作返回 `pending_confirmation`。
`disposition` 可能为 `answer`、`clarification_required`、`confirmation_required`、`plan_ready`、
`limitation` 或 `failed`。明确要求本次响应后继续运行并稍后查询或调整时，当前返回
`limitation`，不会创建后台任务。

首轮提交 `create_session: true`。续聊沿用 `session_id`，省略 `create_session`，提交新的 `client_request_id` 和本轮 `text`。会话不存在或不属于当前主体时返回 404。重复创建已有会话返回 409。

同一主体在同一 Session 重用 `client_request_id` 时，原话、按序原件引用和创建意图必须一致，差异返回 409。重复提交返回原 Turn 的交付结果或确认事项。暂时无法交付时返回 202、`disposition="pending"` 和原 `turn_id`。末轮阻止下一轮提交时返回 409，已登记时 `detail.turn_id` 给出原轮次身份。处理原轮次后可重试本次新输入。

用户要求先审阅时，`plan_ready` 返回待审 `working_plan`；恢复原 Turn 可取得原待审计划。请求继续接受 `interaction_mode` 字段，清单是否暂停由用户要求和计划工具的 `wait_for_user` 决定。[工作清单工具](context/local-tools.md#5-conversation-直接声明的本地动作)

Conversation Runtime 失败的 REST `detail` 为安全对象，含 message、reason_code、failure_stage、retryable；可得时附 provider_status_code／provider_response_complete。模型输出协议无效投影本地 502，请求超时 504，实际临时过载 503，本地实现或持久化异常 500；明确输入校验、权限和冲突仍沿各自契约。**本地 HTTP 状态不是上游实际状态。** 例如完整模型响应无法按当前输出协议消费时：

```json
{
  "detail": {
    "message": "模型输出不符合当前协议，无法完成本次请求。",
    "reason_code": "structured_output_invalid",
    "failure_stage": "provider_structured_decode",
    "retryable": false,
    "provider_response_complete": true
  }
}
```

缺少上游状态时省略该字段，不以本地 502 代填。此投影不含模型原文、内部异常栈或密钥，依据见 [ADR 0045](adr/0045-native-intent-loop-and-recorded-model-output.md)。

请求可附 `input_artifact_refs`（默认为空），仅接受当前认证主体拥有的确切 Artifact 引用。首次调用前校验，恢复使用该 Turn 已冻结的消息与引用。

响应的 `resources` 每项为 `{resource, download_url}`：`resource` 是原 Artifact 元数据，`download_url` 是正式下载路径，上传响应复用同一包装。内部 `ConversationTurnView` 保持原元数据类型，文件引用不包含宿主路径。鉴权关闭且主体非默认用户时，URL 带编码后的 `user_id`；鉴权开启时由请求凭据确定主体。

研究实验只在许可部署、主体和开发原件绑定后启用，实现及验收状态见[研究 Spec](optimization/to_verify/knowledge-decision-delivery.md)。

知识读取与生命周期能力的部分入口：

- `list_personal_knowledge`：读取当前 principal 的 active/conflicted canonical KnowledgeItem 引用；
- `prepare_conversation_knowledge_save`：冻结 exact user span；
- `prepare_knowledge_delete`：准备 lifecycle delete command，确认前零副作用。

### `POST /api/conversation/turns/{turn_id}/workspace-changes/decision`

工作区会话在适用部署中返回 `kind=workspace_changes`、`command_digest` 和有序的 `changes`。已认证用户提交原 `command_digest` 和 `decision`（`approve` 或 `reject`），服务端从 Turn 定位所属 Session。响应包含摘要、整体状态和按批准顺序记录的执行结果。相同决定重复提交返回原回执，并发处理或决定冲突时返回 409，其他主体或错误摘要返回 404。取得回执后调用原 Turn 的恢复入口。执行成功时模型消费实际回执并继续交付，拒绝或结果未知时展示对应状态。

配置入口允许名单时，对话、SSE 和直接工具 API 的未授权请求在执行前返回 403。认证与工作区部署配置见 [MCP 接入 Spec](mcpDesign/README.md#523-工作区变更确认与接续)。

### SSE 响应

对同一个 `POST /api/conversation/turns` 请求发送 `Accept: text/event-stream`，通过常规 API Key 或 Bearer 头鉴权。校验失败且未登记时返回常规 HTTP 错误。登记后，第一条 `status` 事件携带 `turn_id` 与 `session_id`。运行完成后发送 `answer_delta` 和 `done`，`done` 携带处置、身份及适用的待确认事项。答案分块来自已交付文本。

原轮次暂未交付时发送 `pending`。登记后的错误通过 `error` 发送，数据含 `status_code` 及安全 `detail`。连接断开时，可凭 `turn_id` 查询，或用同一请求键、原话、附件和创建意图重提。恢复运行使用原 Turn 的 `/resume`。

### Turn 查询、恢复与知识保存确认

- `GET /api/conversation/turns/{turn_id}` 读取当前主体拥有的已提交 Turn，包括主决策的
  `step_no`。该操作受 Web 入口权限和轮次归属约束。认证关闭且策略未限制主体的本地环境可用
  `user_id` 查询参数选择测试主体。跨作用域或未知 Turn 返回 `404`。
- `POST /api/conversation/turns/{turn_id}/resume` 恢复原 Turn，请求体只含可选的 `user_id`。服务端读取
  已冻结的消息、原件引用和执行绑定。正在执行时按会话锁返回冲突，已交付则返回原结果。
- `POST /api/conversation/turns/{turn_id}/knowledge-save-decision` 接受或拒绝已冻结的
  exact-span 保存 Command；路径中的 `turn_id` 与认证主体定位唯一
  operation，confirm 还必须提供 `confirmation_ref`。内部 digest 由服务端从 Command 读取。

### Artifact 原件与成果内容

`POST /api/artifacts/upload` 使用 multipart 的 `file`（认证关闭时可附 `user_id`）保存原件，返回 `resource` 元数据及 `download_url`，不摄入知识。

`GET /api/artifacts/{resource_id}/revisions/{revision}` 按当前认证主体恢复确切引用，校验原始字节摘要与长度后下载。缺资源或非 owner 返回 `404`，非法引用或完整性失败返回 `422`；下载返回已核验字节，不暴露存储路径。

旧 `POST /api/entry/upload`、`GET /api/entry/runs` 和
`POST /api/entry/runs/{run_id}/resume` 已删除并返回 `404`。文件上传使用
`POST /api/knowledge/ingest-upload`，原件上传使用上述 Artifact 入口；Conversation 恢复事实由 Interaction journal 与公开
`turn_id` 合约拥有，不再暴露 LangGraph run snapshot。

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

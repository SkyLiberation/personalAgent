# Review Digest 触达能力设计

## 设计立场

Review Digest 不应该被设计成“前端 Digest 页面加一个飞书发送按钮”，也不应该被设计成“用 cron 调现有接口”。它应该是个人知识 Agent 的一个独立能力域：系统根据长期记忆中的复习状态，周期性生成复习任务，并通过合适的触达渠道推给用户，再把用户反馈写回复习状态。

飞书是第一优先触达渠道，但不是能力边界本身。能力边界应抽象为：

```text
Review State
  -> Digest Generation
  -> Schedule / Subscription
  -> Delivery
  -> Feedback
  -> Review State Update
```

这条链路属于“复习与触达子系统”，不是 Web 前端、飞书入口、LangGraph entry 或普通聊天能力的附属物。

## 目标架构

目标形态：

```text
ReviewScheduler
  -> DigestSubscriptionRepository
  -> ReviewDigestUseCase
     -> ReviewRepository
     -> NoteRepository
     -> DigestComposer
     -> DigestFormatter
  -> DeliveryRouter
     -> FeishuDeliveryProvider
  -> DeliveryLedger

FeishuInboundCommand
  -> DigestCommandHandler
  -> ReviewDigestUseCase
  -> FeishuDeliveryProvider.reply()

FeishuInboundFeedback
  -> ReviewFeedbackHandler
  -> ReviewPolicy
  -> ReviewRepository.update_schedule()
```

这套设计把“什么时候推”“推什么”“推到哪里”“用户如何反馈”“状态如何更新”分开。每个部分可以独立测试、替换和演进。

## 能力边界

### Review State

复习状态是长期记忆的一部分，真源在 Postgres，而不是飞书消息或前端缓存。

核心对象：

```text
ReviewCard
  id
  user_id
  note_id
  prompt
  answer_hint
  due_at
  interval_days
  status
  last_reviewed_at
```

需要新增或补齐：

- 更新复习卡到期时间。
- 记录复习反馈历史。
- 查询某个用户的到期复习卡。
- 排除已删除 note 对应的复习卡。

建议抽象：

```text
ReviewRepository
  due_cards(user_id, now, limit)
  update_schedule(card_id, next_due_at, interval_days)
  record_feedback(card_id, outcome, source)
```

当前 `MemoryFacade.due_reviews()` 可以作为迁移来源，但长期不应让飞书层或调度层直接理解 `PostgresMemoryStore`。

### Digest Generation

Digest 生成负责把复习卡和最近知识组织成“今天值得回顾什么”。它不负责发送，也不负责定时。

核心输入：

- `user_id`
- `now`
- 到期复习卡
- 最近新增或最近更新的知识
- 用户偏好，例如数量、语言、是否包含答案提示

核心输出：

```text
ReviewDigest
  user_id
  generated_at
  recent_notes
  due_cards
  sections
  empty_reason
```

`ReviewDigest` 应该是结构化对象，而不是只有一段拼好的字符串。字符串是 formatter 的职责。

建议抽象：

```text
ReviewDigestUseCase.generate(user_id, now) -> ReviewDigest
DigestComposer.compose(notes, due_cards) -> ReviewDigest
DigestFormatter.to_feishu_text(digest) -> str
DigestFormatter.to_web_payload(digest) -> dict
```

当前 `digest_node()` 可以迁移为 `DigestComposer` 的初版实现；当前 `DigestResult.message` 可以由 `DigestFormatter` 生成。

### Schedule / Subscription

调度是业务能力，不应该只存在于部署层 crontab。cron、K8s CronJob、systemd timer 可以作为外部唤醒方式，但真正的调度语义应该在应用里：

- 谁订阅了 Digest。
- 推送到哪个 channel / target。
- 什么时候推。
- 用哪个 user_id 的记忆生成。
- 今天是否已经推送。
- 失败后是否重试。

核心对象：

```text
DigestSubscription
  id
  user_id
  channel              -- feishu
  target_type          -- chat_id / open_id
  target_id
  schedule_time        -- 09:00
  timezone
  weekdays
  enabled
  created_at
  updated_at
```

建议抽象：

```text
ReviewScheduler.tick(now)
  -> due subscriptions
  -> enqueue ReviewDigestJob

ReviewDigestJob(subscription_id, scheduled_for)
  -> generate digest
  -> deliver
  -> write ledger
```

部署层可以有两种触发方式：

- 应用内 scheduler 定时调用 `tick()`。
- 外部 cron / K8s CronJob 调用 `run_due_review_digest_jobs()`。

无论哪种方式，业务语义都必须收敛到 `ReviewScheduler` 和 `ReviewDigestJob`，不能散落在 crontab shell 脚本里。

### Delivery

触达层只负责把已经生成好的消息送到目标渠道。飞书是第一个 provider。

核心对象：

```text
DeliveryTarget
  channel
  target_type
  target_id

DeliveryMessage
  title
  text
  metadata

DeliveryResult
  ok
  provider_message_id
  error
```

建议抽象：

```text
DeliveryProvider.send(target, message) -> DeliveryResult
DeliveryRouter.route(channel) -> DeliveryProvider
FeishuDeliveryProvider.send(...)
```

`FeishuService` 目前同时承担 inbound message、file download、thread loader、reply 和 send 能力。未来可以拆出 `FeishuDeliveryProvider`，让飞书主动触达不再依赖 `FeishuIncomingMessage`。

### Feedback

复习反馈是闭环的关键。用户在飞书里回复“记得 / 忘了 / 稍后”时，系统应更新复习状态，而不是把这句话当普通聊天。

建议用户交互：

```text
待复习：
R1. 请用一句话回忆：...
R2. 请用一句话回忆：...

回复：R1 记得 / R1 忘了 / R1 稍后
```

核心流程：

```text
InboundMessage
  -> ReviewFeedbackParser
  -> DeliveryLedger.resolve_item(short_id)
  -> ReviewPolicy.next_schedule(outcome)
  -> ReviewRepository.update_schedule(...)
```

`R1` 只是用户可见短编号，必须能映射回真实 `review_card.id`。因此 delivery 记录需要保存 digest item 映射。

建议对象：

```text
DigestDelivery
  id
  subscription_id
  user_id
  channel
  target_id
  digest_date
  idempotency_key
  status
  sent_at

DigestDeliveryItem
  delivery_id
  short_id       -- R1
  review_card_id
  note_id
```

初始复习策略：

| 反馈 | 调度策略 |
| --- | --- |
| 记得 | `interval_days = max(2, interval_days * 2)` |
| 忘了 | `interval_days = 1` |
| 稍后 | `due_at = now + 4 hours` |

## 分层归属

| 层次 | 归属能力 | 不应承担 |
| --- | --- | --- |
| Memory / Review | 复习卡真源、反馈记录、下一次到期时间 | 飞书发送、文案格式化、调度线程 |
| Review Use Case | Digest 生成、复习反馈应用、订阅任务处理 | HTTP 细节、飞书 SDK 细节 |
| Scheduler / Jobs | 周期触发、订阅扫描、幂等执行 | 生成 prompt、直接拼 SQL、直接调飞书 SDK |
| Delivery | 发送文本、记录 provider 结果 | 决定复习内容、更新记忆状态 |
| Feishu Inbound | 命令识别、反馈识别、普通消息转 entry | 存储复习真源、实现调度 |
| Web / Admin | 订阅管理、发送记录、复习历史查看 | 作为复习主触达入口 |
| LangGraph Entry | 用户自然语言任务、知识 capture / ask / delete / solidify | 系统定时 Digest 主路径 |

## 与当前架构的关系

当前已有能力是迁移资源，不是未来设计的边界：

- `review_cards` 是 Review State 的初始存储。
- `MemoryFacade.due_reviews()` 是 `ReviewRepository.due_cards()` 的当前入口。
- `digest_node()` 曾是 `DigestComposer` 的早期实现；当前 Digest 生成已收敛到 `ReviewDigestUseCase / DigestFormatter`。
- `AgentRuntime.digest()` 是对外 facade，可以保留；当前已委托 `ReviewDigestUseCase`。
- `GET /api/digest` 可以改为读取结构化 `ReviewDigest`，而不是承担主触达职责。
- `FeishuService._send_via_chat_id()` 已提炼出主动发送入口，并可被 `FeishuDeliveryProvider.send()` 消费。
- 飞书 incoming message 已支持 Digest command 分流；feedback 分流仍待补齐。
- `digest_subscriptions / digest_deliveries` 已落到 Postgres，并已接入管理 API、CLI job 和 subscription/date 幂等；投递 item 映射和 feedback 写入仍待补齐。

迁移后的方向：

```text
AgentRuntime.digest(user_id)
  -> ReviewDigestUseCase.generate(user_id)

GET /api/digest
  -> ReviewDigestUseCase.generate(user_id)
  -> Web formatter

ReviewDigestJob
  -> ReviewDigestUseCase.generate(user_id)
  -> DeliveryRouter.send(feishu, target, message)
```

## 调度实现策略

架构上应先定义 `ReviewScheduler` 和 `ReviewDigestJob`，再选择运行方式。

### 首选：应用内 Job Runner

适合单实例或已有 leader election / database lock 的部署。

```text
FastAPI startup
  -> JobRunner.start()
  -> ReviewScheduler.tick()
  -> ReviewDigestJob.run()
```

必须具备：

- delivery ledger 幂等。
- job lock 或 subscription-level lock。
- graceful shutdown。
- 失败重试和错误记录。

### 可选：外部触发内部 Job

cron、K8s CronJob、systemd timer 可以作为部署层唤醒器，但只允许调用内部 job 入口：

```text
uv run personal-agent review-digest
```

它不应该自己拼 Digest 文案，也不应该直接调用飞书 SDK。这样 cron 只是 trigger，不是业务实现。

## 数据模型建议

### `digest_subscriptions`

```text
id
user_id
channel
target_type
target_id
schedule_time
timezone
weekdays
enabled
created_at
updated_at
```

### `digest_deliveries`

```text
id
subscription_id
user_id
channel
target_id
digest_date
idempotency_key
status              -- pending / sent / failed / skipped
provider_message_id
error
sent_at
created_at
```

### `digest_delivery_items`

```text
id
delivery_id
short_id
review_card_id
note_id
prompt_snapshot
created_at
```

### `review_feedback_events`

```text
id
review_card_id
user_id
delivery_id
outcome             -- remembered / forgotten / later
source_channel
source_message_id
created_at
```

## API 和入口

### 管理 API

```text
GET  /api/review/digest/subscriptions
POST /api/review/digest/subscriptions
PATCH /api/review/digest/subscriptions/{id}
POST /api/review/digest/subscriptions/{id}/send-now
GET  /api/review/digest/deliveries
GET  /api/review/cards
POST /api/review/cards/{id}/feedback
```

### Job CLI

```text
uv run personal-agent review-digest
uv run personal-agent review-digest --user-id default --chat-id oc_xxx
```

CLI 只进入应用内 job，不承载业务逻辑。

### 飞书命令

命令识别应在飞书入口处优先于普通 entry：

```text
今日简报
复习一下
digest
```

反馈识别也优先于普通 entry：

```text
R1 记得
R2 忘了
R3 稍后
```

未命中命令或反馈时，继续走现有 `AgentService.entry()`。

## MVP 切分

### M1：领域骨架

- 新增 `personal_agent.review`。
- 定义 `ReviewDigest`、`DigestSubscription`、`DeliveryTarget`、`DeliveryResult`。
- 把 `digest_node()` 的拼装逻辑迁移到 `DigestComposer`。
- `AgentRuntime.digest()` 改为委托 `ReviewDigestUseCase`。

### M2：飞书触达 Provider

- 从 `FeishuService` 提炼主动发送方法。
- 增加 `FeishuDeliveryProvider`。
- Digest formatter 支持飞书纯文本。
- 飞书命令“今日简报 / 复习一下 / digest”短路到 ReviewDigestUseCase。

### M3：调度和订阅

- ~~新增 `digest_subscriptions`。~~ 已有 Postgres 存储骨架。
- ~~新增 `digest_deliveries`。~~ 已有 Postgres delivery ledger 和 subscription/date 幂等。
- ~~实现 `ReviewDigestJob.run()`。~~ 已落地，可由 CLI 内部 job 入口触发。
- ~~实现管理 API。~~ 已有订阅创建/查询/更新、立即发送、投递记录查询。
- 待实现 `ReviewScheduler.tick()`。
- 待实现订阅 UI 和多实例 job lock。

### M4：复习反馈闭环

- 推送时写入 `digest_delivery_items`。
- 飞书入口识别 `R1 记得 / 忘了 / 稍后`。
- 写入 `review_feedback_events`。
- 更新 `ReviewCard.due_at / interval_days`。

### M5：管理台

- 前端管理订阅、发送记录、反馈历史。
- 前端仍不是主复习入口，只负责配置和观察。

## 非目标

第一阶段不做：

- 不把定时 Digest 设计成 LangGraph entry workflow。
- 不让 LLM 决定是否推送或推给谁。
- 不把飞书主动推送伪装成收到一条用户消息。
- 不把 cron 脚本作为业务调度实现。
- 不把前端页面作为复习主入口。

## 推荐口径

Review Digest 应被抽象成一个独立的复习触达子系统：长期复习状态归 Review/Memory，Digest 生成归 Use Case，调度归 Scheduler/Job，发送归 Delivery Provider，飞书只是第一种触达渠道。当前 `digest_node()`、`AgentRuntime.digest()` 和 `FeishuService` 都可以作为迁移起点，但不应定义未来边界。cron 可以唤醒内部 job，却不能承载业务语义。

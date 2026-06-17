# Review Digest 能力说明

Review Digest 是当前工程中已经落地的复习触达子系统。它不依赖用户一直打开前端页面，而是围绕长期记忆中的 `review_cards`，按订阅生成每日复习简报，优先通过飞书触达用户，并把用户反馈写回复习状态。

核心闭环：

```text
review_cards
  -> ReviewDigestUseCase 生成结构化 Digest
  -> ReviewDigestScheduler / CLI job 判断是否到期
  -> DeliveryRouter / FeishuDeliveryProvider 发送到飞书
  -> digest_delivery_items 保存 R1/R2 映射
  -> 飞书或 Web 反馈
  -> review_feedback_events
  -> 更新 ReviewCard.due_at / interval_days
```

## 能力边界

Review Digest 被拆在几个层次里：

| 层次 | 代码位置 | 职责 |
| --- | --- | --- |
| Review Domain | `src/personal_agent/review/` | Digest 生成、格式化、job、scheduler、feedback use case |
| Memory / Review State | `MemoryFacade`、`PostgresMemoryStore` | `ReviewCard` 真源、到期查询、复习卡更新 |
| Delivery | `review.delivery`、`FeishuDeliveryProvider` | 把消息投递到目标 channel |
| Delivery Ledger | `PostgresReviewDigestStore` | 订阅、投递幂等、投递 item 映射、反馈事件 |
| Feishu Inbound | `FeishuService` | 飞书命令、订阅命令、反馈命令优先分流 |
| Web API | `web/routes/review.py` | 管理订阅、手动发送、查询记录、提交 Web 反馈 |
| Frontend | `frontend/src/App.tsx` | Digest 页展示与辅助反馈操作 |

前端是配置和辅助入口，不是复习触达主路径。主路径应优先走飞书或其他主动推送渠道。

## 数据模型

### `review_cards`

复习卡仍属于长期记忆的一部分。当前 `ReviewCard` 包含：

- `id`
- `note_id`
- `prompt`
- `answer_hint`
- `interval_days`
- `due_at`
- `last_reviewed_at`

反馈会更新 `interval_days`、`due_at` 和 `last_reviewed_at`。

### `digest_subscriptions`

保存触达订阅。

关键字段：

- `id`
- `user_id`
- `channel`
- `target_type`
- `target_id`
- `schedule_time`
- `timezone`
- `enabled`
- `payload`

飞书会话订阅默认使用 `target_type=chat_id`。

### `digest_deliveries`

保存每次 Digest 投递记录，并承担幂等账本职责。

关键字段：

- `id`
- `subscription_id`
- `user_id`
- `channel`
- `target_id`
- `digest_date`
- `idempotency_key`
- `status`
- `provider_message_id`
- `error`
- `created_at`
- `sent_at`

`idempotency_key` 当前按 `digest:{subscription_id}:{digest_date}` 生成，避免同一天同一订阅重复发送。

### `digest_delivery_items`

保存飞书简报中的短编号映射，例如 `R1`、`R2`。

关键字段：

- `delivery_id`
- `short_id`
- `review_card_id`
- `note_id`
- `prompt_snapshot`

飞书里用户回复 `R1 记得` 时，系统会用该表映射回真实 `review_card_id`。

### `review_feedback_events`

保存复习反馈历史。

关键字段：

- `review_card_id`
- `user_id`
- `delivery_id`
- `outcome`
- `source_channel`
- `source_message_id`
- `created_at`

`outcome` 当前支持：

- `remembered`
- `forgotten`
- `later`

## 生成与投递

Digest 生成由 `ReviewDigestUseCase` 负责：

- 读取最近笔记：`memory.list_recent_notes()`
- 读取到期复习卡：`memory.due_reviews()`
- 产出结构化 `ReviewDigest`
- 由 `DigestFormatter` 转成文本

待复习项会在文案里带短编号：

```text
待复习内容：
- R1. 某个复习问题
- R2. 另一个复习问题
```

投递由 `ReviewDigestJob` 负责：

1. 检查订阅是否启用。
2. 通过 ledger reserve 本日投递。
3. 生成 Digest。
4. 写入 `digest_delivery_items`。
5. 通过 `DeliveryRouter` 发送。
6. 更新 `digest_deliveries.status`。

## 调度方式

当前支持两种调度方式。

### 外部 cron 唤醒内部 job

推荐把 cron / systemd timer / K8s CronJob 作为唤醒器，而不是业务实现。cron 只调用内部 CLI：

```bash
uv run personal-agent review-digest
```

例如每分钟唤醒一次：

```cron
* * * * * cd /path/to/personalAgent && uv run personal-agent review-digest
```

内部 scheduler 会按订阅的 `schedule_time` 和 `timezone` 判断是否到期；同一天重复唤醒由 `digest_deliveries.idempotency_key` 保证幂等。

手动指定一次性发送目标：

```bash
uv run personal-agent review-digest --user-id default --chat-id oc_xxx
```

### 应用内 scheduler

FastAPI 启动时可以启用应用内 runner：

```env
PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_ENABLED=true
PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_TICK_SECONDS=60
```

应用内 runner 使用 `ReviewDigestScheduler` 定期扫描订阅，并调用同一个 `ReviewDigestJob`。默认关闭，避免多实例部署时意外重复 tick；生产多实例场景下仍依赖数据库幂等兜底，后续可增强为显式 distributed lock。

## 配置

环境变量见 `docs/env.md`。核心配置：

```env
PERSONAL_AGENT_REVIEW_DIGEST_ENABLED=false
PERSONAL_AGENT_REVIEW_DIGEST_USER_ID=default
PERSONAL_AGENT_REVIEW_DIGEST_FEISHU_CHAT_IDS=oc_xxx,oc_yyy
PERSONAL_AGENT_REVIEW_DIGEST_TIME=09:00
PERSONAL_AGENT_REVIEW_DIGEST_TIMEZONE=Asia/Shanghai
PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_ENABLED=false
PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_TICK_SECONDS=60
```

`PERSONAL_AGENT_REVIEW_DIGEST_ENABLED=true` 时，CLI job 或 FastAPI startup 会把配置型飞书 chat id bootstrap 成数据库订阅。

## 飞书入口

飞书文本消息会先识别 Review Digest 相关命令，命中后不进入普通 `AgentService.entry()`。

### 查看 Digest

支持：

```text
digest
/digest
今日简报
今天简报
知识简报
复习一下
今日复习
今天复习
```

### 管理当前会话订阅

支持：

```text
订阅简报
取消订阅简报
简报时间 08:30
```

这些命令会管理当前飞书 `chat_id` 对应的订阅。

### 提交复习反馈

支持：

```text
R1 记得
R1 忘了
R1 稍后
```

英文形式也支持部分别名，例如 `remembered`、`forgotten`、`later`。

反馈规则：

- `remembered`：复习间隔翻倍，下一次按新间隔安排。
- `forgotten`：间隔重置为 1 天，明天再复习。
- `later`：保留当前间隔，明天重新提醒。

## Web API

管理 API 位于 `src/personal_agent/web/routes/review.py`，Web 运行期依赖由 `src/personal_agent/web/context.py` 装配。

订阅管理：

```text
GET  /api/review/digest/subscriptions
POST /api/review/digest/subscriptions
PATCH /api/review/digest/subscriptions/{subscription_id}
POST /api/review/digest/subscriptions/{subscription_id}/send-now
GET  /api/review/digest/deliveries
```

复习卡和反馈：

```text
GET  /api/review/cards
POST /api/review/cards/{review_card_id}/feedback
```

普通 API key 只能管理自身用户的数据；admin key 可以指定 `user_id`。

## 前端辅助入口

前端 Digest 页会展示当前 `/api/digest` 返回的到期复习卡，并提供：

- `记得`
- `忘了`
- `稍后`

按钮会调用：

```text
POST /api/review/cards/{review_card_id}/feedback
```

提交成功后刷新 Digest。这个入口用于补充管理和桌面使用场景，飞书仍是主触达渠道。

## 验证

当前相关测试覆盖：

- Digest job 和投递幂等
- Postgres subscription / delivery / delivery item / feedback event
- scheduler 到期判断
- feedback use case 更新 review card
- 飞书 digest 命令、订阅命令、反馈命令
- Web API 管理接口
- 前端 TypeScript/Vite build

常用验证命令：

```bash
uv run pytest tests/test_review_digest_scheduler.py tests/test_review_digest_job.py tests/test_review_digest_store.py tests/test_review_feedback.py tests/test_feishu.py tests/test_agent_flows.py::TestDigestFlow tests/test_api.py::TestDigestEndpoint::test_digest_returns_data tests/test_api.py::TestReviewDigestManagementEndpoints -q
```

```bash
cd frontend
npm run build
```

```bash
uv run personal-agent review-digest --help
```

## 已知边界

- 多实例部署当前主要依赖 `digest_deliveries.idempotency_key` 做同日幂等兜底，还没有显式 distributed lock / lease。
- Digest 文案当前是规则格式化，后续可加入用户偏好、数量限制和答案提示策略。
- 飞书是第一 delivery provider，`DeliveryRouter` 已留出其他 channel 扩展点。
- 前端没有完整订阅管理台，只提供 Digest 查看和反馈辅助操作。

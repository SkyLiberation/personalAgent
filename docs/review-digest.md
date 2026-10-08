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
| Review Domain | `src/personal_agent/application/review/` | Digest 生成、格式化、job、scheduler、feedback use case |
| Memory / Review State | `MemoryFacade`、`PostgresMemoryStore` | `ReviewCard` 真源、到期查询、复习卡更新 |
| Delivery | `application.review.delivery`、`FeishuDeliveryProvider` | 把消息投递到目标 channel |
| Delivery Ledger | `PostgresReviewDigestStore` | 订阅、投递幂等、投递 item 映射、反馈事件 |
| Feishu Inbound | `FeishuService` | 飞书命令、订阅命令、反馈命令优先分流 |
| Web API | `adapters/web/routes/review.py` | 管理订阅、手动发送、查询记录、提交 Web 反馈 |
| Frontend | `frontend/src/App.tsx` | Digest 页展示与辅助反馈操作 |

前端是配置和辅助入口，不是复习触达主路径。主路径应优先走飞书或其他主动推送渠道。

## 数据模型

运行结构由 [Review 契约](../src/personal_agent/kernel/contracts/review.py)定义，`ReviewCard` 由 [kernel/models.py](../src/personal_agent/kernel/models.py)拥有。持久化记录按职责分工：

| 记录 | 责任 |
| --- | --- |
| `review_cards` | 保存复习题目、提示、间隔与到期时间；反馈更新复习状态 |
| `digest_subscriptions` | 保存用户、投递目标、日程和启用状态 |
| `digest_deliveries` | 保存投递状态与外部消息身份；按 `digest:{subscription_id}:{digest_date}` 预留同日投递 |
| `digest_delivery_items` | 将本次简报中的 `R1/R2` 绑定到真实 `review_card_id` 及题目快照 |
| `review_feedback_events` | 保存用户、复习卡、投递和反馈来源关联 |

用户回复短编号时，反馈用例从本次投递映射恢复复习卡，不靠题目文本猜测目标。接口字段与鉴权由 [Review API](api.md#review-digest-管理接口)维护。

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

应用内 runner 使用 `ReviewDigestScheduler` 定期扫描订阅，并调用同一个 `ReviewDigestJob`。默认关闭；多实例重复 tick 由数据库投递幂等约束兜底。

## 配置

启用、目标、时区、日程及应用内 runner 参数统一见 [Review Digest 配置](env.md#review-digest-飞书触达配置)。`PERSONAL_AGENT_REVIEW_DIGEST_ENABLED=true` 时，CLI job 或 FastAPI startup 将配置中的飞书 chat id 初始化为数据库订阅；实际投递仍由同一 job 与账本执行。

## 飞书入口

飞书文本消息会先识别 Review Digest 相关命令，命中后不进入普通 `AgentService.converse()`。

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

订阅管理、手动投递、记录查询和反馈接口由 [API 文档](api.md#review-digest-管理接口)唯一维护。实现见 [review.py](../src/personal_agent/adapters/web/routes/review.py)，装配见 [context.py](../src/personal_agent/adapters/web/context.py)。普通 API key 管理自身数据，admin key 可指定 `user_id`。

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

## 验证与证据

生成、投递幂等和反馈更新需要按真实用户结果及适用失败反事实验收，当前证据由[评测盘点](evals/02-current-case-inventory.md)拥有。自 2026-09-18 起，历史 `tests/` 只读保留；验证分工统一见 [QLT](devSpec/quality-security.md#1-测试职责与覆盖)。

前端构建和 CLI 参数检查仍可使用 `npm run build`（在 `frontend/` 中）与 `uv run personal-agent review-digest --help`。它们只证明构建或命令入口，不证明投递成功。

## 已知边界

- 多实例部署当前主要依赖 `digest_deliveries.idempotency_key` 做同日幂等兜底，还没有显式 distributed lock / lease。
- Digest 文案由 `DigestFormatter` 规则格式化。
- 当前主动投递使用飞书；投递结果由 `DeliveryRouter` 和 Provider 返回。
- 前端没有完整订阅管理台，只提供 Digest 查看和反馈辅助操作。

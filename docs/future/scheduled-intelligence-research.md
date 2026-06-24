# 持续研究与定时情报简报设计

> P0 状态：已落地。一次性研究、周期订阅、durable worker、独立投递任务、事件聚类、来源可信度、个人知识关联、Web/CLI/飞书反馈和冻结来源质量指标均已实现。P1/P2 仍属于未来范围。

本文设计一个面向个人知识 Agent 的持续研究业务：用户既可以发起一次性研究，也可以订阅周期性信息收集，例如：

> 每天 09:00 收集当天重要的 AI 新闻，去重并交叉验证，结合我的知识库说明为什么值得关注，然后发送到飞书。

这不是给现有问答外接一个 cron，也不是把搜索结果定时拼成列表。目标是把当前一次性 `web_search / capture_url / graph_search / capture_text` 能力组织成一个长期运行、可恢复、可反馈学习的研究闭环。

本文属于未来目标设计。允许新增业务模型、数据表、工具、Workflow 和 Worker task type，但继续复用当前的 LangGraph、ToolGateway、PolicyEngine、Postgres durable queue、DeliveryRouter 和审计体系，不引入第二套 Agent 或调度框架。

## 业务定位

当前工程主要覆盖：

```text
采集 -> 入库 -> 检索问答 -> 复习 -> 知识缺口 -> 整理
```

持续研究补充的是外部世界到个人知识库之间的长期信息通道：

```text
外部信息源
  -> 周期收集
  -> 阅读与证据提取
  -> 事件去重和可信度判断
  -> 与个人知识对照
  -> 个性化简报
  -> 用户反馈
  -> 偏好更新 / 确认入库 / 后续追踪
```

产品定位从“替用户查一次”扩展为：

> 长期替用户关注指定主题，理解哪些变化值得打扰用户，并说明它与用户已有知识有什么关系。

## 目标与非目标

### 目标

- 同一套 Research 业务同时支持一次性研究和周期性订阅。
- Agent 根据收集结果动态决定是否扩展查询、抓取全文、补充来源或停止。
- 对同一事件的转载、重复报道和连续更新进行聚类，而不是逐链接展示。
- 区分事实、官方声明、媒体报道、评论和未经证实的信息。
- 使用个人知识库完成相关性判断、历史对照和知识变化提示。
- 按用户时区和计划时间运行，具备持久化、幂等、重试和失败恢复能力。
- 支持飞书等主动投递渠道，以及“展开、忽略、收藏、入库”等反馈。
- 所有工具调用继续经过 ToolGateway，保留权限、限流、超时和审计。

### 非目标

- 不把通用 cron 表达式解析交给 LLM。
- 不允许 Agent 自主创建无限数量的订阅或无限扩展搜索。
- 不默认把所有外部内容写入长期知识库。
- 不把单一搜索结果或单一媒体报道表述为已确认事实。
- 不用 Research Digest 替代现有 Review Digest。
- 第一阶段不做网页持续爬虫、浏览器自动登录和付费墙绕过。
- 第一阶段不做面向大众的新闻聚合平台，只服务个人订阅和个人知识关联。

## 与现有 Review Digest 的边界

Review Digest 和 Research Digest 都需要调度与投递，但业务真源不同：

| 维度 | Review Digest | Research Digest |
| --- | --- | --- |
| 信息来源 | 用户已有笔记与复习卡 | 外部搜索结果、网页和用户知识 |
| 业务目标 | 复习已有知识 | 发现并理解外部变化 |
| 核心动作 | 到期查询、复习反馈 | 查询规划、搜索、阅读、聚类、验证 |
| 主要工具 | 长期记忆读取 | `web_search`、`capture_url`、`graph_search` |
| 输出 | 待复习内容、知识增长 | 新事件、重要性、可信度、个人关联 |
| 反馈 | 记得 / 忘了 / 稍后 | 展开 / 有用 / 不感兴趣 / 收藏 / 入库 |
| 幂等粒度 | 每订阅每天一次 | 每订阅每 collection window 一次 |

两者应共享通用基础设施，但不共享领域模型：

```text
共享：
  SchedulePolicy
  SubscriptionScheduler
  Durable Worker Queue
  DeliveryRouter
  Delivery Ledger Pattern

独立：
  ReviewSubscription / ReviewDigest
  ResearchSubscription / ResearchRun / IntelligenceDigest
```

## 核心用户场景

### 周期新闻简报

```text
每天 9 点收集当天 AI 新闻，最多 8 条，
优先关注大模型、Agent 和开源项目，忽略融资八卦，发送到飞书。
```

### 技术追踪

```text
每周一整理 LangGraph、OpenAI Agents SDK 和 MCP 的重要更新，
对比我知识库中的 Agent 架构笔记。
```

### 论文速递

```text
工作日 18 点收集 RAG 和 GraphRAG 新论文，
只保留有代码或公开数据集的工作。
```

### 公司与产品动态

```text
每天关注 OpenAI、Anthropic、Google DeepMind 的官方发布，
重要产品变化立即提醒，其余进入日报。
```

### 一次性深度研究

```text
调研最近一个月 Agent tool use 的进展，
对比我已有的工具治理设计并生成研究报告。
```

一次性和周期性任务共用 ResearchWorkflow。区别仅在触发方式、collection window 和结果是否继续调度。

## 目标架构

```text
User Entry / Web API / Feishu Command
  -> Research Intent
  -> ResearchSubscriptionUseCase
  -> ResearchSubscriptionStore

External Cron / In-app Scheduler
  -> SubscriptionScheduler
  -> enqueue(research_run)
  -> Postgres Worker Queue
  -> Research Worker
  -> ResearchWorkflow
       -> Query Planner
       -> Collect ReAct
       -> Event Normalization
       -> Deduplicate / Cluster
       -> Source Verification
       -> Personal Knowledge Comparison
       -> Digest Composition
  -> ResearchRunStore / ArtifactStore
  -> DeliveryRouter
  -> Research Delivery Ledger
  -> User Feedback
  -> Preference Profile / Follow-up Action
```

关键边界：

1. Scheduler 只判断到期并创建 durable task，不执行搜索和生成。
2. Worker 只领取并驱动 ResearchWorkflow，不私自绕过 ToolGateway。
3. Workflow 决定研究过程，工具负责可治理的外部或内部动作。
4. Delivery 是工作流的末端 activity，不与研究分析逻辑耦合。
5. 用户知识库写入属于独立确认动作，不是简报生成的默认副作用。

## 核心领域模型

### ResearchSubscription

```python
class ResearchSubscription:
    id: str
    user_id: str
    name: str
    topic: str
    instructions: str

    seed_queries: list[str]
    language: str
    region: str | None
    lookback_hours: int
    max_items: int

    source_preferences: SourcePreferences
    content_preferences: ContentPreferences
    schedule: SchedulePolicy
    delivery: DeliveryTarget
    save_policy: "none" | "digest_only" | "approved_items"

    enabled: bool
    created_at: datetime
    updated_at: datetime
```

`topic` 表示稳定主题，例如“AI”；`instructions` 表示用户的个性化要求，例如“优先技术发布，减少融资新闻”。`seed_queries` 是用户或系统确认的初始查询，不等同于每次运行的实际搜索查询。Agent 可以在单次运行预算内扩展查询，但不能修改订阅真源，除非用户明确确认。

### SchedulePolicy

```python
class SchedulePolicy:
    frequency: "daily" | "weekdays" | "weekly" | "interval"
    schedule_time: str
    timezone: str
    weekdays: list[int]
    interval_minutes: int | None
    quiet_hours: QuietHours | None
```

第一阶段优先支持 `daily / weekdays / weekly`。不要求用户直接提供 cron 表达式，避免时区、夏令时和非法表达式进入业务层。

### SourcePreferences

```python
class SourcePreferences:
    preferred_domains: list[str]
    excluded_domains: list[str]
    prefer_primary_sources: bool
    require_multiple_sources: bool
    allowed_document_types: list[str]
```

这里表达的是排序和筛选偏好。真正的网络访问权限仍由工具的 `allowed_domains` 和 PolicyEngine 决定，用户偏好不能放宽系统安全边界。

### ContentPreferences

```python
class ContentPreferences:
    include_topics: list[str]
    exclude_topics: list[str]
    minimum_importance: float
    include_rumors: bool
    novelty_weight: float
    personal_relevance_weight: float
```

用户反馈可以生成候选偏好，但候选偏好应具备来源和置信度，不应因为一次“不感兴趣”永久屏蔽整个主题。

### ResearchRun

```python
class ResearchRun:
    id: str
    subscription_id: str | None
    user_id: str
    trigger_type: "manual" | "scheduled" | "event"
    status: "queued" | "running" | "completed" | "partial" | "failed" | "skipped"

    window_start: datetime
    window_end: datetime
    workflow_id: str
    workflow_version: str

    query_plan: QueryPlan | None
    source_count: int
    event_count: int
    selected_count: int
    digest_id: str | None

    budget_usage: ResearchBudgetUsage
    failure_reason: str | None
    created_at: datetime
    completed_at: datetime | None
```

`subscription_id` 允许为空，以支持一次性研究任务。完整网页正文、模型 transcript 和中间证据不直接塞入该行，而是写入现有或未来 ArtifactStore。

### ResearchEvent

Research 的最小业务单位不是 URL，而是“事件”：

```python
class ResearchEvent:
    id: str
    run_id: str
    canonical_key: str
    title: str
    summary: str
    occurred_at: datetime | None

    entities: list[str]
    topics: list[str]
    event_type: str
    claims: list[ResearchClaim]
    sources: list[ResearchSource]

    importance_score: float
    novelty_score: float
    confidence_score: float
    personal_relevance_score: float
    status: "verified" | "reported" | "uncertain" | "conflicted"
```

多条 URL 可以属于同一个 `ResearchEvent`。同一事件后续出现官方确认或重要更新时，可以产生新的 event revision，而不是永久被历史去重吞掉。

### IntelligenceDigest

```python
class IntelligenceDigest:
    id: str
    run_id: str
    user_id: str
    title: str
    executive_summary: str
    items: list[IntelligenceDigestItem]
    no_major_update: bool
    generated_at: datetime
```

每个条目至少回答：

- 发生了什么。
- 为什么重要。
- 信息可信度如何。
- 它与用户已有知识或关注点有什么关系。
- 下一步可以展开、跟踪还是入库。

## ResearchWorkflow

### Workflow 定义

```text
research-trigger
  -> research-load-subscription
  -> research-plan-queries
  -> research-collect
  -> research-normalize
  -> research-cluster
  -> research-verify
  -> research-personalize
  -> research-rank
  -> research-compose
  -> research-deliver
  -> research-record-outcome
```

建议将它定义为新的固定 `WorkflowSpec`。拓扑、预算和风险策略由 workflow 决定，Agent 自主性主要存在于 `plan-queries`、`collect` 和必要的补充验证中。

### 1. Load Subscription

确定性读取订阅快照，计算本次 collection window：

```text
window_end   = scheduled fire time
window_start = max(last_successful_window_end, window_end - lookback)
```

需要保留少量 overlap，例如 1 小时，以避免来源发布时间延迟造成漏收。重复内容由 event ledger 去重。

### 2. Plan Queries

LLM 根据以下信息生成结构化 `QueryPlan`：

- 订阅 topic、instructions 和 seed queries。
- collection window。
- 上一次简报中的事件与查询。
- 用户近期反馈。
- 个人知识库中的重点实体和关注主题摘要。
- 单次运行预算。

```python
class QueryPlan:
    queries: list[ResearchQuery]
    stop_conditions: list[str]
    expected_facets: list[str]
```

查询需要覆盖不同信息面，例如：

```text
AI official announcements
AI model release
AI agent open source release
AI research paper
AI safety policy
```

`QueryPlanValidator` 必须限制：

- 查询数量。
- 单条查询长度。
- 允许语言。
- 禁止注入 URL 访问权限。
- 禁止把用户私有内容拼入外部搜索查询。

### 3. Collect

`research-collect` 使用受控 ReAct，而不是固定调用一次 `web_search`：

```text
允许工具：
  web_search
  capture_url
  graph_search（仅用于内部相关性判断）

禁止工具：
  capture_text
  delete_note
  restore_note
  任何外发或长期写入工具
```

Agent 可以根据 observation：

- 搜索结果不足时改写或扩展查询。
- 同一来源占比过高时更换查询角度。
- snippet 信息不足时调用 `capture_url`。
- 发现重大事件但缺少原始来源时搜索官方公告。
- 达到证据充分或预算上限时停止。

ReAct 的自主范围必须受三类预算共同限制：

```python
class ResearchBudget:
    max_queries: int
    max_search_results: int
    max_fulltext_fetches: int
    max_tool_calls: int
    max_model_tokens: int
    max_elapsed_seconds: int
```

### 4. Normalize

把搜索结果和正文统一转为 `ResearchSource` 与候选事件：

```python
class ResearchSource:
    url: str
    canonical_url: str
    domain: str
    title: str
    published_at: datetime | None
    author: str | None
    source_type: "official" | "paper" | "media" | "blog" | "social" | "unknown"
    snippet: str
    content_artifact_ref: str | None
```

归一化必须处理：

- URL canonicalization。
- 跟踪参数去除。
- 发布时间与抓取时间分离。
- 原始来源与转载来源区分。
- 同域名镜像和内容指纹。
- 无法确定发布时间时保留 unknown，不猜测。

### 5. Cluster / Deduplicate

去重分两层：

1. 文档去重：相同 URL、canonical URL 或内容指纹。
2. 事件聚类：多个来源报道同一事件。

事件聚类可结合：

- 标题和摘要语义相似度。
- 核心实体重叠。
- 事件类型。
- 时间窗口。
- 关键 claim 重叠。

不应只按 embedding 相似度合并。以下情况必须保留为独立事件或 revision：

- 同一产品的不同版本发布。
- 首次传闻与后续官方确认。
- 同一政策的草案、通过和生效。
- 同一事件的实质性后续进展。

### 6. Verify

对高重要性候选事件进行来源验证：

```text
官方一手来源 + 独立报道       -> verified
多个可靠独立来源             -> verified/reported
单一媒体来源                  -> reported
匿名消息或社交媒体单源        -> uncertain
来源之间关键事实冲突          -> conflicted
```

验证不是简单“来源数量 >= 2”。应评估来源独立性，避免十篇转载被视为十个证据。

对于缺少验证的高重要性事件，Agent 可以在剩余预算内发起补充搜索。达到预算仍不足时，简报必须明确标注“不确定”，不能为了完整性编造结论。

### 7. Personalize

通过 `graph_search` 和本地检索对照用户知识：

- 是否与用户已有主题相关。
- 是否更新、补充或反驳已有知识。
- 是否命中用户正在跟踪的项目、公司或技术。
- 是否与最近阅读和反馈存在关联。

这一阶段不把个人知识内容发送到外部工具。个人知识只进入本地检索和模型上下文。

推荐输出结构：

```python
class PersonalRelevance:
    score: float
    related_note_ids: list[str]
    relation: "new" | "update" | "support" | "conflict" | "background"
    explanation: str
```

### 8. Rank

候选事件综合排序：

```text
final_score =
    importance
  + novelty
  + confidence
  + personal_relevance
  + source_quality
  - redundancy
  - preference_penalty
```

具体权重应配置化并进入 eval，而不是永久写死在 prompt 中。

排名还需要多样性约束，避免 8 条简报全部是同一家公司的同类新闻。

### 9. Compose

建议简报结构：

```text
AI 情报简报 · 2026-06-23

今日结论
- 2 条高重要性更新，3 条值得关注，无重大风险公告。

1. 事件标题
发生了什么：
为什么重要：
与你的知识关联：
可信度：已验证 / 报道中 / 不确定
来源：官方 + 独立报道
操作：展开 / 收藏 / 入库 / 减少此类内容

趋势观察
- 过去 7 天连续出现的方向变化。

未纳入正文
- 12 条重复报道、4 条低可信消息、7 条低相关内容。
```

没有重大更新时允许输出轻量结果或静默，行为由订阅策略决定：

```python
empty_policy: "send_short" | "silent"
```

### 10. Deliver

复用 `DeliveryRouter`，第一阶段支持飞书。投递前先在 ledger 中原子 claim：

```text
research:{subscription_id}:{window_start}:{window_end}
```

研究成功但投递失败时，不应重新运行整个研究工作流。应保存 Digest artifact，并单独重试 delivery activity。

## 工具能力扩展

现有工具可以覆盖第一版主链路：

| 工具 | 用途 |
| --- | --- |
| `web_search` | 搜索候选来源 |
| `capture_url` | 抓取重点页面全文 |
| `graph_search` | 检索个人知识关联 |
| `capture_text` | 用户确认后保存简报或条目 |

为了提高业务语义和可测试性，后续建议增加以下工具。

### `search_news`

面向时间窗口的信息搜索工具。它不是另一个搜索 provider，而是对 `web_search` 的业务适配：

```python
SearchNewsArgs:
    query
    published_after
    published_before
    preferred_domains
    limit
```

返回必须包含发布时间可信度和来源类型。底层仍可使用 Tavily 或其他 provider。

### `fetch_source`

替代 ResearchWorkflow 直接理解 `capture_url` 的采集语义，返回：

- 正文 artifact ref。
- 标题、作者、发布时间。
- source type。
- 内容指纹。
- 抓取状态。

### `search_personal_knowledge`

对 `graph_search` 增加适合个性化比较的稳定输出，避免 Research Agent 依赖图谱工具的私有返回结构。

### `save_research_item`

高层写入工具，用于用户确认后把某个事件保存为知识笔记，并保留：

- ResearchRun / ResearchEvent 来源。
- 外部 source URLs。
- confidence 和 verification status。
- 与已有 note 的关系。

它属于写长期记忆工具，应走明确确认或 `approved_items` 策略，不能进入收集 ReAct allowlist。

### 工具 Artifact 增强

Research 场景要求 Agent 能稳定判断是否继续行动。建议逐步为工具 artifact 增加通用机器信号：

```python
class ToolArtifact:
    ok: bool
    status: "success" | "partial" | "empty" | "failed"
    data: Any
    error: str | None
    error_kind: ToolErrorKind | None
    evidence: list[Any]
    confidence: float | None
    retryable: bool
    next_actions: list[str]
```

`next_actions` 只是工具建议，不直接获得执行权，Agent 和 workflow 仍需结合预算与策略决定下一步。

## 调度与 Durable Execution

### 到期扫描

可以复用当前 Review Digest 的模式：

- 外部 cron 每分钟唤醒内部 scheduler；或
- 单实例开发环境启用应用内 runner。

生产建议：

```text
cron / K8s CronJob
  -> research-scheduler tick
  -> 查询到期订阅
  -> 原子创建 ResearchRun
  -> enqueue worker task
```

Scheduler 不同步执行 ResearchWorkflow，避免一个慢搜索阻塞其他订阅。

### Worker Queue

扩展当前 `WorkflowWorker`：

```python
self._handlers = {
    "graph_sync_note": ...,
    "research_run": self._handle_research_run,
    "research_delivery": self._handle_research_delivery,
}
```

推荐队列：

```text
research-collect
research-delivery
```

至少支持：

- per-user concurrency。
- subscription 级幂等。
- lease / heartbeat。
- retry / dead letter。
- priority。
- due_at。

### 幂等策略

需要三层幂等：

1. Run 幂等：同一订阅和 collection window 只创建一个 run。
2. Event 幂等：同一 canonical event 不在相邻 run 中重复作为“新事件”发送。
3. Delivery 幂等：同一个 digest 和 target 只发送一次。

数据库唯一键应承担最终一致性兜底，不能只依赖进程内状态。

### 失败恢复

| 失败位置 | 恢复策略 |
| --- | --- |
| 查询规划失败 | 使用 seed queries 和确定性查询模板 |
| 单次搜索失败 | transient retry；其他查询继续 |
| 全文抓取失败 | 保留 snippet，降低 confidence |
| 聚类失败 | 文档级去重后继续，标记 partial |
| 验证不足 | 标记 uncertain，不阻断整个简报 |
| 个性化检索失败 | 生成非个性化简报，标记降级 |
| Compose 失败 | 使用结构化事件模板格式化 |
| Delivery 失败 | 单独重试 delivery，不重复研究 |

## 数据存储设计

### `research_subscriptions`

```text
id
user_id
name
topic
instructions
schedule JSONB
preferences JSONB
delivery JSONB
save_policy
enabled
created_at
updated_at
```

### `research_runs`

```text
id
subscription_id nullable
user_id
trigger_type
status
window_start
window_end
workflow_id
workflow_version
query_plan JSONB
source_count
event_count
selected_count
digest_id nullable
budget_usage JSONB
failure_reason
created_at
completed_at
```

唯一约束：

```text
(subscription_id, window_start, window_end)
```

一次性研究可使用独立 idempotency key。

### `research_sources`

```text
id
run_id
url
canonical_url
domain
title
published_at
source_type
content_fingerprint
artifact_ref
metadata JSONB
```

### `research_events`

```text
id
run_id
canonical_key
title
summary
occurred_at
event_type
status
scores JSONB
claims JSONB
personal_relevance JSONB
created_at
```

### `research_event_sources`

```text
event_id
source_id
relation_type
```

`relation_type` 可表达 `primary / independent_report / repost / commentary / contradiction`。

### `intelligence_digests`

```text
id
run_id
user_id
title
payload JSONB
artifact_ref
created_at
```

### `research_deliveries`

```text
id
digest_id
subscription_id
channel
target_id
idempotency_key UNIQUE
status
provider_message_id
error
created_at
sent_at
```

### `research_feedback_events`

```text
id
user_id
subscription_id
run_id
event_id nullable
action
source_channel
source_message_id
payload JSONB
created_at
```

## 用户反馈闭环

第一阶段支持：

```text
N1 展开
N1 有用
N1 不感兴趣
N1 收藏
N1 入库
今天内容太多
以后少发融资新闻
以后多关注开源 Agent
```

反馈分三类处理。

### 即时动作

- 展开：基于该事件和来源生成详细说明。
- 收藏：记录 bookmark，不直接写知识正文。
- 入库：触发 `save_research_item`，写入前展示内容和来源。

### 偏好信号

- 有用 / 不感兴趣。
- 内容过多 / 过少。
- 更关注 / 少关注某主题或来源。

这些反馈先写入事件表，再生成 `PreferenceCandidate`。高置信、重复出现的偏好可以自动应用；明显改变订阅范围的偏好需要用户确认。

### 研究追踪

用户可以对事件开启 follow-up：

```text
继续跟踪这项模型发布，出现 API、价格或开源权重时提醒我。
```

目标形态可把它创建为新的窄主题订阅，或作为父订阅的 tracked entity。第一阶段可只记录待跟踪项，不立即实现事件触发式监测。

## 入口与 API

### 自然语言入口

新增 Intent：

```text
create_research_subscription
update_research_subscription
list_research_subscriptions
pause_research_subscription
run_research_now
research_once
```

高层示例：

```text
每天早上 9 点给我一份 AI 新闻简报。
改成工作日 8:30，只看 Agent 和开源模型。
暂停 AI 简报。
现在立即跑一次。
```

Router 只提取语义目标和原始文本。时间、时区、主题、投递目标等由专门的结构化解析节点生成 SubscriptionDraft；涉及创建或显著修改长期任务时，先向用户展示确认摘要。

### Web API

```text
GET    /api/research/subscriptions
POST   /api/research/subscriptions
PATCH  /api/research/subscriptions/{id}
DELETE /api/research/subscriptions/{id}
POST   /api/research/subscriptions/{id}/run-now

GET    /api/research/runs
GET    /api/research/runs/{id}
GET    /api/research/digests/{id}
POST   /api/research/events/{id}/feedback
POST   /api/research/events/{id}/save
```

`DELETE` 默认停用订阅，不物理删除历史 run、digest 和审计。

## 权限与安全

- 订阅、Run、Event、Digest 和反馈全部强制 `user_id` 隔离。
- 外部搜索查询不得包含完整私有笔记、会话历史或敏感字段。
- URL 抓取继续受 ToolGateway 域名策略、超时和限流约束。
- 网页内容属于不可信输入，不能作为系统指令或工具调用授权。
- Research ReAct 只允许只读工具。
- 创建订阅属于长期后台行为，需要显式确认。
- 自动入库默认关闭；开启时也只允许保存摘要或用户批准条目。
- 投递目标变更需要所有权检查，避免将私人简报发往错误会话。
- 简报必须保留来源链接和不确定性标记。

## 可观测性

新增事件建议：

```text
research_subscription_created
research_run_queued
research_run_started
research_query_planned
research_source_collected
research_event_clustered
research_event_verified
research_digest_composed
research_delivery_succeeded
research_delivery_failed
research_feedback_recorded
research_run_completed
```

关键指标：

- 每个 run 的工具调用数、token、耗时和成本。
- 搜索结果到选中事件的漏斗。
- 重复来源比例和事件压缩比。
- 一手来源覆盖率。
- verified / uncertain / conflicted 比例。
- 用户展开率、收藏率、入库率和负反馈率。
- 无重大更新比例。
- 投递成功率与重复投递率。
- 按订阅的长期点击/反馈衰减。

## 评测设计

### 离线数据集

构造带固定 collection window 的 Research case：

```python
ResearchEvalCase:
    topic
    instructions
    historical_sources
    current_sources
    personal_notes
    expected_events
    expected_exclusions
```

使用冻结搜索结果和网页快照，避免评测依赖实时互联网。

### 核心指标

| 指标 | 说明 |
| --- | --- |
| Query coverage | 查询是否覆盖订阅要求的主要 facet |
| Event recall | 重要事件召回率 |
| Event precision | 入选事件中真正相关和重要的比例 |
| Deduplication quality | 同一事件是否被正确合并 |
| Update distinction | 是否区分重复报道和实质更新 |
| Primary source rate | 有一手来源的事件比例 |
| Claim support | 简报 claim 是否被来源支持 |
| Uncertainty calibration | 证据不足时是否正确降级 |
| Personal relevance | 与用户知识关联是否真实、非牵强 |
| Preference adherence | 是否遵守包含/排除和数量偏好 |
| Tool efficiency | 每个有效事件消耗的工具调用和 token |
| Empty-day quality | 无重大更新时是否避免硬凑内容 |

### 在线反馈指标

- Digest 打开或响应率。
- 条目展开率。
- 收藏、入库和 follow-up 比例。
- “不感兴趣”比例。
- 订阅留存和暂停率。
- 单位打扰带来的有效反馈数。

## 分期方案

### P0-A：一次性研究

> 状态：已实现。

目标：先证明 ResearchWorkflow 的收集、去重、验证和知识对照质量。

- 增加 `research_once` workflow，并将主链路拆为 `research_prepare_run → research_plan_queries → research_collect_sources → research_cluster_events → research_rank_events → research_compose_digest`。
- 使用 `web_search / capture_url / graph_search`。
- 生成结构化研究报告，不做定时调度。
- 建立冻结来源 eval。

验收：

- 能对多个来源聚类去重。
- 重要 claim 保留来源。
- 证据不足时显式标记。
- 能说明与个人知识的真实关联。

### P0-B：周期研究订阅

> 状态：已实现。

目标：支持“每天 9 点 AI 新闻简报”。

生产 worker 消费 scheduled `research_run` 后通过内部 `execute_research_run` workflow 复用已有 `run_id` 执行主链路，投递仍作为独立 durable task 解耦。

- 增加 `ResearchSubscription`、store 和 API。
- 扩展 scheduler 和 worker task。
- 增加 ResearchRun / delivery ledger 幂等。
- 飞书投递。
- 支持 run-now、暂停和修改时间。

验收：

- 时区和计划时间正确。
- 同一窗口不会重复运行和投递。
- 服务重启后可恢复。
- 投递失败不会重复搜索。

### P0-C：个性化与反馈

> 状态：已实现。

- 加入个人知识对照。
- 支持展开、有用、不感兴趣、收藏、入库。
- 建立偏好候选和简报排序调整。
- 支持“今日无重大更新”策略。

### P1：来源与验证增强

- 增加 `search_news / fetch_source` 业务工具。
- 来源独立性分析。
- 官方来源优先和 claim-level verification。
- 连续事件 revision 与趋势观察。

### P2：事件触发和持续追踪

- RSS、官方 changelog、GitHub release、论文源等结构化 connector。
- 重要事件即时提醒，普通事件进入定时简报。
- tracked entity / follow-up subscription。
- 安静时段和通知优先级。

## 推荐首版切片

第一版只实现一个清晰场景：

```text
用户：
  每天 9 点收集 AI 新闻，
  优先大模型、Agent 和开源项目，
  最多 5 条，发送到当前飞书会话。

系统：
  1. 确认主题、时间、时区、数量和投递目标。
  2. 创建 ResearchSubscription。
  3. Scheduler 到期创建 ResearchRun。
  4. Worker 执行受控 ResearchWorkflow。
  5. 搜索、阅读、去重、验证、排序。
  6. 生成带来源和可信度的飞书简报。
  7. 用户可以回复 N1 展开 / 收藏 / 入库 / 不感兴趣。
```

首版限制：

- 每日一次。
- 单一飞书目标。
- 最多 5 个查询、20 个候选来源、5 次全文抓取、5 个最终事件。
- 自动入库关闭。
- 无重大更新时发送一条短消息。
- 只支持低风险只读 ReAct。

这个切片足以验证业务价值和工具编排价值，同时不会一开始就陷入通用调度、全网爬取或复杂多 Agent 系统。

## 与其他未来设计的关系

- Durable run、worker queue、artifact、event history 和 deployment 复用 [Workflow 平台化优化设计](workflow-platform-optimization.md)。
- 外部证据归一、反证、grounding 和 eval 复用 [Capture / Ask RAG 质量优化设计](rag-quality-optimization.md)。
- 第一阶段使用单个受控 ReAct，不依赖 multi-agent；后续高价值事件验证可以复用 [Multi-Agent 设计方案](multi-agent-design.md) 的 critic / judge 思路。
- ResearchWorkflow 仍采用确定性骨架，不把全局流程交给 autonomous planner。

## 最终判断

持续研究是当前工程最自然的业务扩展之一，因为它同时使用了已有但尚未被充分组合的能力：

```text
Scheduler
  + Durable Queue
  + Workflow
  + ReAct Tool Calling
  + Web Search / URL Fetch
  + Personal Knowledge Retrieval
  + Evidence Verification
  + Delivery
  + Feedback
```

它的价值不在“每天自动搜索一次”，而在于：

> 系统能够长期理解一个主题，判断什么是新变化、什么值得关注、什么仍不可信，以及这些变化为什么与当前用户有关。

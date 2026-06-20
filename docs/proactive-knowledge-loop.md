# 主动知识闭环能力说明

本文档描述在 Review Digest 复习触达之上扩展出的一组**主动知识能力**。它们的共同目标是让系统不只是被动回答问题，而是能「回看自己懂了什么、漏了什么」并主动行动——这是 Agent 区别于单次 RAG 问答的核心。

三项能力全部复用既有的调度 / 投递 / 反馈设施（`ReviewDigestScheduler`、`DeliveryRouter`、`FeishuDeliveryProvider`、Postgres ledger），**没有引入新的编排框架**：

1. **知识缺口主动追问**（`insight/`）——后台发现知识孤岛和潜在矛盾，主动向用户提问。
2. **自动主题整理**（`tools/consolidate_notes`）——把同主题的多条笔记整理成一篇综述，原笔记标记为已被取代。
3. **简报知识增长 section**（`review/service`）——日报中展示笔记增长趋势与图谱概览。

> 与本文相关的基础设施见 [review-digest.md](review-digest.md)；系统整体的 LLM/确定性分工见 [summary/llm-decisions-and-deterministic-flows.md](summary/llm-decisions-and-deterministic-flows.md)。

---

## 1. 知识缺口主动追问

### 闭环

```text
知识图谱拓扑 + 本地笔记
  -> KnowledgeGapAnalyzer 确定性检测缺口（孤岛 / 矛盾）
  -> (可选) LLM 改写提问措辞
  -> KnowledgeGapScheduler 按 schedule_time 判断到期
  -> knowledge_gap_deliveries 按天原子去重（claim）
  -> DeliveryRouter / FeishuDeliveryProvider 主动提问
  -> 用户回复
  -> 既有 entry -> router -> capture 路径将回答写回知识库
```

### 检测逻辑（确定性）

`KnowledgeGapAnalyzer`（`src/personal_agent/insight/analyzer.py`）产出两类缺口：

| 缺口类型 | 判定 | 数据来源 |
| --- | --- | --- |
| `isolated_entity`（知识孤岛） | 实体在图谱中连接度 ≤ `min_entity_degree` | `GraphitiStore.get_topology(user_id)` |
| `potential_conflict`（潜在矛盾） | 两条标题词重叠的笔记极性相反（复用 verifier 的否定词启发式） | `memory.list_recent_notes()` |

检测本身完全确定性，符合工程「代码控执行、LLM 处理开放语义」的边界。提问措辞可选经 LLM 改写（见下），改写失败回退确定性模板。

### 提问措辞接 LLM（可选增强）

`KnowledgeGapAnalyzer` 接受一个可选的 `question_llm: Callable[[KnowledgeGap], str | None]`：

- 装配处 `web/context.py:_build_gap_question_rewriter` 用 `LlmClient.generate_answer` 实现它。
- LLM 未配置时返回 `None`，analyzer 保留确定性模板问题，不静默降级。
- 任何异常或空结果都回退模板。

### 防刷屏与幂等

`is_subscription_due` 在过了 `schedule_time` 后当天会持续返回 `True`，因此必须有去重，否则 300 秒一个 tick 会刷屏。`KnowledgeGapJob` 采用两级：

- 有 ledger（生产）：`PostgresReviewDigestStore.claim_gap_delivery(subscription_id, day)` 原子 claim，跨进程重启幂等。
- 无 ledger（测试/降级）：进程内 `dict` 守卫。

关键顺序：**先检测、有缺口才 claim**——避免「上午无缺口的空跑」烧掉当天名额、阻塞下午真实缺口的投递。

### 数据模型 `knowledge_gap_deliveries`

| 字段 | 说明 |
| --- | --- |
| `idempotency_key` | 主键，`gap:{subscription_id}:{day}` |
| `subscription_id` | 复用 digest 订阅（同一批飞书 chat 目标） |
| `gap_date` | 投递日期 |
| `created_at` | 创建时间 |

订阅复用 `digest_subscriptions`，但 gap job 用独立的 `schedule_time`（默认 20:00），与日报（默认 09:00）错开。

---

## 2. 自动主题整理（consolidate_notes 工具）

### 能力

把同一主题下的多条笔记整理成一篇结构化综述，原笔记保留但标记为 `superseded`（可恢复、默认退出检索）。

```text
note_ids + topic
  -> 加载各源笔记（所有权校验）
  -> LLM 生成结构化综述草稿（失败回退确定性拼接）
  -> capture_text 链路写入新笔记
  -> 对每条源笔记 supersede_note(old, new)
  -> 综述 supersedes_note_ids 记录来源，可回溯
```

### 工具与执行

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| 工具定义 | `src/personal_agent/tools/consolidate_notes.py` | args schema、governance、结果归一 |
| 执行器 | `AgentRuntime.execute_consolidate`（`agent/runtime.py`） | 加载 / 生成 / 入库 / supersede 编排 |
| 服务委托 | `AgentService.execute_consolidate` | 对外暴露入口 |

工具治理：`risk_level=low`、`side_effects=("write_longterm",)`、`permission_scope="memory:write"`，无需 confirm（综述是新增笔记，原笔记走 supersede 标记而非删除，可恢复）。仍走 Gateway/Policy。

容错：单条 `supersede_note` 失败记入返回的 `failed`，**不回滚整篇综述**——新笔记已是当前真源。

### 返回结构

`artifact.data` 包含：`note_id`（综述）、`title`、`summary`、`superseded`（成功取代的原笔记 ID）、`failed`（处理失败的原笔记 ID）。

### 当前触发方式

第一版通过 `AgentService.execute_consolidate` 直接调用或后台 job 触发。**尚未接入用户自然语言主动触发**（「把关于 X 的笔记整理成一篇」）——这需要新增 `EntryIntent` + 注册 workflow + 多 note_id 解析与注入逻辑，会触动 router 这个强单点 LLM 依赖，按计划留作独立任务。

---

## 3. 简报知识增长 section

`ReviewDigestUseCase`（`src/personal_agent/review/service.py`）在「最近笔记 / 待复习」之外新增「知识增长」section：

- **趋势行**（始终可用）：本周新增 vs 上周笔记数，来自本地 `created_at`，例如「本周新增 5 条笔记（上周 3 条，↑2）」。图谱不可用时仍能展示。
- **图谱概览**（图谱可用时追加）：实体/关联总数、连接最密集的概念、关联事实样例，来自 `get_topology(user_id)`。

整个 section 仅在「既无笔记增长也无图谱」时才完全省略。图谱失败只丢图谱部分，不影响趋势行——遵循「图谱失败不阻断本地路径」原则。

> 配套修复：`GraphitiStore.get_topology` 此前忽略 `user_id` 返回全图，现已按 `group_id` 过滤，多用户不再串数据。

---

## 配置

知识缺口追问（`KnowledgeGapConfig`，前缀 `PERSONAL_AGENT_KNOWLEDGE_GAP_`）：

```env
PERSONAL_AGENT_KNOWLEDGE_GAP_ENABLED=false
PERSONAL_AGENT_KNOWLEDGE_GAP_TIME=20:00
PERSONAL_AGENT_KNOWLEDGE_GAP_SCHEDULER_ENABLED=false
PERSONAL_AGENT_KNOWLEDGE_GAP_SCHEDULER_TICK_SECONDS=300
PERSONAL_AGENT_KNOWLEDGE_GAP_MAX_GAPS=3
PERSONAL_AGENT_KNOWLEDGE_GAP_MIN_DEGREE=1
PERSONAL_AGENT_KNOWLEDGE_GAP_RECENT_NOTE_LIMIT=30
```

`max_gaps_per_run` 限制单次提问条数，避免打扰用户——这是主动 Agent 最易翻车处。知识增长 section 与 consolidate 工具无独立开关，随 Review Digest / Agent runtime 默认启用。

装配统一在 `web/context.py:build_web_app_context`，生命周期由 `startup()/shutdown()` 管理；`scheduler_enabled=true` 时启动应用内 runner。

---

## 验证

相关测试：

- `tests/test_knowledge_gap_analyzer.py`——孤岛 / 矛盾检测、max_gaps 上限、图谱失败降级、LLM 改写与回退
- `tests/test_knowledge_gap_job.py`——有缺口才投递、按天去重、ledger 跨重启幂等、空跑不烧名额
- `tests/test_review_digest_store.py::test_claim_gap_delivery_is_idempotent_per_day`——store 层原子幂等
- `tests/test_review_digest_job.py`——知识增长 section（趋势 + 图谱、降级）
- `tests/test_consolidate_notes_tool.py`——工具 governance 与结果契约
- `tests/test_agent_flows.py::TestCaptureFlow::test_consolidate_notes_*`——端到端 supersede（真实 Postgres）

常用命令：

```bash
uv run pytest tests/test_knowledge_gap_analyzer.py tests/test_knowledge_gap_job.py tests/test_consolidate_notes_tool.py tests/test_review_digest_job.py -q
```

---

## 已知边界

- **consolidate 尚无自然语言主动触发**：需新增意图 + workflow + 多 note_id 解析注入，留作独立任务。
- **gap 矛盾检测是词重叠 + 否定词启发式**：可能漏判语义矛盾，仅用于「值得问一句」而非断言冲突。
- **gap 提问反馈未做强关联**：用户回答靠既有 capture 路径入库，没有「这条回答对应哪个 gap」的硬绑定（刻意避免脆弱的文本前缀解析）。
- **趋势行是固定 7 天窗口**：未做可配置周期与按主题维度的趋势。
- 多实例部署的同日幂等仍依赖 `knowledge_gap_deliveries` 主键兜底，未引入 distributed lock。

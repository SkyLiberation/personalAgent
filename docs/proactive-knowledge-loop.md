# 主动知识闭环能力说明

本文说明知识缺口提问、主题整理和简报增长统计的现行用例及入口。各用例分别拥有检测、写入或投递事实，实际可用范围由当前曝光和执行契约决定。

三个用例分别由应用服务实现：模型只可调用当前明确曝光的能力，定时任务按订阅调用缺口检测或简报用例，再由投递组件发送。当前曝光见第 2 节入口表；定时与主动查询共用业务用例，主动查询本身不触发订阅投递。

1. **知识缺口主动追问**（`insight/`）——后台发现知识孤岛和潜在矛盾，主动向用户提问。
2. **自动主题整理**（`consolidate_knowledge`）——按主题选择多条笔记并整理成综述，原笔记标记为已被取代。
3. **简报知识增长 section**（`review/service`）——日报中展示笔记增长趋势与图谱概览。

> 与本文相关的基础设施见 [review-digest.md](review-digest.md)；系统整体架构与 LLM/确定性分工见 [architecture/core-architecture-current-state.md](architecture/core-architecture-current-state.md)。

---

## 1. 知识缺口主动追问

### 闭环

```text
知识图谱拓扑 + 本地笔记
  -> KnowledgeGapUseCase
  -> KnowledgeGapAnalyzer 确定性检测缺口（孤岛 / 矛盾）
  -> (可选) LLM 改写提问措辞
  -> KnowledgeGapScheduler 按 schedule_time 判断到期
  -> knowledge_gap_deliveries 按天原子去重（claim）
  -> DeliveryRouter / FeishuDeliveryProvider 主动提问
  -> 用户回复
  -> 用户通过明确 Capture/Conversation 保存入口决定是否写回知识库
```

### 检测逻辑（确定性）

`KnowledgeGapAnalyzer`（[analyzer.py](../src/personal_agent/application/insight/analyzer.py)）产出两类缺口：

| 缺口类型 | 判定 | 数据来源 |
| --- | --- | --- |
| `isolated_entity`（知识孤岛） | 实体在图谱中连接度 ≤ `min_entity_degree` | `GraphitiStore.get_topology(user_id)` |
| `potential_conflict`（潜在矛盾） | 两条标题词重叠的笔记极性相反（复用 verifier 的否定词启发式） | `memory.list_recent_notes()` |

检测产出的是候选信号。词重叠与否定词不能判定语义矛盾，系统只据此提出问题；提问措辞可选经 LLM 改写，异常或空结果保留模板。

### 提问措辞接 LLM（可选增强）

`KnowledgeGapAnalyzer` 接受一个可选的 `question_llm: Callable[[KnowledgeGap], str | None]`：

- 装配处 `AgentRuntime` 用共享的 `LlmClient.generate_answer` 实现它。
- LLM 未配置时返回 `None`，analyzer 保留模板问题。
- 任何异常或空结果都回退模板。

### 防刷屏与幂等

`is_subscription_due` 在到达订阅时间后，当天持续返回 `True`。`KnowledgeGapJob` 通过以下边界避免每次 tick 都重复投递：

- 有 ledger（生产）：`PostgresReviewDigestStore.claim_gap_delivery(subscription_id, day)` 原子 claim，跨进程重启幂等。
- 无账本的独立装配：进程内 `dict` 守卫，只在投递成功后记录，不能跨进程恢复。

关键顺序：**先检测、有缺口才 claim**——避免「上午无缺口的空跑」烧掉当天名额、阻塞下午真实缺口的投递。

### 数据模型 `knowledge_gap_deliveries`

| 字段 | 说明 |
| --- | --- |
| `idempotency_key` | 主键，`gap:{subscription_id}:{day}` |
| `subscription_id` | 复用 digest 订阅（同一批飞书 chat 目标） |
| `gap_date` | 投递日期 |
| `created_at` | 创建时间 |

订阅复用 `digest_subscriptions`，缺口调度按自身配置的时间覆盖订阅日程；具体默认值见[环境变量](env.md#知识缺口主动追问)。

---

## 2. 自动主题整理（consolidate_knowledge）

### 能力

把同一主题下的多条笔记整理成一篇结构化综述，原笔记保留但标记为 `superseded`（可恢复、默认退出检索）。

```text
topic
  -> 在应用用例中检索并选择当前版本的相关笔记（所有权校验）
  -> LLM 生成综述草稿（空结果时拼接原文）
  -> capture_text 链路写入新笔记
  -> 对每条源笔记 supersede_note(old, new)
  -> 综述 supersedes_note_ids 记录来源，可回溯
```

### 工具与执行

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| 应用用例 | [consolidation.py](../src/personal_agent/application/knowledge/consolidation.py) | 主题检索 / 生成 / 入库 / supersede 编排 |
| 工具适配 | `src/personal_agent/tools/consolidate_knowledge.py` | `topic`、`user_id` 参数、governance 与结果归一 |
| 服务委托 | `AgentService.execute_consolidate` | 对外暴露入口 |

工具声明 `risk_level=low`、`side_effects=("write_longterm",)`、`permission_scope="memory:write"`，不要求确认；执行仍经过 Gateway 与 Policy。综述写入和源笔记替代分别产生结果。

容错：单条 `supersede_note` 失败记入返回的 `failed`，保留已写入的新笔记并报告失败列表。返回新笔记不代表所有源笔记均已退出检索。

### 返回结构

`artifact.data` 包含：`note_id`（综述）、`title`、`summary`、`superseded`（成功取代的原笔记 ID）、`failed`（处理失败的原笔记 ID）。

### 入口边界

工具的当前曝光由 [tools/](../src/personal_agent/tools)声明，执行规则由[工具专题](topics/tools.md#注册与曝光)拥有：

| 工具 | 曝光与职责 |
| --- | --- |
| `consolidate_knowledge` | `workflow_activity`；主题选笔记、生成和 supersede 由 `KnowledgeConsolidationUseCase` 完成 |
| `review_digest` | `workflow_activity`；即时生成简报，投递与按日幂等由 job 拥有 |
| `inspect_knowledge_gaps` | `public_agent`；返回缺口候选，不执行 scheduler 投递 |

---

## 3. 简报知识增长 section

`ReviewDigestUseCase`（[service.py](../src/personal_agent/application/review/service.py)）在“最近笔记／待复习”之外生成“知识增长”区块：

- **趋势行**：按本地 `created_at` 比较最近 7 天与此前 7 天的笔记数，例如“本周新增 5 条笔记（上周 3 条，↑2）”。两段窗口均无新增或读取失败时省略，图谱不可用不影响该计算。
- **图谱概览**（图谱可用时追加）：实体/关联总数、连接最密集的概念、关联事实样例，来自 `get_topology(user_id)`。

趋势与图谱部分都为空时省略整个区块。`GraphitiStore.get_topology(user_id)` 按用户分组过滤；图谱读取失败只省略图谱部分。

---

## 配置

知识缺口提问的启用、日程、数量与检测参数统一见 [环境变量](env.md#知识缺口主动追问)。`max_gaps_per_run` 限制单次提问条数；知识增长统计随 Review Digest 生成，主题整理由对应 Application 用例执行，其当前曝光见前文入口表。

装配位于 [adapters/web/context.py](../src/personal_agent/adapters/web/context.py) 的 `build_web_app_context`，生命周期由 `startup()/shutdown()` 管理；`scheduler_enabled=true` 时启动应用内 runner。

---

## 验证与证据

有效证据与用户结果由[评测盘点](evals/02-current-case-inventory.md)维护。缺口检测、按日幂等、综述写入和源笔记替代应分别在各自责任边界验收；实现存在不能替代完整闭环通过。历史 `tests/` 只读保留，现行验证分工见 [QLT](devSpec/quality-security.md#1-测试职责与覆盖)。

---

## 已知边界

- **gap 提问反馈未做强关联**：用户回答靠既有 capture 路径入库，没有「这条回答对应哪个 gap」的硬绑定（刻意避免脆弱的文本前缀解析）。
- **趋势行是固定 7 天窗口**：未做可配置周期与按主题维度的趋势。
- 多实例部署的同日幂等仍依赖 `knowledge_gap_deliveries` 主键兜底，未引入 distributed lock。

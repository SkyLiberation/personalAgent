# Research Once Workflow

本文从 `ResearchService` 视角说明一次 `research_once` 的内部执行链路。这里不展开前端、Router、WorkflowSpec 或 LangGraph 入口，只关注业务服务如何把一个 `ResearchRun` 推进为 sources、events 和 digest。

核心代码：

- `src/personal_agent/application/research/service.py`
- `src/personal_agent/kernel/contracts/research.py`
- `src/personal_agent/application/research/extraction.py`

## 总体链路

`research_once` 在 `ResearchService` 内部可以理解为一条 evidence-driven pipeline：

```text
prepare_run
  -> initialize_state
  -> run_research_loop
       -> _next_research_decision
       -> _execute_research_decision
       -> _collect
       -> _cluster_sources
       -> _personalize_and_rank
       -> _evidence_gaps
       -> _should_stop_loop
  -> synthesize_digest
  -> verify_digest
```

最终数据形态大致是：

```text
ResearchRun
  -> ResearchState
  -> ResearchDecision
  -> ResearchSource
  -> ResearchEventFrame
  -> ResearchEvent
  -> EvidenceGap
  -> IntelligenceDigest
  -> DigestClaim
```

关键对象之间保留可审计 trace：

```text
ResearchDecision.id
  -> ResearchSource.decision_id / query / query_phase
  -> ResearchEvent.source_ids / frame
  -> IntelligenceDigestItem.source_ids / decision_ids
  -> DigestClaim.event_id / source_ids / decision_ids / evidence_spans
```

这条链路用于回答三类问题：哪次策略决策触发了某个来源，哪些 event-frame 信号让多个来源被聚成同一事件，以及最终 digest claim 具体被哪些 source span 支撑。

同时 `ResearchState` 保存 latency telemetry：

```text
ResearchDecision.started_at / completed_at / elapsed_ms
ResearchState.stage_timings[]
ResearchState.tool_call_traces[]
ResearchState.satisfaction_model_call_count
```

`stage_timings` 会记录 `next_research_decision`、`execute_research_decision`、`cluster_sources`、`personalize_and_rank`、`evaluate_research_satisfaction` 等阶段耗时；`tool_call_traces` 会记录每次 `web_search/capture_url/graph_search` 的耗时、结果数和失败类型。

为避免多轮 loop 重复消耗外部调用，当前还包含两层缓存：

- `StructuredResearchEventExtractor` 内部缓存 structured LLM 产出的 event-frame。缓存 key 包含 topic、instructions、canonical URL、标题、摘要和正文 fingerprint/preview；同一来源内容不变时，多轮聚类会复用 frame。
- `ResearchState.personal_relevance_cache` 缓存 event 到个人知识图谱的相关性结果。同一 canonical event 再次排序时，不重复调用 `graph_search`。

## 1. prepare_run

`prepare_run()` 创建本次研究的业务锚点 `ResearchRun`。这一阶段不再尝试完整理解用户自然语言，而是先保存原始请求边界。

它会写入：

- `user_id`
- 原始 `topic/request`
- 初始 `instructions`
- 初始 `max_items`
- `window_start / window_end`
- `budget`

默认 budget 来自 `ResearchBudget`：

```text
max_queries = 5
max_exploration_queries = 3
max_verification_queries = 2
max_satisfaction_model_calls = 1
max_search_results = 30
max_fulltext_fetches = 5
max_tool_calls = 15
```

生产运行时默认值来自 `Settings.research`，可通过 env 调整，例如：

```text
PERSONAL_AGENT_RESEARCH_MAX_SATISFACTION_MODEL_CALLS=0|1|2
```

这个预算专门控制 `_evaluate_research_satisfaction()` 是否允许调用 LLM。设为 0 时，停止判断完全使用 deterministic satisfaction；设为 1 时，只有 fallback 判断仍需继续且确实存在语义权衡时才调用一次。

创建后，run 会被持久化，并更新为 `running`。

## 2. initialize_state

`initialize_state()` 负责创建 evidence-driven loop 的初始状态 `ResearchState`，也是当前一次性研究请求的主要语义理解节点。

它会调用 `_understand_research_request()`，把 `ResearchRun` 中保存的原始请求解析成结构化研究配置：

```json
{
  "topic": "Agent Runtime SDK",
  "instructions": "高可信优先；优先结合个人 Agent 工具调用知识",
  "max_items": 1,
  "lookback_hours": 168,
  "policy": {
    "research_type": "technical_product_update",
    "source_preference": ["official", "docs", "github", "paper", "media"],
    "evidence_requirement": "official_or_multi_source",
    "ranking_objective": "confidence_first",
    "verification_strictness": "medium_high"
  },
  "query_plan": [
    {
      "query": "Agent Runtime SDK official announcement",
      "intent": "official",
      "priority": 0.9
    },
    {
      "query": "Agent Runtime SDK GitHub release",
      "intent": "repo",
      "priority": 0.8
    },
    {
      "query": "Agent Runtime SDK technical report",
      "intent": "technical",
      "priority": 0.7
    }
  ]
}
```

LLM 输出不会直接裸用。service 会经过两个受控解析步骤：

- `ResearchPolicyResolver.resolve()`：校验 `policy`，按 `research_type` 补默认 source preference、evidence requirement、ranking objective、verification strictness。LLM 负责语义分类，resolver 负责边界和默认值。
- `QueryPlanner.build()`：解析 `query_plan`，按 priority 排序、去重、按预算截断，并根据 policy 补 fallback query，例如技术产品更新会补 official/docs/github/paper/media 角度。

解析结果会回写到 `ResearchRun`：

- `topic`
- `instructions`
- `max_items`
- `window_start / window_end`
- `query_plan`
- `query_plan_details`
- `policy`

如果没有配置 `generate_text`，或 LLM 输出非法，则使用 `_default_research_understanding()` fallback。fallback 会保留原始 topic/instructions/max_items，通过 `ResearchPolicyResolver` 从 topic/instructions 推断 policy，并调用 `QueryPlanner` 生成默认查询。以技术产品更新为例：

```text
{topic} official announcement
{topic} documentation release notes
{topic} GitHub release
{topic} technical report
{topic} latest news
```

每个 `ResearchQuery` 会变成一个 `ResearchDecision(action="search_web")`。这些 decision 和规范化后的 topic、instructions、max_items、窗口、budget、policy、query_plan 一起组成 `ResearchState`，并写回到 `run.research_state`。

每个 decision 都有独立 `id`。后续 source、digest item 和 claim 会通过这个 id 回链到具体 action，因此延迟分析时可以统计每个 decision/query 的结果数、工具调用数、是否产生 verified event、是否最终进入 digest。

## 3. run_research_loop

`run_research_loop()` 是核心循环。它不是固定一次搜索后结束，而是根据 evidence gaps 动态决定是否继续搜索。

每轮大致做这些事：

1. 检查是否超过 `state.budget.max_queries`
2. 调 `_next_research_decision()` 找下一步 action
3. 用 `_decision_allowed()` 阻止重复 query，并检查 exploration / verification 子预算
4. 调 `_execute_research_decision()` 执行搜索
5. 合并新旧 sources
6. 调 `_cluster_sources()` 把 sources 聚成 events
7. 调 `_personalize_and_rank()` 做个人相关性排序
8. 调 `_evidence_gaps()` 生成证据缺口
9. 调 `_should_stop_loop()` 判断是否停止

每轮执行后，service 会更新：

- `source_count`
- `event_count`
- `selected_count`
- `research_state`
- `query_history`
- `iteration_count`
- `exploration_query_count`
- `verification_query_count`
- `satisfaction_model_call_count`
- `stage_timings`
- `tool_call_traces`
- `stop_reason`

## 4. _next_research_decision

`_next_research_decision()` 决定下一轮要做什么。

优先级是：

1. 如果还没有执行过 query，先执行初始 planned decisions
2. 如果存在 open evidence gap，先生成 gap-driven 候选 action
3. 如果还有 planned decision，继续执行
4. 否则返回 `action="stop"`

gap-driven action 不是让模型自由调用工具。service 会先生成受控候选，作为 policy 的参考动作：

```text
missing_primary_source -> search_web policy-specific primary-source alternatives
single_source          -> search_web "{event.title} independent coverage"
```

`missing_primary_source` 的含义是“缺少 policy 要求的一手来源”。例如：

- `technical_product_update`：official/docs/github/paper 都可能满足 primary-source 要求。
- `academic_research`：paper、官方项目页、GitHub repo 更重要。
- `company_financials`：SEC filing、investor relations、transcript 才是关键证据。

如果 `generate_text` 可用，service 会先调用 `research_policy_decision`，让 LLM 在受控 schema 下决策下一步：

```json
{
  "action": "search_web | stop",
  "query": "...",
  "purpose": "...",
  "event_id": "...",
  "expected_gain": "official_confirmation | independent_source | disambiguation | personal_relevance | recency | stop",
  "cost_level": "low | medium | high",
  "reason": "..."
}
```

这一步允许 LLM 自己提出更具体的 `search_web` query，而不只是从候选中投票。例如它可以认为泛泛搜索官方公告不如直接搜索 technical report 或 GitHub release。确定性代码负责校验：

- action 只能是 `search_web` 或 `stop`
- query 不能为空、不能太长、不能和 `query_history` 重复
- `event_id` 必须来自当前 events 或为空
- 输出非法时回退到确定性策略

如果 policy 输出非法但存在多个候选 action，service 通常直接走 deterministic fallback，避免每轮多一次 LLM。只有在候选较多、`verification_strictness=high` 且验证预算仍充足时，service 才会调用 `research_next_action`，让 LLM 只在候选 action 中选择。若仍非法，系统回退到确定性优先级。

没有 LLM selector 时，fallback 会保持保守策略：优先处理 `missing_primary_source`，避免单源扩展把 loop 拉长。

如果某个 gap candidate query 已执行过，service 会先尝试同一 gap 的 alternative candidates，例如 official/docs/GitHub/paper/filing/transcript；再尝试剩余 planned exploration query；最后才停止为 `no open research actions remain`。重复 query 不再直接停止整个 loop。

## 5. _collect

`_collect()` 负责把 query 转成 `ResearchSource`。

它先调用 `web_search` 工具，然后对结果做清洗：

- 取 URL
- `canonicalize_url()` 去掉 `utm_* / ref` 等 tracking 参数
- 用 canonical URL 去重
- 解析 domain
- 过滤 subscription excluded domains
- 识别 source type：`official / docs / github / paper / filing / investor_relations / transcript / media / blog / social / unknown`
- 写入 title、snippet、published_at、provider
- 写入 `decision_id / query / query_phase`，保留它来自哪次 research decision

之后会按 `_source_priority(source, policy)` 对 sources 排序，优先对当前 policy 偏好的高价值来源调用 `capture_url` 抓全文。抓取受 `max_fulltext_fetches` 限制，正文最多保留 12000 字符。

所有 research 工具调用都会经过 `_invoke_research_tool()`，它会累计 `state.tool_call_count`，并写入 `state.tool_call_traces`：

```text
tool_name
decision_id
elapsed_ms
ok
result_count
error_kind
```

如果超过 `budget.max_tool_calls`，会设置：

```text
stop_reason = "tool budget exhausted"
```

## 6. _cluster_sources

`_cluster_sources()` 把多个 source 聚成一个或多个 `ResearchEvent`。

第一步是调用 `event_extractor.extract()` 生成 event-frame。当前生产路径使用 `StructuredResearchEventExtractor`，输出结构包括：

- `actor`
- `action`
- `object`
- `event_type`
- `occurred_at`
- `entities`
- `confidence`

为控制 latency，`StructuredResearchEventExtractor` 不是对所有 sources 无条件调用结构化 LLM。它先生成 heuristic frames，然后只在这些情况调用 structured model 覆盖：

- 多个 source 之间存在中等标题相似度，可能是同一事件的语义改写。
- actor/object 有重叠，但标题写法差异较大，需要更稳定的 frame 来聚类。
- heuristic frame 缺少 action、event_type 或 object 过短，且附近存在相关 source。

单源事件、标题高度重复、或标题完全无关的 sources 会直接使用 heuristic frame。这样保留 event-frame 对语义聚类的价值，同时避免把固定、显然不需要语义判断的来源都送进 LLM。

结构化 LLM 产出的 frame 会在 extractor 内部缓存。`run_research_loop()` 多轮重新聚类同一批 sources 时，不会对相同 source 重复调用模型；如果 source 正文或 fingerprint 改变，会生成新的 cache key 并重新抽取。

然后 service 用 `frames_describe_same_event()` 判断两个 source 是否描述同一事件。

聚类完成后，每个 cluster 会生成一个 `ResearchEvent`：

- primary source 取 `_source_priority()` 最高的 source
- canonical key 来自 event frame 和 primary source
- status/confidence 由 `_event_status_for_policy()` 根据 `evidence_requirement` 决定
- 例如 `official_or_multi_source` 下，一手来源 + 多独立 domain 会更容易成为 `verified`
- 例如 `primary_financial_source_required` 下，没有 filing/investor_relations/transcript 时会保持 `uncertain`
- 如果最近出现过同 canonical key，novelty 降低
- 写入 `source_ids`
- 写入 `frame` 快照：`actor/action/object/event_type/occurred_at/entities/confidence`

因此 event-frame 的主要作用不是展示标题，而是让不同标题、不同报道口径的 sources 能稳定归并成同一事件。

## 7. _personalize_and_rank

`_personalize_and_rank()` 把事件与个人知识库关联起来。

它会对每个 event 调用 `graph_search`：

```text
question = compact text
structured_context = title + event_type + entities + source_domains + summary
```

如果找到相关长期知识，事件会获得 `PersonalRelevance`：

```text
relation = direct_update | related_update | background_context | weak_match | not_relevant
score = relation-aware score
```

结果会写入 `state.personal_relevance_cache`。后续轮次如果同一 event 仍然参与排序，service 会直接复用缓存的 `PersonalRelevance`，避免重复调用 `graph_search`。

随后 service 计算 `final_score`，综合考虑：

- importance
- novelty
- confidence
- personal relevance

同时会写入 `score_breakdown`：

```text
source_quality
evidence_support
source_independence
novelty
impact
personal_relevance
uncertainty_penalty
final_score
```

具体权重由 `policy.ranking_objective` 决定：

- `confidence_first`：更重视来源可信度，适合高可信 research。
- `personal_relevance_first`：更重视和个人知识的关联，适合订阅/个人情报。
- `novelty_first`：更重视新变化。
- `impact_first`：更重视事件重要性。

排序后的 events 会写回 store。这个步骤决定 digest 优先展示哪些事件。

## 8. _evidence_gaps

`_evidence_gaps()` 根据当前 events 生成证据缺口：

- `single_source`：只有一个独立来源
- `missing_primary_source`：没有满足当前 policy 的一手/关键来源
- `missing_personal_context`：没有个人知识关联

这些 gaps 会影响下一轮 `_next_research_decision()`：

- `missing_primary_source` 会生成 policy-specific primary-source 查询，例如 official docs、GitHub、paper、SEC filing。
- `single_source` 会生成独立来源查询。
- `missing_personal_context` 当前是 `accepted` 诊断项，因为 `_personalize_and_rank()` 已经对事件执行过 `graph_search`；它不再单独触发下一轮搜索。

## 9. _evaluate_research_satisfaction / _should_stop_loop

当前停止条件不再只是散落的规则判断，而是先构造 `ResearchSatisfaction`，再由 `_should_stop_loop()` 根据目标满足度决定是否继续。

代码层面，`_should_stop_loop()` 只做一件事：

```python
satisfaction = self._evaluate_research_satisfaction(state, events)
state.satisfaction = satisfaction
if satisfaction.should_continue:
    return False
state.stop_reason = satisfaction.reason or "research target satisfaction reached"
return True
```

也就是说，真正的停止标准集中在 `_evaluate_research_satisfaction()`。

`ResearchSatisfaction` 包含：

```text
coverage_score
confidence_score
remaining_critical_gaps
marginal_gain
should_continue
reason
```

这些字段不是独立展示字段，而是一起表达“目标是否已经满足”：

- `coverage_score`：当前排在前面的事件是否已经覆盖目标条数。fallback 中计算为 `len(events[:max_items]) / max_items`，上限为 1。
- `confidence_score`：当前入选事件的平均 `confidence_score`。fallback 中只看 `events[:max_items]`。
- `remaining_critical_gaps`：仍然阻碍目标满足的关键 gap。fallback 只把入选事件上的 open `missing_primary_source` 和 `single_source` 当 critical gap。
- `marginal_gain`：继续搜索预计还能带来的新增价值。fallback 中 budget/low-yield 时为 0，有 critical gaps 时较高，没有 critical gaps 时较低。
- `should_continue`：最终是否继续 research loop。`False` 会让 `_should_stop_loop()` 设置 `state.stop_reason` 并停止。
- `reason`：本次继续或停止的可观测原因，会进入 `state.stop_reason`。

### 9.1 LLM satisfaction 路径

如果配置了 `generate_text`，service 不会每轮都调用 `research_satisfaction`。它先算 deterministic fallback，再由 `_should_call_satisfaction_model()` 判断是否值得消耗 LLM：

- fallback 已经明确停止时，不调用 LLM。
- 没有 events 时，不调用 LLM。
- 已达到 `max_satisfaction_model_calls` 时，不调用 LLM。
- 查询/工具预算已经耗尽时，不调用 LLM。
- fallback 仍建议继续，且存在 critical gaps、低收益轮次，或已经进入较后阶段时，才调用 LLM。

这样 satisfaction LLM 从“每轮可能调用”变成“受预算控制的语义仲裁”，避免 latency 被额外模型调用放大。

LLM 输入包含：

- `state.topic`
- `state.instructions`
- `state.max_items`
- `state.policy`
- `state.iteration_count / max_queries`
- `state.tool_call_count / max_tool_calls`
- `state.low_yield_rounds`
- `state.query_history`
- 当前前 10 个 events 的 `status / source_count / source_types / confidence_score / personal_relevance / final_score`
- 当前 evidence gaps 的 `id / event_id / type / severity / status / suggested_action`

LLM 输出形状是：

```json
{
  "coverage_score": 1.0,
  "confidence_score": 0.9,
  "remaining_critical_gap_ids": [],
  "marginal_gain": 0.1,
  "should_continue": false,
  "reason": "research target satisfaction reached"
}
```

LLM 输出仍会被确定性边界约束：

- 分数会被 clamp 到 0 到 1。
- `remaining_critical_gap_ids` 只能引用已有 gap。
- query/tool budget 已耗尽时强制停止。
- LLM 输出非法时回退到 deterministic satisfaction。

特别注意：即使 LLM 认为应该继续，只要已经达到 query 或 tool budget，也会被覆盖成停止：

```text
iteration_count >= max_queries  -> query budget exhausted
verification_query_count >= max_verification_queries -> verification query budget exhausted
tool_call_count >= max_tool_calls -> tool budget exhausted
```

### 9.2 Deterministic satisfaction fallback

没有 LLM、没有 events，或者 LLM 输出非法时，会走 `_default_research_satisfaction()`。fallback 的停止/继续标准如下。

第一步先确定目标条数和当前入选事件：

```python
target_count = max(1, state.max_items)
selected = events[:target_count]
supported = [
    event for event in selected
    if _event_satisfies_policy(event, state.policy)
]
```

这里的 `supported` 表示“证据支撑足够进入目标满足判断”的事件。它不只看 `verified/reported` 标签，而是检查是否满足当前 policy 的 evidence requirement：技术产品更新可以接受 official/docs/github/paper 或多独立来源；公司财报更偏向 filing/investor_relations/transcript；学术研究更偏向 paper 或 primary technical source。

然后计算基础分：

```python
coverage_score = min(1.0, len(selected) / target_count)
confidence_score = average(event.confidence_score for event in selected)
```

接着只从入选事件里挑 critical gaps：

```python
critical_gaps = [
    gap for gap in state.evidence_gaps
    if gap.status == "open"
    and gap.type in {"missing_primary_source", "single_source"}
    and gap.event_id in selected_event_ids
]
```

所以不是所有 gap 都阻止停止：

- `missing_primary_source`：critical，因为会影响可信度。
- `single_source`：critical，因为会影响多源支撑。
- `missing_personal_context`：不是 critical，当前只是 accepted 诊断项，不阻塞 digest。
- 非入选事件上的 gap：不阻塞当前目标满足，因为 digest 只会取 `events[:max_items]`。

### 9.3 强制停止标准

fallback 首先检查硬预算和低收益：

- tool budget 耗尽：`tool budget exhausted`
- query budget 耗尽：`query budget exhausted`
- 连续低收益：`low-yield marginal gain exhausted`

对应代码顺序是：

```text
tool_call_count >= max_tool_calls -> stop
iteration_count >= max_queries -> stop
low_yield_rounds >= 2 -> stop
```

这三类停止不表示“研究目标已经完美满足”，而是表示继续搜索不再被允许或不值得。

### 9.4 目标满足停止标准

真正的“目标满足”停止条件是：

```text
len(supported) >= target_count
and remaining_critical_gaps is empty
```

满足时返回：

```text
coverage_score = 当前覆盖率
confidence_score = 当前平均可信度
remaining_critical_gaps = []
marginal_gain = 0.1
should_continue = false
reason = "research target satisfaction reached"
```

举例：用户要求最多 1 条高可信事件，当前排第一的事件是：

```text
OpenAI announces Agent Runtime SDK
status = verified
sources = official + independent media
open critical gaps = []
```

这时目标已经满足，loop 会停止，而不是继续消耗预算去找更多来源。

### 9.5 继续搜索标准

fallback 会在以下情况继续：

第一种：还没有任何 supported 入选事件。

```text
supported = []
should_continue = true
reason = "supported target events not found yet"
```

例如当前只有一条社交传闻或单源媒体报道，状态仍是 `uncertain`。这时即使 `coverage_score` 看起来已经是 1，也不能停，因为可信度目标没有满足。

第二种：supported 数量少于目标条数。

```text
len(supported) < target_count
should_continue = true
reason = "more supported target events needed"
```

例如 `max_items = 3`，但当前只有 1 条 `verified/reported` 事件。

第三种：supported 数量够了，但入选事件仍有 critical gaps。

```text
critical_gaps != []
should_continue = true
reason = "critical evidence gaps remain"
```

例如某条入选事件是 `reported`，但仍缺官方来源，或者只有单一独立来源。此时下一轮 `_next_research_decision()` 会优先围绕这些 gaps 生成或选择 action。

最后一个 fallback 分支是：

```text
should_continue = bool(critical_gaps)
reason = "critical evidence gaps remain" if critical_gaps else "no critical evidence gaps remain"
```

但在正常情况下，如果没有 critical gaps 且 supported 数量已满足，会提前命中 `research target satisfaction reached`。

此外，如果下一步 decision 不可执行，例如 query 已重复，`run_research_loop()` 会停止在：

```text
no new allowed research action
```

这是 decision 层的停止，不是 satisfaction 层的停止。它表示“理论上还有 gap，但下一步可行动作已经重复或无效”，用于防止循环发散。

### 9.6 用例对照

#### 用例 A：目标满足后停止

用户要求：

```text
调研 Agent Runtime SDK，最多 1 条，高可信
```

当前事件：

```text
OpenAI announces Agent Runtime SDK
status = verified
sources = openai.com + news.example
critical_gaps = []
```

结果：

```text
coverage_score = 1.0
confidence_score = 0.9
remaining_critical_gaps = []
marginal_gain = 0.1
should_continue = false
reason = research target satisfaction reached
```

#### 用例 B：有事件但可信度不够，继续

当前事件：

```text
Media reports Agent Runtime SDK
status = uncertain
sources = news.example
gaps = single_source + missing_primary_source
```

结果：

```text
coverage_score = 1.0
confidence_score = 0.4
remaining_critical_gaps = [single_source, missing_primary_source]
should_continue = true
reason = supported target events not found yet
```

下一轮会倾向搜索官方确认或独立来源。

#### 用例 C：目标条数没满足，继续

用户要求：

```text
最多 3 条
```

当前只有 1 条 `verified` 事件：

```text
coverage_score = 0.3333
len(supported) = 1
target_count = 3
should_continue = true
reason = more supported target events needed
```

#### 用例 D：预算或低收益停止

如果连续两轮没有新 sources：

```text
low_yield_rounds >= 2
should_continue = false
reason = low-yield marginal gain exhausted
```

如果工具调用已用完：

```text
tool_call_count >= max_tool_calls
should_continue = false
reason = tool budget exhausted
```

这些不是“目标已满足”，而是“继续研究的边际收益或预算条件已经不允许”。

## 10. synthesize_digest

`synthesize_digest()` 从 store 读取当前 run 的 ranked events，并按 `max_items` 截断。

然后 `_compose_digest()` 生成 `IntelligenceDigest`，每个 digest item 包含：

- `title`
- `what_happened`
- `why_it_matters`
- `personal_relevance`
- `confidence_label`
- `source_urls`
- `source_ids`
- `decision_ids`
- `claims`

`claims` 是 claim-level verification 的输入。每个 `DigestClaim` 包含：

```text
text
event_id
claim_importance = core | supporting | context
source_ids
decision_ids
evidence_spans
support_level = supported | partially_supported | unsupported | contradicted
```

`_compose_digest()` 会先从 event title 和 event summary 生成初始 factual claims：标题是 `core` claim，摘要首句是 `supporting` claim。此时 `source_ids/decision_ids` 表示候选证据链，真正的 `evidence_spans/support_level` 会在 `verify_digest()` 中填充或收窄。

digest 保存后，run 会先被更新为待 verify 的阶段性状态：

- 有 sources：`completed_with_limitations`
- 无 sources：`partial_no_supported_claims`

最终状态会在 `verify_digest()` 后根据 claim support 重新校准。

并写入：

- `source_count`
- `event_count`
- `selected_count`
- `digest_id`
- `completed_at`

## 11. verify_digest

`verify_digest()` 是最后的 claim-level 证据过滤。

它不再只检查 digest item 是否存在 `source_urls`，而是读取 item 对应的 `ResearchEvent`，把 `ResearchSource` 投影成共享 `EvidenceItem`，再交给 `EvidenceEngine.verify_claims()` 做证据对齐：

- 通过 `SourceDocument / EvidenceItem` 统一来源语义
- 从 `evidence_text_spans` 找到最佳 evidence span
- 计算 claim term coverage
- 使用 EvidenceEngine 内部 entailment judge 判断 `supported / unsupported / contradicted`
- coverage 足够但 entailment 不充分时标记为 `partially_supported`
- 根据 claim support 和 event.status 重新校准 `confidence_label`
- 将 claim 的 `source_ids/decision_ids` 收窄到真正支撑最佳 evidence span 的来源和决策

这一步能防住几类问题：

- 有 URL，但 claim 被 source 夸大或不支持。
- 有 URL，但 source 实际只支持部分说法。
- `uncertain` 被写成 confirmed。
- `reported` 被误写成 `verified`。

过滤规则：

- 没有 `source_urls` 的 item 会被删除。
- 没有对应 event 的 item 会被删除。
- `core` claim unsupported 或 contradicted 时，item 会被删除。
- `supporting/context` claim unsupported 时，该 claim 会被删除，item 保留但 `confidence_label` 会降为 `信息不足`。
- 出现 contradicted claim 的 item 会被删除。
- event.status 不是 `verified` 时，即使 claim supported，也不能标成 `已验证`。

verify 后，run status 也会被重新校准：

```text
completed_verified
completed_with_limitations
partial_no_supported_claims
partial_budget_exhausted
partial_low_yield
```

如果过滤后没有任何 item，会把 digest 改为 no-major-update：

```text
本次时间窗口内未发现有来源支撑的重大更新。
```

这一步保证最终输出不是“有链接就算有证据”，而是每条事实 claim 都有可审计的 source span 和 support level。

## 关键设计点

### Evidence-driven loop

当前 research 不是一次性搜索 pipeline，而是 evidence-driven loop。第一次搜索后，系统会根据事件证据状态生成 gap，再决定是否继续查官方来源或补充来源。

### Event-frame clustering

事件聚类不只依赖标题相似度，而是先抽取 event-frame，再比较 actor/action/object/event_type。这样可以处理“同一事件不同标题”的情况，例如：

```text
OpenAI launches Agent Runtime SDK
New runtime SDK for AI agents announced by OpenAI
```

### Personal relevance ranking

Research 的排序不是纯新闻热度，而是会结合个人知识图谱。一个事件如果能命中用户已有知识，会被提高 relevance，从而更可能进入 digest。

### Latency-sensitive budget

Research loop 同时受多层 budget 约束：

- query budget
- exploration / verification query budget
- search result budget
- fulltext fetch budget
- satisfaction model-call budget
- tool call budget

这些 budget 不只是成本控制，也直接影响端到端 latency。实际耗时会落到 `state.stage_timings` 和 `state.tool_call_traces`，可以按 `decision_id` 分析哪次 query、哪个工具或哪个阶段拖慢了 run。

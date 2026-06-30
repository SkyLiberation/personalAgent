# research_once Evidence-Driven Loop 重构设计

当前 `research_once` 是固定 pipeline：

```text
prepare
  -> plan_queries
  -> collect_sources
  -> cluster_events
  -> rank_events
  -> compose_digest
```

这条链路工程边界清楚，但智能性偏弱。它不会根据搜索结果质量、证据缺口、事件可信度、个人相关性和预算动态调整研究路线。因此不应把它描述成“会研究的 Agent”，更准确是 workflow-native intelligence pipeline。

本设计不考虑旧接口兼容性，目标是把 `research_once` 主路径改成：

```text
research-prepare
  -> research-initialize
  -> research-loop
  -> research-synthesize
  -> research-verify
  -> research-compose
```

外层仍然 workflow-first，负责 run、checkpoint、ToolGateway、审计和最终交付；中间研究过程改成 evidence-driven loop，让系统围绕证据缺口动态决定下一步行动。

## 核心对象

新增 `ResearchState`，作为一次研究的工作记忆：

```text
ResearchState
  run_id
  topic
  instructions
  window_start / window_end
  budget
  query_history
  sources
  events
  evidence_gaps
  decisions
  stop_reason
  iteration_count
```

新增 `ResearchDecision`：

```text
ResearchDecision
  iteration
  action
  query
  purpose
  event_id
  reason
```

新增 `EvidenceGap`：

```text
EvidenceGap
  id
  event_id
  type: missing_primary_source | single_source | missing_personal_context | low_yield
  severity
  suggested_action
  status
```

这些对象不替代 `ResearchRun / ResearchSource / ResearchEvent / IntelligenceDigest`，而是补上研究过程里的“为什么继续 / 为什么停止 / 缺什么证据”。

## Loop 行为

`research_initialize_state(run_id)` 创建初始 state，并写入第一个策略动作。默认动作为围绕 topic、instructions 和时间窗口生成一组初始搜索任务。

`research_loop(run_id)` 负责迭代：

```text
while budget remains:
  decide_next_action(state)
  validate_action(action, state)
  execute_action(action)
  integrate_sources_and_events(state)
  update_evidence_gaps(state)
  evaluate_stop_condition(state)
```

第一版 action space 收敛为：

- `search_web(query, purpose)`：通过 `web_search` 收集来源。
- `fetch_source(url, purpose)`：通过 `capture_url` 抓全文。
- `search_personal_graph(question, event_id)`：通过 `graph_search` 给事件补个人相关性。
- `stop(reason)`：显式停止。

后续可扩展 `verify_event / broaden_query / narrow_to_official_sources / split_event / merge_event`，但第一版先把动态 loop 和状态模型跑通。

## 决策策略

第一版采用“确定性策略 + 可选 LLM query expansion”的混合模式：

1. 初始阶段生成最多 `max_queries` 个查询。
2. 每轮优先执行未运行搜索。
3. 每批来源入库后立即抽事件 frame、聚类为事件。
4. 对新事件立即做个人图谱检索，而不是等最后 rank。
5. 若事件只有单一来源，生成 `single_source` gap。
6. 若事件缺少当前 policy 要求的一手来源，生成 `missing_primary_source` gap，并追加 primary-source 查询。
7. 若连续低收益或预算耗尽，停止。

这比旧 pipeline 智能的地方在于：事件聚类、个人相关性和证据缺口进入 loop 本身，会反向影响下一轮搜索。

## Workflow 替换

旧工具：

```text
research_plan_queries
research_collect_sources
research_cluster_events
research_rank_events
research_compose_digest
```

新工具：

```text
research_initialize_state
research_run_loop
research_synthesize_digest
research_verify_digest
```

`research_prepare_run` 保留，因为 run 仍是持久状态锚点。

新 `research_once`：

```text
research-prepare
  -> research-initialize
  -> research-loop
  -> research-synthesize
  -> research-verify
  -> research-compose
```

新 `execute_research_run`：

```text
research-initialize
  -> research-loop
  -> research-synthesize
  -> research-verify
```

## 交付与校验

`research_synthesize_digest` 从 `ResearchState.events` 选择高分事件生成 `IntelligenceDigest`。

`research_verify_digest` 校验：

- 每个 item 必须有 source URL。
- `verified / reported / uncertain` 与来源数量和官方来源一致。
- 没有足够证据的事件降级为 `uncertain`。
- 若没有事件，生成 no-major-update digest。

最终 `research-compose` 只负责呈现，不再承担研究逻辑。

## 面试口径

重构后的说法：

> `research_once` 不再是固定 plan/collect/cluster/rank 流水线，而是 evidence-driven research loop。外层 workflow 保留确定性控制面，内层 `ResearchState` 记录来源、事件、证据缺口、个人相关性和停止原因；系统每轮根据证据是否足够、来源是否可信、是否和用户已有知识相关来决定继续搜索、抓取全文、查个人图谱或停止。这样智能性体现在研究路线会被中间证据动态改变，而不是固定跑完几个阶段。

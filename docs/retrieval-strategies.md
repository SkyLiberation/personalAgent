# 检索方案说明

本文说明当前工程已有的检索方案、实现位置、排序逻辑、返回结果如何进入回答生成，以及如何用 eval 观测不同方案的效果。

相关代码：

- [src/personal_agent/agent/runtime_ask.py](../src/personal_agent/agent/runtime_ask.py)
- [src/personal_agent/storage/postgres_memory_store.py](../src/personal_agent/storage/postgres_memory_store.py)
- [src/personal_agent/graphiti/store.py](../src/personal_agent/graphiti/store.py)
- [src/personal_agent/graphiti/search_strategies.py](../src/personal_agent/graphiti/search_strategies.py)
- [src/personal_agent/graphiti/reranker.py](../src/personal_agent/graphiti/reranker.py)
- [src/personal_agent/core/evidence.py](../src/personal_agent/core/evidence.py)
- [evals/open_ragbench](../evals/open_ragbench)

## 总体分层

当前 ask 主链路采用分层检索：

```text
用户问题
  -> Graphiti 图谱检索
     -> Graphiti search_config 选候选节点/边/episode
     -> 项目侧 citation reranker 排序关系事实
     -> episode_uuid 映射回本地 KnowledgeNote
     -> 生成图谱事实 + 原文锚点 prompt
  -> 如果图谱不可用或证据不足，回退本地 note 检索
  -> 如果本地证据仍不足，按配置回退 web search
  -> 统一转为 Citation / EvidenceItem
  -> LLM 生成答案
  -> AnswerVerifier 校验证据
```

也就是说，当前不是单一检索器，而是“图谱优先、本地兜底、必要时网络补充”的组合。

## 方案一：本地 note 关键词检索

实现入口：

- [PostgresMemoryStore.find_similar_notes()](../src/personal_agent/storage/postgres_memory_store.py)

使用位置：

- capture 的 `link_node`：为新 note 找相似历史 note，写入 `related_note_ids`
- ask 的本地 fallback：当图谱不可用或图谱答案证据不足时，用本地 note 生成回答
- Open RAGBench 的 `keyword` baseline

核心逻辑：

```text
query.split()
  -> 生成小写 token 集合
  -> 对每个 note 拼接 title + summary + content
  -> 统计 query token 出现在 haystack 中的数量
  -> 按 score 倒序
  -> 如果命中的是 chunk，同一个 parent 只保留最优 chunk，并补充 parent note
  -> 截断到 limit
```

特点：

- 优点：简单、快、无外部依赖，适合作为稳定 fallback。
- 缺点：不是语义检索，英文标点、中文分词、同义词、长问题表达变化都会影响命中。
- 当前排序信号只有 token overlap，没有 embedding、BM25、时间衰减或引用质量权重。

输出会被转换成：

- `KnowledgeNote matches`
- `Citation`
- `EvidenceItem(source_type="note" / "chunk")`

## 方案二：Graphiti 图谱检索

实现入口：

- [GraphitiStore.ask()](../src/personal_agent/graphiti/store.py)
- [GraphitiStore._ask()](../src/personal_agent/graphiti/store.py)

使用位置：

- ask 主链路第一层检索
- `graph_search` 工具

核心过程：

```text
GraphitiStore.ask(question, user_id)
  -> graphiti.search_(
       query=question,
       config=self.search_strategy.search_config,
       group_ids=[user_group_id],
     )
  -> search_result.nodes / search_result.edges
  -> strategy.citation_hits(question, edges, node_names_by_uuid)
  -> GraphAskResult
```

Graphiti 负责根据 `search_config` 在图谱中取回候选节点、边、episode、community 等搜索结果。项目侧随后把 Graphiti 返回的边进一步加工成 `citation_hits`，用于把关系事实映射回本地 note 和回答证据。

`GraphAskResult` 主要成员：

- `entity_names`：命中的实体名
- `relation_facts`：项目侧排序后选出的关系事实
- `related_episode_uuids`：关系事实关联的 episode
- `citation_hits`：带 score、matched_terms、endpoint_names 的事实命中
- `node_refs / edge_refs / fact_refs`：结构化图谱引用

## 方案三：GraphSearchStrategy 策略选择

实现入口：

- [search_strategies.py](../src/personal_agent/graphiti/search_strategies.py)

配置项：

```text
PERSONAL_AGENT_GRAPH_SEARCH_STRATEGY=hybrid_rrf
```

当前内置策略：

| 策略 | Graphiti search_config | 说明 |
| --- | --- | --- |
| `hybrid_rrf` | `COMBINED_HYBRID_SEARCH_RRF` | 默认方案，综合边、点、episode、community，并用 RRF 融合排序 |
| `hybrid_mmr` | `COMBINED_HYBRID_SEARCH_MMR` | 综合搜索后使用 MMR，倾向减少候选结果冗余 |
| `hybrid_cross_encoder` | `COMBINED_HYBRID_SEARCH_CROSS_ENCODER` | 综合搜索后使用 BFS + cross encoder reranking |
| `edge_rrf` | `EDGE_HYBRID_SEARCH_RRF` | 只关注边的 hybrid search + RRF |
| `edge_node_distance` | `EDGE_HYBRID_SEARCH_NODE_DISTANCE` | 只关注边，并引入节点距离排序 |

策略对象当前承担两件事：

1. 选择 Graphiti 的 `search_config`
2. 调用项目侧 `rank_graph_citation_hits()` 生成 `citation_hits`

目前这些策略的 citation rerank 逻辑相同，差异主要来自 Graphiti 原始候选集不同。也就是说，在线 ask 中它们会因为 Graphiti search_config 不同而拿到不同 edges；但在离线 `citation_*` eval 中，如果输入 edges 完全相同，这些策略结果通常也会相同。

## 方案四：关系事实 citation reranker

实现入口：

- [rank_graph_citation_hits()](../src/personal_agent/graphiti/reranker.py)

它是项目侧独立的胶水层，不依赖 GraphitiStore、Settings、Neo4j client 或本地存储。输入是：

- `question`
- Graphiti edge-like 对象列表
- `node_names_by_uuid`

输出是 `GraphCitationHit`：

- `episode_uuid`
- `relation_fact`
- `endpoint_names`
- `matched_terms`
- `entity_overlap_count`
- `score`

核心排序流程：

```text
edges
  -> 读取 edge.fact
  -> 读取 source / target 节点名
  -> 计算问题与 relation_fact 的相关性
  -> 每个 edge.episodes 生成 GraphCitationHit
  -> 按 entity overlap、关键词命中、综合分排序
  -> 去重
  -> 聚焦 top score 附近的事实
```

当前分数由几类启发式信号组成：

- `endpoint_score`：问题中出现关系两端实体名时加分
- `direct_match_score`：问题和关系事实存在包含关系时加分
- `overlap_score`：问题和事实的字符 bigram 重叠数量
- `keyword_score`：问题关键词出现在事实中时加分
- `relation_bonus`：相邻关键词组合后出现在事实中时加分

排序 tuple：

```text
(
  entity_overlap_count,
  len(matched_terms),
  score,
  len(relation_fact),
)
```

这个 reranker 的作用不是替代 Graphiti 检索，而是解决项目侧需要的问题：从 Graphiti 返回的关系边中挑出最适合展示、引用和映射回本地 note 的事实。

## 方案五：图谱检索工具 graph_search

实现入口：

- [`build_graph_search_tool`](../src/personal_agent/tools/graph_search.py)

该工具封装 `GraphitiStore.ask(question, user_id)`，面向工具调用场景返回结构化数据：

- `answer`
- `entity_names`
- `relation_facts`
- `related_episode_uuids`
- `node_refs / edge_refs / fact_refs`
- `EvidenceItem(source_type="graph_fact")`

它和 ask 主链路的区别是：工具本身只执行图谱检索并返回工具结果，不负责完整的 fallback、回答 prompt 构造、verifier retry 和历史记录。

## 方案六：web search fallback

实现位置：

- [runtime_ask.py](../src/personal_agent/agent/runtime_ask.py)
- web search 工具注册与执行逻辑

触发条件：

- 图谱检索不可用或证据不足
- 本地 note 检索也不足
- 当前运行时 `_web_search_available=True`

web 结果会转为：

- `Citation(source_type="web", url=...)`
- `EvidenceItem(source_type="web")`

这个方案不是个人知识库检索的主路径，而是外部信息补充路径。回答 prompt 会要求说明信息来自网络搜索。

## 证据汇聚

当前检索结果最终会汇聚到两个模型：

| 模型 | 用途 |
| --- | --- |
| `Citation` | 面向展示和轻量校验，包含 note_id、title、snippet、relation_fact、url |
| `EvidenceItem` | 面向内部统一证据追踪，覆盖 graph_fact、note、chunk、web、tool |

转换入口：

- `graph_result_to_evidence()`
- `notes_to_evidence()`
- `web_results_to_evidence()`

这样做的好处是：不同来源的检索结果可以在回答生成、证据校验、前端展示和后续 eval 中使用统一结构观察。

## Eval 观测方式

当前已有两类 eval。

### 轻量合成用例

位置：

- [evals/test_retrieval_strategies.py](../evals/test_retrieval_strategies.py)

作用：

- 用小型手写 edge case 验证所有 `GraphSearchStrategy` 的 citation 排序钩子能把预期 fact 排在第一。
- 适合单元级防回归。
- 不代表真实 Graphiti 检索质量，因为输入 edges 是固定的。

### Open RAGBench

位置：

- [evals/open_ragbench](../evals/open_ragbench)

当前支持策略：

- `keyword`
- `citation_reranker`
- `graphiti_hybrid_rrf`
- `graphiti_hybrid_mmr`
- `graphiti_hybrid_cross_encoder`
- `graphiti_edge_rrf`
- `graphiti_edge_node_distance`

示例：

```powershell
uv run python -m evals.open_ragbench.runner `
  --num-queries 50 `
  --corpus-mode relevant `
  --strategies keyword,citation_reranker `
  --output evals/open_ragbench/results/latest.json
```

`corpus_mode`：

- `relevant`：只加载被抽样 query 命中的文档，快，但难度偏低
- `full`：加载完整 arxiv corpus，慢，但更适合公平比较

注意：Open RAGBench 中的 `citation_reranker` 是 citation 层离线评估，它不会真正执行 Graphiti search。要比较 Graphiti 的真实 search_config 差异，请使用 `graphiti_*` 策略。

`graphiti_*` 策略用于真实 Graphiti 检索评估。它会：

1. 用 `corpus_to_notes()` 把 benchmark corpus 转成 `KnowledgeNote`
2. 清理 `--graphiti-user-id` 对应的 Graphiti group
3. 调用 `GraphitiStore.ingest_note()` 把 note 写入 Graphiti
4. 记录 `episode_uuid -> note_id` manifest
5. 对每个 query 调用 `GraphitiStore.ask()`
6. 将返回的 `citation_hits / related_episode_uuids` 映射成本地 note id
7. 用 Open RAGBench 的 qrel 计算 `MRR / Recall@K / NDCG@K`

同一次 runner 里执行多个 `graphiti_*` 策略时，corpus 只会入图一次，后续策略复用同一个 Graphiti group。跨进程复用时可以传入 `--reuse-graphiti`，但要求 manifest 与当前 corpus、user id 匹配。

## 当前局限

- 本地 note 检索是关键词 overlap，不是 BM25 或 embedding retrieval。
- `citation_reranker` 是启发式排序，适合可解释和轻量引用，但不是学习型 reranker。
- `GraphSearchStrategy` 已能切换 Graphiti search_config，但 citation rerank 逻辑仍是共享实现。
- 当前没有真正的多跳路径展开器。Graphiti 的 combined search 可能返回连接到同一问题的多类图谱元素，但项目侧还没有显式执行“从命中实体出发继续扩展 N 跳路径”的算法。
- Open RAGBench 已能比较本地 baseline、citation 层策略和真实 Graphiti search_config；但真实 Graphiti eval 依赖 Neo4j、LLM、embedding 服务，成本和耗时都明显更高。

## 后续扩展方向

- 增加 BM25 或 embedding 本地检索策略，替代当前简单 token overlap。
- 给 `GraphSearchStrategy` 增加可插拔 citation reranker，让不同策略不仅候选集不同，后处理也可以不同。
- 新增显式多跳 graph expansion strategy，例如从 top entities 出发扩展 1 到 2 跳关系，再做 path-level rerank。
- 在 Open RAGBench 的真实 Graphiti eval 中继续补充 token cost、ingest 成功率、query error rate 等运行指标。
- 将 eval 结果持续落到 JSON/CSV，便于长期比较策略变化。

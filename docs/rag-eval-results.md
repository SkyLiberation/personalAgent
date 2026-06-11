# RAG 评估结果

本文集中记录 Ask / 检索链路的评估结果，从 `docs/workflow/capture-ask-model-flow.md` 中拆出，便于独立维护评测口径、数据集规模和关键指标。架构设计仍以 [capture-ask-model-flow.md](workflow/capture-ask-model-flow.md) 为准。

覆盖两个评估数据集：

- **Open RAGBench**（`vectara/open_ragbench`，pdf/arxiv）：单跳检索基准，每个 query 对应 1 个 relevant doc + 1 个 section。框架见 [evals/open_ragbench/](../evals/open_ragbench/)。
- **MultiHopRAG**（`yixuantt/MultiHopRAG`，COLM 2024）：多跳检索基准，每个 query 的 evidence 分布在 2-4 篇文档，分 inference / comparison / temporal / null 四种类型。框架见 [evals/multihoprag/](../evals/multihoprag/)。

两个数据集共享 IR 指标实现（`evals/open_ragbench/metrics.py`）和 Graphiti ingest 的渐进式缓存逻辑，但语义不同：Open RAGBench relevance 是单个 (section_id, parent_id)，MultiHopRAG relevance 是多个 evidence doc 的 parent note id 集合。

主回归结论：

- Open RAGBench 上，最优生产链路是 `optimized hybrid`：MRR=0.721，R@10=0.700。
- MultiHopRAG 上，`optimized hybrid wide` 相比 graphiti-only / hybrid narrow 有小幅提升：MRR=0.434，R@10=0.733，但仍显著低于 retrieval-only Graphiti（MRR=0.589，R@10=0.919）。
- Microsoft GraphRAG CLI 已接入并完成两个 30q 评估集测试，但作为生产 Ask provider 的效果低于 Structural + Graphiti hybrid；主要问题不是“能不能构图”，而是 CLI answer 需要再投影回本地 note id，且 community-level answer 不天然返回可直接评价的证据集合。

## Graphiti Ingest 数据量统计

Graphiti ingest 把 corpus note 写成 Neo4j 中的实体/关系图。以下数据用于估算 ingest 规模、成本和图谱密度，也是判断"图谱是否值得维持"的基线。

数据用 `group_id` 隔离（`group_id = f"{group_prefix}-{user_id}"`，见 [graphiti/store.py](../src/personal_agent/graphiti/store.py) `_group_id`），不同评测 user 互不干扰。

### Open RAGBench 30q（group=`personal-agent-ragbench_eval_30q`，note_mode=parent_sections）

manifest：[evals/open_ragbench/results/graphiti_30q_manifest.json](../evals/open_ragbench/results/graphiti_30q_manifest.json)

| 维度 | 数量 | 说明 |
| --- | ---: | --- |
| note_ids | 750 | parent + section 笔记（30 query 命中约 47 文档展开） |
| episodes | 737 | 成功 ingest 的 episodic node（1 note → 1 episode） |
| ingest_errors | 1 | manifest 记录的失败 note |
| Entity 节点 | 3821 | LLM 抽取的实体节点 |
| RELATES_TO 关系边 | 6685 | 实体间关系事实边 |
| MENTIONS 边 | 10359 | episode → entity 提及边 |
| 孤立 Entity（无 RELATES_TO） | 553 | 占 entity 14.5%，反映抽取后未连通的实体 |
| Entity / episode | 5.18 | 平均每个 episode 抽出的实体数 |
| RELATES_TO / episode | 9.07 | 平均每个 episode 抽出的关系数 |

观察：

- 每 episode 约 5 个实体、9 条关系，密度合理，未出现 zero-entity 大面积塌陷。
- 553 个孤立实体（14.5%）是抽取质量的关注点——这些实体进入了图但没有关系边，对多跳检索无贡献。对应 [capture-ask-model-flow.md](workflow/capture-ask-model-flow.md) 失败模式 #1（抽取质量黑盒）的监控信号。
- ingest 成本：737 episodes 各跑一次实体/关系抽取 LLM 调用，是 30q 评测中最贵的一步，因此必须靠 manifest 缓存复用。

> 复现命令：`scripts/probe_graph_health.py --user ragbench_eval_30q --neo4j`，或直接对 `group_id` 跑 Cypher `MATCH (n:Entity {group_id:$g}) RETURN count(n)`。

### MultiHopRAG 30q（group=`personal-agent-multihoprag_eval_30q`，note_mode=parent_chunks）

manifest：[evals/multihoprag/results/multihoprag_30q_manifest.json](../evals/multihoprag/results/multihoprag_30q_manifest.json)

| 维度 | 数量 | 说明 |
| --- | ---: | --- |
| note_ids | 140 | 38 parent + 102 chunk 笔记（30 query，corpus_mode=relevant 命中 38 篇新闻文档，长文按生产 `chunk_content` 切分） |
| episodes | 139 | 成功 ingest 的 episodic node（1 note → 1 episode） |
| ingest_errors | 1 | manifest 记录的失败 note |
| Entity 节点 | 1163 | LLM 抽取的实体节点 |
| RELATES_TO 关系边 | 2529 | 实体间关系事实边 |
| MENTIONS 边 | 2822 | episode → entity 提及边 |
| 孤立 Entity（无 RELATES_TO） | 129 | 占 entity 11.1%，反映抽取后未连通的实体 |
| Entity / episode | 8.37 | 平均每个 episode 抽出的实体数 |
| RELATES_TO / episode | 18.19 | 平均每个 episode 抽出的关系数 |

观察：

- 相比 Open RAGBench（arxiv 学术 section），新闻文章的实体/关系密度明显更高：8.37 entity/episode、18.19 relation/episode（vs 学术 5.18 / 9.07）。新闻文本人名、机构、产品、事件实体更密集，利于多跳关系召回。
- 孤立实体占比 11.1%，低于 Open RAGBench 的 14.5%，说明新闻语料的实体更容易被关系边连通。
- 140 note 中 1 个 ingest 失败（`--graphiti-continue-on-ingest-error` 容错跳过），不影响整体评测。

> 复现命令：见下方 MultiHopRAG 评估结果中的 ingest 命令；图谱统计直接对 `group_id` 跑 Cypher `MATCH (n:Entity {group_id:$g}) RETURN count(n)`。


## Open RAGBench 评估结果

使用 [evals/open_ragbench/](../evals/open_ragbench/) 框架对 Ask 流程进行检索质量评估。评估数据集为 `vectara/open_ragbench` (pdf/arxiv split)，corpus_mode=relevant。

评估口径分两类：

- **主回归口径**：`current_runtime_ask`，直接执行生产 `AgentRuntime.execute_ask()`，会走真实 `QueryUnderstanding -> RetrievalPlan -> graph/local/web -> EvidenceItem -> ContextPack -> generation -> verifier/retry` 链路。
- **诊断 proxy**：`ask_pipeline*` 系列，只评估检索代理路径，不生成答案、不跑 verifier，主要用于拆 planner / rewrite / local / graph 的影响，不再作为最终 Ask 效果指标。

### 生产 Ask 主回归（30 queries）

`current_runtime_ask` 使用 Graphiti ingest manifest 缓存：

```text
--reuse-graphiti
--graphiti-user-id ragbench_eval_30q
--graphiti-manifest evals/open_ragbench/results/graphiti_30q_manifest.json
```

| 指标 | current_runtime_ask |
| --- | ---: |
| **MRR** | **0.596** |
| **Recall@1** | 0.217 |
| **Recall@3** | 0.483 |
| **Recall@5** | 0.583 |
| **Recall@10** | 0.683 |
| **NDCG@5** | 0.511 |
| **NDCG@10** | 0.553 |
| 耗时 | 893.7s |

rank 分布：

- top1 命中：13 / 30
- top3 命中：23 / 30
- top10 命中：25 / 30
- miss：5 / 30

结果文件：[evals/open_ragbench/results/current_runtime_ask_30q.json](../evals/open_ragbench/results/current_runtime_ask_30q.json)

### LLM rerank 对照（30 queries）

LLM rerank 使用 `PERSONAL_AGENT_EXTRACT_*` 配置；本地环境实际选择：

```text
source=langextract
model=qwen3-coder-flash
base_url=https://dashscope.aliyuncs.com/compatible-mode/v1
response_format=strict json_schema
llm_rerank_top_n=20
```

同一批 30 queries、同一 Graphiti manifest 下，对 `current_runtime_ask` 切换 `--ask-reranker llm`：

| 指标 | heuristic ContextPack | LLM rerank | LLM rerank + parent_child v2 |
| --- | ---: | ---: | ---: |
| **MRR** | 0.596 | 0.607 | **0.658** |
| **Recall@1** | 0.217 | 0.217 | **0.283** |
| **Recall@3** | 0.483 | **0.517** | 0.467 |
| **Recall@5** | 0.583 | **0.617** | 0.583 |
| **Recall@10** | 0.683 | 0.700 | **0.783** |
| **NDCG@5** | 0.511 | **0.534** | 0.529 |
| **NDCG@10** | 0.553 | 0.568 | **0.612** |
| 耗时 | 893.7s | 880.7s | 933.9s |

纯 LLM rerank 相对 heuristic 的 query 级 rank 变化：

- 改善：4 / 30
- 退化：2 / 30
- 不变：24 / 30
- bucket 从 `rank6_10=1` 变为 `rank6_10=0`，`rank2_3` 从 10 变为 11，top1 数量保持 13。

`parent_child v2` 相对纯 LLM rerank 的 query 级 rank 变化：

- 改善：8 / 30
- 退化：6 / 30
- 不变：16 / 30
- power-iteration 退化样本从 rank2 修复到 rank1，因为 parent hit 触发补齐了真正相关的 `sec_8`。
- pressure-broadening/biases 样本仍未修复，因为 expected parent/section 没进入候选补齐入口；这属于上游召回问题，不是 rerank 可单独解决。

结论：LLM rerank 不应只拿 parent abstract 直接排序；配合保守 `parent_child` candidate enrichment 后，整体指标明显提升。`parent_child v2` 默认只做 parent -> 高 overlap child 和 child -> parent，不默认补 neighbor，避免引入大量相邻但不直接回答的 section。

结果文件：[evals/open_ragbench/results/current_runtime_ask_30q_llm_rerank.json](../evals/open_ragbench/results/current_runtime_ask_30q_llm_rerank.json)
结果文件：[evals/open_ragbench/results/current_runtime_ask_30q_llm_rerank_parent_child_v2.json](../evals/open_ragbench/results/current_runtime_ask_30q_llm_rerank_parent_child_v2.json)

### 与检索 proxy 的区别

`ask_pipeline` 不是生产 Ask，它只是 runner 内的 retrieval-only proxy。两者差异：

| 项 | ask_pipeline / ablations | current_runtime_ask |
| --- | --- | --- |
| 定位 | 检索诊断 proxy | 生产 Ask 主回归 |
| 生成答案 | 否 | 是 |
| verifier / retry | 否 | 是 |
| ContextPack | 不走完整生产链路 | 真实 `EvidenceItem -> ContextPack` |
| graph/local 合并 | runner 简化合并 | 生产 `execute_ask()` 合并 |
| 速度 | 较快 | 慢，30q 约 15 分钟 |
| 适用场景 | 拆 planner/rewrite/local/graph | 判断真实用户 Ask 效果 |

因此后续报告里不应再把 `ask_pipeline` 当作主策略。它保留为诊断工具，建议在文档或命令中称为 **Ask retrieval proxy**。

### 检索 proxy / ablation（30 queries，qwen planner + shared plan cache）

| 指标 | ask_pipeline_no_planner | ask_pipeline_no_rewrite | ask_pipeline_local_only | ask_pipeline proxy |
| --- | --- | --- | --- | --- |
| **MRR** | 0.246 | 0.246 | **0.489** | **0.489** |
| **Recall@1** | 0.067 | 0.067 | **0.150** | **0.150** |
| **Recall@3** | 0.217 | 0.217 | **0.417** | **0.417** |
| **Recall@5** | 0.250 | 0.250 | **0.500** | **0.500** |
| **Recall@10** | 0.317 | 0.317 | **0.617** | **0.617** |
| **NDCG@5** | 0.214 | 0.214 | **0.431** | **0.431** |
| **NDCG@10** | 0.242 | 0.242 | **0.478** | **0.478** |
| 耗时 | 32s | 514s | 33s | 470s |

各环节说明：
- **ask_pipeline_no_planner**: 跳过 LLM planner，原始 query 直接跑 Postgres hybrid（纯本地基线）
- **ask_pipeline_no_rewrite**: 保留 planner routing/sub-query，但强制用原始 query（隔离 rewrite 影响）
- **ask_pipeline_local_only**: 保留 planner rewrite，但只跑本地检索（隔离 Graphiti 贡献）
- **ask_pipeline**: retrieval-only proxy（planner + rewrite + graph + local + sub-query），不代表最终生产 Ask

结果文件：[evals/open_ragbench/results/ask_pipeline_ablation_30q_qwen_cached.json](../evals/open_ragbench/results/ask_pipeline_ablation_30q_qwen_cached.json)

关键发现：

1. **qwen/json_schema planner 明显改善 rewrite 后的本地检索**：`ask_pipeline_local_only` 从旧结果 MRR=0.389 / R@10=0.483 提升到 MRR=0.489 / R@10=0.617。旧结果的差距很大程度来自 planner 稳定性和 rewrite 质量。
2. **query rewrite 是主要收益来源**：`no_rewrite` 与 `no_planner` 基本相同，而 `local_only` 大幅提升，说明 routing/sub-query 本身贡献很小，rewrite 才是 Postgres hybrid retrieval 的关键。
3. **proxy 不能衡量最终 Ask**：`ask_pipeline proxy` 的 MRR=0.489，而 `current_runtime_ask` MRR=0.596；生产链路的 ContextPack、graph/local 合并、verifier/retry 和证据装配会继续改善最终排序。
4. **Graphiti 在 proxy 中仍未有效进入 top-k**：`ask_pipeline` 与 `local_only` 指标完全相同，diagnostics 显示 graph 有命中但没有新增进入 top10。这是 proxy 的简化合并限制；Graphiti 收益应以 `current_runtime_ask` 验证。
5. **shared planner cache 已加入 runner**：同一轮 ablation 共享同一份 planner 输出，避免每个策略重复调用 LLM 导致不可比。`local_only` 和 `ask_pipeline` 的 diagnostics 中 `cache_hit=30/30`。

### 后续优化方向

- 将 `current_runtime_ask` 作为 Ask 质量主回归；`ask_pipeline*` 仅作为 retrieval ablation / debug。
- 在 runner 和文档命名上逐步把 `ask_pipeline` 改成 `ask_retrieval_proxy`，减少误读。
- 继续补 raw candidate debug：让 Postgres local retrieval 暴露 lexical/vector 原始候选、分数和 RRF 融合过程。
- Structural retriever 已融入生产 ask 流程，可通过 `--ask-graph-provider structural` / `PERSONAL_AGENT_ASK_GRAPH_PROVIDER=structural` 与 Graphiti 组合或单独使用；后续重点是 `graphiti|structural|hybrid` 的融合权重。
- Graphiti 检索优化：在 R@3/R@5 仍有优势，应继续尝试 episode-only、实体 alias 和关系归一，并以 `current_runtime_ask` 验证收益。
- Rerank 组合评测：用 `--ask-graph-provider graphiti|structural`、`--ask-reranker heuristic|llm`、`--ask-llm-rerank-top-n`、`--ask-context-max-items`、`--ask-context-char-budget` 在同一生产链路内对照，优先看 `current_runtime_ask` 的 MRR/Recall 和 diagnostics。
- 优化 planner 延迟：考虑对高频 query pattern 做 plan 缓存。
- 扩大到 100 queries 验证统计稳定性。
- 加入 answer quality 评估（faithfulness、answer completeness vs gold answer）。

### Graphiti 检索优化（30 queries）

配置优化：

- 新增 `PERSONAL_AGENT_GRAPH_SEARCH_CITATION_LIMIT`，默认 20，用于控制项目侧从 Graphiti edges 中保留多少 citation hits 参与 episode -> note 映射。
- Graphiti `search_result.episodes` 中的 raw episode uuid 也进入 `related_episode_uuids`，作为 citation edge 映射失败时的兜底。
- Open RAGBench runner 增加 `--graph-search-limit` 和 `--graph-search-citation-limit`，可直接组合测试 Graphiti 检索参数。

复用同一份 30q Graphiti manifest，`graphiti_hybrid_rrf` 指标：

| 指标 | graphiti_hybrid_rrf |
| --- | ---: |
| **MRR** | **0.671** |
| **Recall@1** | 0.217 |
| **Recall@3** | 0.583 |
| **Recall@5** | 0.683 |
| **Recall@10** | 0.767 |
| **NDCG@5** | 0.575 |
| **NDCG@10** | 0.606 |
| 耗时 | 679.8s |

结果文件：[evals/open_ragbench/results/graphiti_hybrid_rrf_30q_citation20.json](../evals/open_ragbench/results/graphiti_hybrid_rrf_30q_citation20.json)

结论：Graphiti 独立检索已经有较强召回，R@10=0.767 接近 `current_runtime_ask + LLM rerank + parent_child v2` 的 R@10=0.783。后续真正的收益点是把 graph candidate 更稳定地并入生产 `ContextPack`，并让 LLM rerank 在 local/graph 候选混合池中做最终排序。

### Graphiti 融入生产 ContextPack（30 queries）

把 Graphiti 映射回来的 notes 显式桥接成 `EvidenceItem(metadata.retrieved_by="graphiti")`，让 raw episode 兜底映射不只停留在 `matches`，而是进入生产 `ContextPack` 和 LLM rerank。

| 指标 | parent_child v2 | graph bridge: all | graph bridge: cited_overlap |
| --- | ---: | ---: | ---: |
| **MRR** | 0.658 | **0.666** | 0.653 |
| **Recall@1** | 0.283 | 0.283 | 0.283 |
| **Recall@3** | 0.467 | **0.500** | 0.467 |
| **Recall@5** | 0.583 | **0.650** | 0.567 |
| **Recall@10** | **0.783** | 0.750 | 0.767 |
| **NDCG@5** | 0.529 | **0.570** | 0.521 |
| **NDCG@10** | **0.612** | 0.609 | 0.602 |

结论：

- `graph bridge: all` 对 top-k 前半段收益最大，MRR/R@3/R@5/NDCG@5 最好，适合生产首选。
- `parent_child v2` 的 R@10/NDCG@10 略高，说明 graph candidates 仍会挤掉少量尾部 local 命中。
- `cited_overlap` 过滤过强，未达到预期；后续应做 LLM rerank prompt/候选分层，而不是简单 term overlap 过滤。

默认使用 `PERSONAL_AGENT_ASK_GRAPH_NOTE_EVIDENCE_MODE=all`，并保留 `none/cited_overlap` 方便回归。

#### 组合 Structural retriever（30 queries）

生产 `StructuralRetrieverStore` 的定位**不是替换 Graphiti**，而是作为另一路检索 provider 与 Graphiti **组合**进入同一个 ContextPack。通过 `AskConfig.graph_provider` / `PERSONAL_AGENT_ASK_GRAPH_PROVIDER` / runner 参数 `--ask-graph-provider graphiti|structural` 切换或叠加。

实现边界：

- Graphiti 是实体/关系知识图谱，需要 LLM 抽取 entity/relation 并写入 Neo4j。
- Structural retriever 是 parent-section 结构索引，不做实体摄取，不写 Neo4j；它从 Postgres `knowledge_notes` 读取 parent note 与 chunk note，构建 token/IDF + section/doc score propagation 的轻量索引。
- Structural 索引按 `user_id + filters + note_count + note.updated_at + parent/chunk signature` 做缓存失效；因此不需要实体 ingestion，但仍具备渐进式缓存重建能力。
- Structural 命中的 notes 会以 `EvidenceItem(metadata.retrieved_by="structural")` 进入同一个 ContextPack，后续 LLM rerank、生成和 verifier 与 Graphiti 完全共用——两路证据在同一候选池里融合。

同一批 30 queries，`current_runtime_ask + llm rerank + parent_child + graph_note_evidence=all`，对照单独使用各 provider 的指标：

| 指标 | Graphiti bridge | Structural provider |
| --- | ---: | ---: |
| **MRR** | 0.666 | **0.686** |
| **Recall@1** | 0.283 | **0.300** |
| **Recall@3** | **0.500** | 0.467 |
| **Recall@5** | **0.650** | 0.583 |
| **Recall@10** | 0.750 | **0.850** |
| **NDCG@5** | **0.570** | 0.545 |
| **NDCG@10** | 0.609 | **0.647** |
| 耗时 | 989.5s | **448.2s** |

结果文件：

- [evals/open_ragbench/results/current_runtime_ask_30q_llm_parent_child_graph_bridge.json](../evals/open_ragbench/results/current_runtime_ask_30q_llm_parent_child_graph_bridge.json)
- 30q production ask 对照结果见 [evals/open_ragbench/results/](../evals/open_ragbench/results/)。

补充说明：曾尝试用同样参数重跑 `graph_provider=graphiti` 并复用 manifest，但 30 分钟超时，未写出完整结果；因此表中 Graphiti bridge 使用已完成的同链路结果。

逐 query diff：

- Structural 的主要收益是宽召回：R@10 从 0.750 提升到 0.850，耗时约减半。它在 "option pricing / PDV""power iteration""chaos and entropy" 等 query 上把目标文档或章节提前。
- Graphiti bridge 的优势在 top-k 前半段：R@3/R@5/NDCG@5 更好，说明实体/关系图在部分主题定位和摘要级父节点补位上仍有价值。
- Structural 的明显退化 query 包括 "multilevel modeling in DIF analysis""mixed strategy profile payoff""common randomness coordination"，主要表现为目标仍在 top10 内，但父节点或目标 section 被排到更后。

组合判断：

- 两路 provider **能力互补**：structural 提供 deterministic 宽召回（R@10 更高、更快），Graphiti 提供实体/关系事实和 top-k 前半段精度（R@3/R@5/NDCG@5 更好）。这正是把两者放进同一 ContextPack 组合、而非二选一的依据。
- **Graphiti 不应被替换删除**：作为语义知识图谱，它承载实体、关系、alias、事实边和多跳推理；面向人/项目/组织/事件关系记忆时不可替代。
- 下一步优先做 `graph_provider=hybrid`：structural + Graphiti 候选统一进入 LLM rerank/MMR，由 rerank 在混合池里做最终排序，让宽召回和关系精度同时生效。


## MultiHopRAG 评估结果

使用 [evals/multihoprag/](../evals/multihoprag/) 框架评估多跳检索能力。数据集 `yixuantt/MultiHopRAG`（COLM 2024），corpus_mode=relevant，relevance 是每个 query 的全部 evidence 文档对应的 parent note id **集合**（2-4 篇），按 `question_type` 分组。

与 Open RAGBench 的关键差异：

- **多跳 set-relevance**：一个 query 的命中需要跨多篇文档，Recall@k 衡量的是"召回了多少比例的 evidence 文档"，不是单文档命中。
- **chunk 折叠到 parent**：strategy 内部对 chunk note 命中按 `note_id.split("_sec_")[0]` 折叠回 parent，因为 relevance 是 parent 级。
- **null_query 特例**：MultiHopRAG 的 `null_query` 是"无法从语料回答"的负样本，其 relevance 集合命中口径与其它类型不同，Recall 恒为 1.0、MRR 恒为 0.0，仅作分组占位，不代表真实排序质量。

### 渐进式缓存（30 queries）

ingest 写 manifest，后续 `--reuse-graphiti` 复用：

```text
--num-queries 30 --seed 42 --corpus-mode relevant
--graphiti-user-id multihoprag_eval_30q
--graphiti-manifest evals/multihoprag/results/multihoprag_30q_manifest.json
--graphiti-continue-on-ingest-error
```

ingest 规模见上方 [Graphiti Ingest 数据量统计](#multihoprag-30qgrouppersonal-agent-multihoprag_eval_30qnote_modeparent_chunks)（139 episodes，1 error）。ingest + 30q hybrid_rrf 检索合计约 2591s（ingest 与检索在同一 strategy 调用内串行）。

### keyword vs graphiti_hybrid_rrf（30 queries）

| 指标（overall） | keyword | graphiti_hybrid_rrf |
| --- | ---: | ---: |
| **MRR** | 0.442 | **0.589** |
| **Recall@1** | 0.411 | **0.500** |
| **Recall@3** | 0.575 | **0.828** |
| **Recall@5** | 0.747 | **0.919** |
| **Recall@10** | **0.933** | 0.919 |
| **NDCG@5** | 0.374 | **0.566** |
| **NDCG@10** | 0.457 | **0.566** |
| 耗时 | 0.4s | 2591.5s |

按 question_type 分组（MRR / R@3 / R@5 / R@10）：

| 类型 | n | keyword | graphiti_hybrid_rrf |
| --- | ---: | --- | --- |
| inference_query | 8 | 0.667 / 0.469 / 0.698 / 0.938 | **0.792 / 0.708 / 0.865** / 0.865 |
| comparison_query | 6 | 0.653 / 0.361 / 0.583 / 0.944 | **0.889 / 0.806 / 0.944** / 0.944 |
| temporal_query | 7 | 0.571 / 0.333 / 0.619 / 0.833 | **0.857 / 0.762 / 0.857 / 0.857** |
| null_query | 9 | 0.000 / 1.000 / 1.000 / 1.000 | 0.000 / 1.000 / 1.000 / 1.000 |

结果文件：[evals/multihoprag/results/graphiti_hybrid_rrf_30q.json](../evals/multihoprag/results/graphiti_hybrid_rrf_30q.json)

结论：

- **Graphiti 在多跳场景的 top-k 前半段优势显著**：overall MRR 0.442 → 0.589，R@3 0.575 → 0.828，R@5 0.747 → 0.919。实体/关系图把跨文档 evidence 更早、更集中地召回，这正是多跳检索的核心诉求。
- **三类真实多跳 query 全面提升**：inference / comparison / temporal 的 MRR 和 R@3/R@5 都明显高于 keyword，comparison_query 提升最大（MRR 0.653 → 0.889）。
- **keyword 仅在 R@10 略高（0.933 vs 0.919）**：宽松 top-10 下纯词重叠也能凑齐 evidence，但排序质量（MRR/NDCG）远逊；Graphiti 用约 2 个数量级的耗时换取前排精度。

### current_runtime_ask 端到端（30 queries）

复用同一份 30q manifest（`--reuse-graphiti`，无重新 ingest），跑生产 `AgentRuntime.execute_ask`，`graph_provider=graphiti + reranker=llm`，全链路含 generation/verifier：

```text
--reuse-graphiti --ask-graph-provider graphiti --ask-reranker llm
--graphiti-user-id multihoprag_eval_30q
--graphiti-manifest evals/multihoprag/results/multihoprag_30q_manifest.json
```

| 指标（overall） | graphiti_hybrid_rrf（检索 only） | current_runtime_ask（端到端） |
| --- | ---: | ---: |
| **MRR** | **0.589** | 0.375 |
| **Recall@1** | 0.500 | 0.433 |
| **Recall@3** | **0.828** | 0.564 |
| **Recall@5** | **0.919** | 0.681 |
| **Recall@10** | **0.919** | 0.708 |
| **NDCG@5** | **0.566** | 0.350 |
| **NDCG@10** | **0.566** | 0.365 |
| 耗时 | 2591.5s | 2413.0s |

按 question_type 分组（current_runtime_ask，MRR / R@3 / R@5 / R@10）：

| 类型 | n | current_runtime_ask |
| --- | ---: | --- |
| inference_query | 8 | 0.719 / 0.490 / 0.781 / 0.844 |
| comparison_query | 6 | 0.500 / 0.361 / 0.500 / 0.500 |
| temporal_query | 7 | 0.357 / 0.262 / 0.310 / 0.357 |
| null_query | 9 | 0.000 / 1.000 / 1.000 / 1.000 |

结果文件：[evals/multihoprag/results/current_runtime_ask_30q.json](../evals/multihoprag/results/current_runtime_ask_30q.json)

结论（多跳场景下端到端反而低于检索 proxy）：

- **端到端显著低于 retrieval-only**：overall MRR 0.589 → 0.375，R@5 0.919 → 0.681，R@10 0.919 → 0.708。`current_runtime_ask` 的 `AskResult.matches` 只保留进入最终 ContextPack 的证据（`_selected_matches` 按 `context_pack.evidence` 过滤），diagnostics 显示端到端每 query 平均只返回 **4.8 个 match**（expected 平均 1.9，最多 4），而 retrieval-only 直接返回 top-10 候选。多跳 set-recall 需要凑齐 2-4 篇 evidence，被裁剪到 ~5 个的最终证据池会系统性丢尾部 evidence。
- **窄预算不是主因**（见下方 wide-budget 对照，假设被证伪）：把 `context_max_items/char_budget` 从 12/5000 放宽到 24/12000，每 query match 仅从 4.8 升到 5.9，但**所有指标反而下降**（MRR 0.375 → 0.283，R@5 0.681 → 0.614）。说明瓶颈不在预算大小，而在候选进入证据池后的**排序/装配质量**。
- **temporal_query 退化最重**（R@5 0.310）：时间型多跳需要更多并列 evidence；inference_query 受影响最小（R@5 0.781），更依赖单条强相关链。
- **web 检索噪声无害但增加耗时**：日志中多次旧 Firecrawl web fallback 402（额度不足），MultiHopRAG evidence 全在本地语料，不影响 parent-note 指标。
- **下一步**：见下方 wide-budget 对照得出的真实瓶颈与后续方向。

#### wide-budget 对照（证伪窄预算假设，30 queries）

为验证"窄 char_budget 是否为主因"，同参数仅放宽 ContextPack 预算重跑：

```text
--ask-context-max-items 24 --ask-context-char-budget 12000  （其余同上）
```

| 指标（overall） | narrow 12/5000 | wide 24/12000 |
| --- | ---: | ---: |
| **MRR** | **0.375** | 0.283 |
| **Recall@3** | **0.564** | 0.522 |
| **Recall@5** | **0.681** | 0.614 |
| **Recall@10** | **0.708** | 0.642 |
| **NDCG@5** | **0.350** | 0.281 |
| match/query（均值） | 4.8 | 5.9 |
| 耗时 | 2413.0s | 2089.4s |

逐 query recall diff（排除 null_query，21 条）：**better=0 / worse=4 / same=17**。结果文件：[evals/multihoprag/results/current_runtime_ask_30q_wide.json](../evals/multihoprag/results/current_runtime_ask_30q_wide.json)

真实瓶颈（放宽预算无效，反而更差）：

- **更多候选 ≠ 更好**：4 条退化 query 里，2 条（mhr_01728/mhr_02413）wide 返回了**更多** match（9-10 个）但命中**更少** expected——LLM rerank 在更大的多跳候选池里把 expected evidence 排到了 top-10 之外。瓶颈是 **rerank 对多跳混合池的排序质量**，不是能装多少。
- **端到端存在不稳定性（confounder）**：另 2 条（mhr_00653/mhr_00952）wide 直接返回**空结果**（ranked=0, citations=0）。预算变大不可能机械导致 recall 归零，这是端到端链路（LLM rerank/generation/verifier/web fallback 串行）的运行间不确定性。因此单次 narrow-vs-wide 对照本身被噪声污染，不能作为预算结论的唯一依据。
- **下一步（修正后）**：① 评测时关掉 web fallback、固定 rerank 随机性，先消除端到端 confounder，让结果可复现；② 把优化重点从"预算大小"转到"多跳候选 rerank/MMR 排序质量"与 candidate 分层；③ 跑 `--ask-graph-provider structural` 组合对照，再扩到 100q 看统计稳定性。


### Structural + Graphiti 生产 Ask 组合（30 queries）

`graph_provider=hybrid` 表示 Structural retriever 与 Graphiti 同时作为 graph retrieval provider 运行。Structural 提供 parent-section deterministic 宽召回，Graphiti 提供实体/关系事实与 episode -> note 映射；两路候选统一进入生产 `ContextPack`，再经过 `parent_child` candidate enrichment、LLM rerank、生成与 verifier。

复用同一份 MultiHopRAG 30q manifest：

```text
--num-queries 30 --seed 42 --corpus-mode relevant
--strategies current_runtime_ask
--reuse-graphiti
--graphiti-user-id multihoprag_eval_30q
--graphiti-manifest evals/multihoprag/results/multihoprag_30q_manifest.json
--graphiti-continue-on-ingest-error
--ask-graph-provider hybrid
--ask-reranker llm
--ask-candidate-enricher parent_child
--ask-graph-note-evidence-mode all
```

与已有 `current_runtime_ask`（graph_provider=graphiti）和 retrieval-only `graphiti_hybrid_rrf` 的整体对照：

| 指标（overall） | current_runtime_ask / graphiti | current_runtime_ask / hybrid | graphiti_hybrid_rrf retrieval-only |
| --- | ---: | ---: | ---: |
| **MRR** | 0.375 | **0.422** | 0.589 |
| **Recall@1** | 0.433 | **0.461** | 0.500 |
| **Recall@3** | 0.564 | **0.575** | 0.828 |
| **Recall@5** | 0.681 | **0.686** | 0.919 |
| **Recall@10** | **0.708** | 0.706 | 0.919 |
| **NDCG@5** | 0.350 | **0.365** | 0.566 |
| **NDCG@10** | 0.365 | **0.375** | 0.566 |
| 耗时 | 2413.0s | **2353.0s** | 2591.5s |

按 question_type 分组（MRR / R@3 / R@5 / R@10）：

| 类型 | n | current_runtime_ask / graphiti | current_runtime_ask / hybrid |
| --- | ---: | --- | --- |
| inference_query | 8 | **0.719 / 0.490 / 0.781 / 0.844** | 0.542 / 0.365 / 0.531 / 0.562 |
| comparison_query | 6 | **0.500 / 0.361 / 0.500 / 0.500** | 0.333 / 0.250 / 0.333 / 0.333 |
| temporal_query | 7 | 0.357 / 0.262 / 0.310 / 0.357 | **0.905 / 0.548 / 0.762 / 0.810** |
| null_query | 9 | 0.000 / 1.000 / 1.000 / 1.000 | 0.000 / 1.000 / 1.000 / 1.000 |

结果文件：[evals/multihoprag/results/current_runtime_ask_30q_llm_parent_child_hybrid.json](../evals/multihoprag/results/current_runtime_ask_30q_llm_parent_child_hybrid.json)

结论：

- Hybrid 对生产 Ask overall 有小幅提升：MRR 0.375 → 0.422，R@1/R@3/R@5/NDCG 均略升，耗时略低。
- temporal_query 收益显著，说明 Structural 的 deterministic section/doc 传播能补足 Graphiti 在部分时间线问题上的 candidate 覆盖。
- inference_query 与 comparison_query 明显退化，说明 hybrid 仍是“直接合池后交给 LLM rerank”，还缺候选分层、source-aware MMR 或按 query_type 调权；它不是最终融合策略。
- retrieval-only `graphiti_hybrid_rrf` 仍显著高于生产 Ask hybrid，差距主要来自生产链路会经过 planner rewrite、ContextPack budget、LLM rerank、生成/verifier/retry 与 selected matches 裁剪，不能与纯检索策略直接等价。
- 运行中 Firecrawl 多次返回 HTTP 402（credits 不足），且有 2 次 planner 输出 `filters.source_ref_contains` list 导致 parse fallback；指标仍写出完整 30q，但这些噪声会影响端到端生产 Ask 的稳定性。

### 双数据集最终对照（30 queries）

针对上方暴露的问题做了三项低风险优化：

- `RetrievalFilters` 对 string filter 增加容错：当 planner 把 `source_ref_contains` 等字段误输出为 list 时，取第一个非空字符串，避免整个 planner fallback。
- 两个 runner 增加 `--ask-disable-web`，评测时清掉 Firecrawl key，避免 corpus-only 指标混入 web fallback / HTTP 402 噪声。
- LLM rerank prompt 增加多跳/比较/时间问题的 evidence set coverage 指令，并接受 reranker 返回裸 JSON list 的容错格式。

#### Open RAGBench：单跳生产 Ask

复用 `graphiti_30q_manifest.json`，运行：

```text
--strategies current_runtime_ask
--reuse-graphiti
--graphiti-user-id ragbench_eval_30q
--graphiti-manifest evals/open_ragbench/results/graphiti_30q_manifest.json
--ask-graph-provider hybrid
--ask-reranker llm
--ask-candidate-enricher parent_child
--ask-graph-note-evidence-mode all
--ask-disable-web
```

| 指标 | heuristic baseline | LLM + parent_child v2 | Graph bridge all | optimized hybrid |
| --- | ---: | ---: | ---: | ---: |
| **MRR** | 0.596 | 0.658 | 0.666 | **0.721** |
| **Recall@1** | 0.217 | 0.283 | 0.283 | **0.317** |
| **Recall@3** | 0.483 | 0.467 | **0.500** | 0.483 |
| **Recall@5** | 0.583 | 0.583 | **0.650** | 0.600 |
| **Recall@10** | 0.683 | **0.783** | 0.750 | 0.700 |
| **NDCG@5** | 0.511 | 0.529 | **0.570** | 0.561 |
| **NDCG@10** | 0.553 | **0.612** | 0.609 | 0.603 |
| 耗时 | 893.7s | 933.9s | 989.5s | 948.7s |

结果文件：[evals/open_ragbench/results/current_runtime_ask_30q_optimized_hybrid.json](../evals/open_ragbench/results/current_runtime_ask_30q_optimized_hybrid.json)

结论：

- 单跳主指标改善明显：MRR 0.666 → 0.721，top1 也提升到 0.317，说明 hybrid + coverage rerank 对“最前排选中正确 evidence”有帮助。
- R@5/R@10 低于 Graph bridge / parent_child v2，说明 hybrid 仍会把部分尾部 relevant section 挤出 top-k；它更像“提高 top1/MRR”的优化，而不是宽召回优化。
- Open RAGBench 单跳不需要放宽 ContextPack；默认预算即可。

#### MultiHopRAG：多跳生产 Ask

复用 `multihoprag_30q_manifest.json`，运行：

```text
--strategies current_runtime_ask
--reuse-graphiti
--graphiti-user-id multihoprag_eval_30q
--graphiti-manifest evals/multihoprag/results/multihoprag_30q_manifest.json
--ask-graph-provider hybrid
--ask-reranker llm
--ask-candidate-enricher parent_child
--ask-graph-note-evidence-mode all
--ask-context-max-items 24
--ask-context-char-budget 12000
--ask-llm-rerank-top-n 40
--ask-disable-web
```

| 指标（overall） | graphiti runtime | hybrid narrow | optimized hybrid wide | graphiti_hybrid_rrf retrieval-only |
| --- | ---: | ---: | ---: | ---: |
| **MRR** | 0.375 | 0.422 | **0.434** | 0.589 |
| **Recall@1** | 0.433 | 0.461 | **0.464** | 0.500 |
| **Recall@3** | 0.564 | 0.575 | **0.589** | 0.828 |
| **Recall@5** | 0.681 | **0.686** | 0.644 | 0.919 |
| **Recall@10** | 0.708 | 0.706 | **0.733** | 0.919 |
| **NDCG@5** | 0.350 | **0.365** | 0.346 | 0.566 |
| **NDCG@10** | 0.365 | 0.375 | **0.389** | 0.566 |
| 耗时 | 2413.0s | **2353.0s** | 2532.1s | 2591.5s |

按 question_type 分组（optimized hybrid wide，MRR / R@3 / R@5 / R@10）：

| 类型 | n | optimized hybrid wide |
| --- | ---: | --- |
| inference_query | 8 | 0.463 / 0.333 / 0.438 / 0.625 |
| comparison_query | 6 | 0.667 / 0.389 / 0.472 / 0.556 |
| temporal_query | 7 | 0.762 / 0.524 / 0.571 / 0.667 |
| null_query | 9 | 0.000 / 1.000 / 1.000 / 1.000 |

结果文件：[evals/multihoprag/results/current_runtime_ask_30q_optimized_hybrid_wide.json](../evals/multihoprag/results/current_runtime_ask_30q_optimized_hybrid_wide.json)

结论：

- MultiHopRAG overall 只有小幅改善：MRR 0.422 → 0.434，R@3 0.575 → 0.589，R@10 0.706 → 0.733。
- R@5/NDCG@5 下降，说明放宽预算和 coverage prompt 把更多正确 evidence 推进 top10，但前 5 的排序质量变差；多跳仍需要 source-aware MMR / set coverage reranker，而不是简单扩大候选池。
- comparison_query 从 hybrid narrow 的 MRR 0.333 提升到 0.667，但 temporal_query 从 0.905 降到 0.762，说明单一融合权重无法同时服务三类多跳问题。
- 评测已禁用 web fallback，因此不再受旧 Firecrawl 402 影响；仍出现 Graphiti/httpx 异步 client 关闭时的 `Event loop is closed` 噪声，但结果文件已完整写出。

#### Microsoft GraphRAG CLI provider

接入 [microsoft/graphrag](https://github.com/microsoft/graphrag) CLI（本地版本 `graphrag v3.1.0`），新增 `graph_provider=ms_graphrag`。与 Graphiti 不同，Microsoft GraphRAG 是 project-directory 模式：先把 corpus 导出到 `ROOT/input/*.txt`，再运行 `graphrag index` 生成 parquet / LanceDB / community report，最后用 `graphrag query` 生成自然语言 answer。

评估配置：

```text
PERSONAL_AGENT_MS_GRAPHRAG_INDEX_METHOD=fast
PERSONAL_AGENT_MS_GRAPHRAG_QUERY_METHOD=local
completion_model=deepseek-v4-flash
completion_api_base=https://api.deepseek.com
embedding_model=text-embedding-v4
embedding_api_base=https://dashscope.aliyuncs.com/compatible-mode/v1
--ask-graph-provider ms_graphrag
--ask-reranker llm
--ask-disable-web
```

说明：

- Microsoft GraphRAG CLI 的 `query` 输出是 answer 文本，不直接返回本项目的 `KnowledgeNote.id`；runner 因此使用 answer/evidence text 对本地 notes 做投影，结果文件 diagnostics 中标记为 `projection=answer_to_local_notes`。
- 使用 DashScope/Qwen completion 跑 Open RAGBench 时，`community_reports` 阶段出现严格 JSON schema 校验失败：模型返回了 schema 外字段，GraphRAG 反复重试后 3600s 超时。切换到 DeepSeek completion 后两个数据集均完整跑通。
- `fast` index 用于控制时间和成本；它不是 GraphRAG 最重的标准索引配置，因此这里先作为可复现的 CLI provider 对照，不作为 GraphRAG 极限能力结论。

##### 双数据集结果

| 数据集 | 方法 | MRR | R@1 | R@3 | R@5 | R@10 | NDCG@5 | NDCG@10 | 耗时 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Open RAGBench | MS GraphRAG fast | 0.516 | 0.217 | 0.383 | 0.483 | 0.633 | 0.431 | 0.494 | 493.0s |
| Open RAGBench | optimized hybrid | **0.721** | **0.317** | **0.483** | **0.600** | **0.700** | **0.561** | **0.603** | 948.7s |
| MultiHopRAG | MS GraphRAG fast | 0.323 | 0.431 | 0.475 | 0.486 | 0.494 | 0.204 | 0.209 | 802.9s |
| MultiHopRAG | optimized hybrid wide | **0.434** | **0.464** | **0.589** | **0.644** | **0.733** | **0.346** | **0.389** | 2532.1s |

结果文件：

- [evals/open_ragbench/results/current_runtime_ask_30q_ms_graphrag_fast_deepseek.json](../evals/open_ragbench/results/current_runtime_ask_30q_ms_graphrag_fast_deepseek.json)
- [evals/multihoprag/results/current_runtime_ask_30q_ms_graphrag_fast_deepseek.json](../evals/multihoprag/results/current_runtime_ask_30q_ms_graphrag_fast_deepseek.json)
- 对照：[evals/open_ragbench/results/current_runtime_ask_30q_optimized_hybrid.json](../evals/open_ragbench/results/current_runtime_ask_30q_optimized_hybrid.json)
- 对照：[evals/multihoprag/results/current_runtime_ask_30q_optimized_hybrid_wide.json](../evals/multihoprag/results/current_runtime_ask_30q_optimized_hybrid_wide.json)

##### 与 Graphiti / Structural 的差异

| 维度 | Graphiti | Structural retriever | Microsoft GraphRAG CLI |
| --- | --- | --- | --- |
| 数据形态 | 实体/关系/episode 图，写 Neo4j | parent-section 结构索引，读 Postgres notes | 文件项目 + parquet/LanceDB/community reports |
| 更新方式 | note 级 ingest，可复用 manifest | 轻量缓存，按 note signature 失效 | project 级 index，适合批处理 |
| 返回结果 | 可映射 episode/note evidence | 直接返回 note candidates | 默认返回 answer 文本，需要投影回 note |
| 优势 | 多跳 top-k 前半段强 | 宽召回快、稳定 | 社区摘要和全局结构化分析能力强 |
| 短板 | ingest 慢、LLM 抽取成本高 | 不含实体/关系事实 | 与本地 citation/evidence 评价口径不匹配 |

##### 为什么整体效果不理想

- **评价目标不完全匹配**：我们的 IR 指标评的是本地 note id 排序；Microsoft GraphRAG 的 query 更偏“基于社区图生成答案”。answer 文本再投影回 note id 会损失 citation 精度，尤其 MultiHopRAG 这种 evidence set 任务更吃亏。
- **多跳需要 evidence coverage，不只是答案合理**：GraphRAG 生成的答案可能语义正确，但如果没有把 2-4 篇 evidence 文档都显式带回 top-k，Recall@k/NDCG 会低。
- **project-level indexing 成本高**：Open RAGBench 750 notes 下，即使 `fast` index 也依赖 community report 阶段；模型 schema 兼容性不好时会被严格 JSON 校验拖垮。
- **adapter 仍是最小可用集成**：它还没有直接读取 GraphRAG 的 parquet/LanceDB 中间产物来生成 note candidates，而是通过 CLI answer 做反向映射。要公平比较，需要进一步实现“GraphRAG artifacts -> local note evidence”的原生检索层。

结论：Microsoft GraphRAG CLI 可以作为离线图分析和社区摘要 provider 保留，但不建议替换 Graphiti。生产 Ask 的主线仍应是 `Structural + Graphiti hybrid`：Structural 保证宽召回，Graphiti 保证实体/关系事实，LLM rerank/MMR 负责最终 evidence set 排序。GraphRAG 后续优化应集中在 artifact-level retrieval 和 citation 映射，而不是直接用 CLI answer 当检索结果。

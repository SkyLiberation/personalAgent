# Open RAGBench 评估

这个目录提供 `vectara/open_ragbench` 数据集中 `pdf/arxiv` 子集的评估辅助代码。
当前 loader 只保留 `source=text` 的问题，因为项目里的本地检索 baseline 主要处理文本
note 和关系事实。

## 数据集概况

统计口径：`vectara/open_ragbench` 的 `pdf/arxiv` 子集，loader 只保留 `source=text`
的 query。以下数据来自本地 HuggingFace cache snapshot
`63f6b052ff83508b08e242db42263ee708815c26`。

| 项目 | 数量 |
| --- | ---: |
| corpus 文档 | 1000 |
| text-source queries | 1914 |
| abstractive queries | 893 |
| extractive queries | 1021 |
| 被 query 标注为 relevant 的文档 | 387 |
| corpus sections | 18840 |
| 每篇文档 section 数 | min 0 / avg 18.84 / max 198 |
| section 字符数 | min 17 / avg 4452.52 / max 113288 |

当前 adapter 会把数据集转换成项目内部 `KnowledgeNote`：

| `--graphiti-note-mode` | full corpus note 数 | 含义 |
| --- | ---: | --- |
| `parent_sections` | 19840 | 1000 个父文档 + 18840 个 section 子笔记 |
| `parent_only` | 1000 | 只使用父文档 |
| `section_only` | 18840 | 只使用 section 子笔记 |

常用 `corpus_mode=relevant` 抽样规模（`seed=42`）：

| query 数 | relevant docs | sections | `parent_sections` notes | `parent_only` notes |
| ---: | ---: | ---: | ---: | ---: |
| 3 | 3 | 81 | 84 | 3 |
| 20 | 19 | 419 | 438 | 19 |
| 50 | 47 | 1214 | 1261 | 47 |

因此真实 Graphiti eval 在默认 `parent_sections` 模式下，即使 query 数很少，也可能展开成大量
episode；如果只想做 smoke 或策略初筛，优先使用 `--graphiti-note-mode parent_only`。

## 模式

- `corpus_mode=relevant`：只加载当前抽样 query 命中的文档。这个模式速度快，适合本地
  快速迭代，但由于无关候选文档较少，会低估真实检索难度。
- `corpus_mode=full`：加载完整 arxiv corpus 子集。比较不同检索策略时，应优先使用
  这个模式。

## 策略

- `keyword`：评估 `LocalMemoryStore.find_similar_notes`。
- `citation_reranker`：把 section 包装成伪关系边，评估 `rank_graph_citation_hits`。
- `structural`：离线 structural retriever baseline，基于文档-章节图做 section 局部评分，并向父文档/兄弟 section 传播分数。
- `current_runtime_ask`：完整生产 `AgentRuntime.execute_ask()` 路径，会执行生成和 verifier，是 Ask 效果主回归口径；因为很慢，建议复用 Graphiti manifest 后再跑。
- `ask_pipeline`：Ask retrieval proxy，运行 planner、local/graph 检索和 sub-query 检索，但不做答案生成、不跑 verifier；输出统一 note id，并在 JSON 中写入 query 级 diagnostics。它只用于诊断，不代表最终生产 Ask 效果。同一轮 ablation 会共享 planner 输出，避免重复调用 LLM 导致策略不可比。
- `ask_pipeline_no_rewrite`：保留 planner routing/sub-query，但强制使用原始 query，用于隔离 query rewrite 的影响。
- `ask_pipeline_local_only`：保留 planner rewrite，但只跑本地 Postgres 检索，用于隔离 Graphiti 贡献和耗时。
- `ask_pipeline_no_planner`：跳过 planner，直接用原始 query 跑当前 Postgres hybrid retrieval，用作当前本地检索基线。
- `graphiti_<graph_strategy>`：把 corpus 写入 Graphiti 后，使用对应 graph strategy 的
  `search_config` 执行真实图谱检索，例如 `graphiti_hybrid_rrf`。

注意：`citation_reranker` 不会真正执行 Graphiti search，它只隔离评估项目侧的关系事实排序层。
要比较 Graphiti 检索策略，请使用 `graphiti_*` 策略。
`ask_pipeline` 的 graph 命中会通过 `episode_uuid -> note_id` 映射后再参与指标计算，避免 episode id 与 note id 混排导致 Recall/MRR 偏低。
但 `ask_pipeline` 仍只是检索代理；最终 Ask 质量请看 `current_runtime_ask`。
生产 Ask 的 rerank 可通过配置或 runner 参数切换：默认 `heuristic`，可用 `--ask-reranker llm`
启用 LLM listwise rerank，并用 `--ask-llm-rerank-top-n`、`--ask-context-max-items`、
`--ask-context-char-budget` 做组合测试。rerank 前的 parent/child 候选补齐默认开启，可用
`--ask-candidate-enricher none` 关闭做 ablation。

## 示例

快速 smoke run：

```powershell
uv run pytest evals/open_ragbench --num-queries 3 -q
```

比较几个本地策略并写出 JSON 报告：

```powershell
uv run python -m evals.open_ragbench.runner `
  --num-queries 50 `
  --corpus-mode relevant `
  --strategies keyword,citation_reranker,structural `
  --output evals/open_ragbench/results/latest.json
```

对 Ask retrieval proxy 做 ablation 并输出 query 级 diagnostics：

```powershell
uv run python -m evals.open_ragbench.runner `
  --num-queries 30 `
  --corpus-mode relevant `
  --strategies ask_pipeline_no_planner,ask_pipeline_local_only,ask_pipeline_no_rewrite,ask_pipeline `
  --reuse-graphiti `
  --graphiti-user-id ragbench_eval_30q `
  --graphiti-manifest evals/open_ragbench/results/graphiti_30q_manifest.json `
  --output evals/open_ragbench/results/ask_pipeline_ablation.json
```

复用已有 Graphiti ingest 缓存，跑生产 Ask 主回归：

```powershell
uv run python -m evals.open_ragbench.runner `
  --num-queries 30 `
  --corpus-mode relevant `
  --strategies current_runtime_ask `
  --reuse-graphiti `
  --graphiti-user-id ragbench_eval_30q `
  --graphiti-manifest evals/open_ragbench/results/graphiti_30q_manifest.json `
  --output evals/open_ragbench/results/current_runtime_ask_30q.json
```

比较生产 Ask 的启发式 rerank 和 LLM rerank：

```powershell
uv run python -m evals.open_ragbench.runner `
  --num-queries 30 `
  --corpus-mode relevant `
  --strategies current_runtime_ask `
  --ask-candidate-enricher parent_child `
  --ask-graph-note-evidence-mode all `
  --ask-reranker llm `
  --ask-llm-rerank-top-n 20 `
  --reuse-graphiti `
  --graphiti-user-id ragbench_eval_30q `
  --graphiti-manifest evals/open_ragbench/results/graphiti_30q_manifest.json `
  --output evals/open_ragbench/results/current_runtime_ask_30q_llm_rerank.json
```

2026-06-02 的 30q 对照结果：`qwen3-coder-flash` strict `json_schema` LLM rerank
相对默认 heuristic 有小幅正收益，MRR 0.596 -> 0.607，Recall@10 0.683 -> 0.700。
加入保守版 `parent_child` candidate enrichment 后，MRR 进一步到 0.658，Recall@10 到 0.783，
NDCG@10 到 0.612。该版本只补 parent 命中的高 overlap child sections 和 child 命中的
parent，不默认补 neighbor chunks。

进一步把 Graphiti 映射回来的 notes 桥接进生产 ContextPack 后，`--ask-graph-note-evidence-mode all`
在 30q 上达到 MRR 0.666、Recall@5 0.650、NDCG@5 0.570；但 Recall@10 从 0.783 降到
0.750，说明 graph candidate 会挤掉少量尾部 local 命中。保留 `none/all/cited_overlap`
三种模式用于后续回归。

比较真实 Graphiti 检索策略：

```powershell
uv run python -m evals.open_ragbench.runner `
  --num-queries 20 `
  --corpus-mode relevant `
  --strategies graphiti_hybrid_rrf,graphiti_edge_rrf `
  --graph-search-citation-limit 20 `
  --graphiti-user-id ragbench_eval_graphiti `
  --output evals/open_ragbench/results/graphiti-latest.json
```

2026-06-02 复用 30q manifest 的 `graphiti_hybrid_rrf` 结果：MRR 0.671，
Recall@10 0.767，NDCG@10 0.606。当前 Graphiti 独立检索已经有较强召回，
后续重点是让生产 `current_runtime_ask` 更稳定地把 graph candidate 纳入 ContextPack。

如果 `add_episode` 的边解析随图谱增长变慢，可以先用父文档粒度跑 smoke：

```powershell
uv run python -m evals.open_ragbench.runner `
  --num-queries 3 `
  --corpus-mode relevant `
  --strategies graphiti_hybrid_rrf `
  --graphiti-note-mode parent_only `
  --graphiti-continue-on-ingest-error `
  --output evals/open_ragbench/results/graphiti-parent-only-smoke.json
```

首次运行会清理并重建 `--graphiti-user-id` 对应的 Graphiti group，并把
`episode_uuid -> note_id` 映射写入 `evals/open_ragbench/results/graphiti_manifest.json`。
后续如果 corpus、query sample 和 user id 不变，可以加 `--reuse-graphiti` 复用已入图数据：

```powershell
uv run python -m evals.open_ragbench.runner `
  --num-queries 20 `
  --corpus-mode relevant `
  --strategies graphiti_hybrid_mmr,graphiti_edge_node_distance `
  --graphiti-user-id ragbench_eval_graphiti `
  --reuse-graphiti
```

当候选策略的运行时间可以接受后，使用 `--corpus-mode full` 做更公平的检索比较。

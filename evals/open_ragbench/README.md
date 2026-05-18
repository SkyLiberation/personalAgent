# Open RAGBench 评估

这个目录提供 `vectara/open_ragbench` 数据集中 `pdf/arxiv` 子集的评估辅助代码。
当前 loader 只保留 `source=text` 的问题，因为项目里的本地检索 baseline 主要处理文本
note 和关系事实。

## 模式

- `corpus_mode=relevant`：只加载当前抽样 query 命中的文档。这个模式速度快，适合本地
  快速迭代，但由于无关候选文档较少，会低估真实检索难度。
- `corpus_mode=full`：加载完整 arxiv corpus 子集。比较不同检索策略时，应优先使用
  这个模式。

## 策略

- `keyword`：评估 `LocalMemoryStore.find_similar_notes`。
- `citation_reranker`：把 section 包装成伪关系边，评估 `rank_graph_citation_hits`。
- `graphrag`：离线 GraphRAG-style baseline，基于文档-章节图做 section 局部评分，并向父文档/兄弟 section 传播分数。
- `graphiti_<graph_strategy>`：把 corpus 写入 Graphiti 后，使用对应 graph strategy 的
  `search_config` 执行真实图谱检索，例如 `graphiti_hybrid_rrf`。

注意：`citation_reranker` 不会真正执行 Graphiti search，它只隔离评估项目侧的关系事实排序层。
要比较 Graphiti 检索策略，请使用 `graphiti_*` 策略。

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
  --strategies keyword,citation_reranker,graphrag `
  --output evals/open_ragbench/results/latest.json
```

比较真实 Graphiti 检索策略：

```powershell
uv run python -m evals.open_ragbench.runner `
  --num-queries 20 `
  --corpus-mode relevant `
  --strategies graphiti_hybrid_rrf,graphiti_edge_rrf `
  --graphiti-user-id ragbench_eval_graphiti `
  --output evals/open_ragbench/results/graphiti-latest.json
```

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

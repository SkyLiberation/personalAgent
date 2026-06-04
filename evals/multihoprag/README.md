# MultiHopRAG 评估

这个目录提供 `yixuantt/MultiHopRAG` 数据集（COLM 2024）的检索评估辅助代码。
它与 [`../open_ragbench/`](../open_ragbench/) 并列：两者共享 IR 指标实现和 Graphiti
ingest 缓存逻辑，但数据集语义不同。

## 与 Open RAGBench 的区别

| 维度 | Open RAGBench | MultiHopRAG |
| --- | --- | --- |
| 跳数 | 单跳：1 query → 1 relevant doc + 1 section | 多跳：1 query → 2-4 个 evidence doc |
| relevance | 单个 (section_id, parent_id) | **set**（多个 evidence doc 的 parent note id） |
| corpus 结构 | 论文带 sections | 新闻文章整篇 body（无 sections） |
| query 类型 | abstractive / extractive | **inference / comparison / temporal / null** |
| 指标口径 | 整体 MRR/Recall@k/NDCG@k | 整体 + **按 question_type 子分组** |

## 数据集概况

- corpus：约 609 篇新闻文章，字段 `{title, author, source, published_at, category, url, body}`。
- queries：2556 条，字段 `{query, answer, question_type, evidence_list}`；每条 evidence
  `{title, author, url, source, category, published_at, fact}`。
- 文档无显式 id → 用文章 `url` 作唯一键，note id 用 `mhr_{sha1(url)[:16]}`。
- query 无显式 id → 稳定排序后赋 `mhr_{index:05d}`。

## Note 切分

文章 body 无 sections，统一用**生产切分器** `personal_agent.core.chunking.chunk_content`
按标题/段落切 chunk，保证与真实 capture 流程一致。`--note-mode`：

| 模式 | 含义 |
| --- | --- |
| `parent_only` | 每篇文章 1 个 parent note |
| `parent_chunks`（默认） | parent note + 按段落切的 chunk child notes |
| `section_only` | 只保留 chunk child notes |

relevance 始终在 **parent 级**判定：任意 chunk 命中都折叠回其 parent，再与 query 的
evidence parent 集合求交。

## 渐进式缓存

与 open_ragbench 完全一致，避免 Graphiti ingest 重复跑：

1. **抽样**：`--num-queries 30 --seed 42` 固定抽样，先跑 30q smoke。
2. **corpus_mode**：`relevant`（只装载抽样 query 命中的 evidence 文档，快）/
   `full`（全 609 篇，公平对比）。
3. **进程内 cache**：同次运行多策略复用 ingest 结果。
4. **跨进程 manifest**：`--reuse-graphiti` + `multihoprag_30q_manifest.json`，匹配则跳过
   ingest，否则只增量 ingest 新 notes。

典型流程：30q 写 manifest → 100q `--reuse-graphiti` 增量 → `--corpus-mode full` 公平对比。

## 策略

- `keyword`：关键词 overlap baseline（parent+chunk notes，命中折叠回 parent）。
- `citation_reranker`：把 chunk 包成伪关系边，评估 `rank_graph_citation_hits`，再映射回 parent。
- `graphrag`：离线 GraphRAG-style baseline，chunk 局部评分 + 向 parent 传播。
- `graphiti_<strategy>`：把 corpus 写入 Graphiti 后跑真实图谱检索，例如 `graphiti_hybrid_rrf`。
- `current_runtime_ask`：完整生产 `AgentRuntime.execute_ask()` 路径（含生成 + verifier），慢，
  建议复用 manifest 后再跑。

## 示例

loader smoke（首次会从 HF 下载到 `data/huggingface/`）：

```powershell
uv run python -c "from evals.multihoprag.loader import load_benchmark; q,d=load_benchmark(num_queries=5); print(len(q), len(d), q[0].question_type)"
```

本地策略 + per-type 报告（无需 Graphiti）：

```powershell
uv run python -m evals.multihoprag.runner `
  --num-queries 30 `
  --corpus-mode relevant `
  --strategies keyword,graphrag `
  --output evals/multihoprag/results/smoke.json
```

生产 Ask 主回归（贵，复用 manifest）：

```powershell
uv run python -m evals.multihoprag.runner `
  --num-queries 30 `
  --corpus-mode relevant `
  --strategies current_runtime_ask `
  --reuse-graphiti `
  --graphiti-user-id multihoprag_eval_30q `
  --graphiti-manifest evals/multihoprag/results/multihoprag_30q_manifest.json `
  --output evals/multihoprag/results/current_runtime_ask_30q.json
```

真实 Graphiti 检索策略：

```powershell
uv run python -m evals.multihoprag.runner `
  --num-queries 30 `
  --corpus-mode relevant `
  --strategies graphiti_hybrid_rrf `
  --graphiti-user-id multihoprag_eval_30q `
  --graphiti-manifest evals/multihoprag/results/multihoprag_30q_manifest.json `
  --output evals/multihoprag/results/graphiti_hybrid_rrf_30q.json
```

输出 JSON 中每个策略含 `metrics`（overall）和 `grouped_metrics`（每种 question_type）。

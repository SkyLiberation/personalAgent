# Microsoft GraphRAG Provider

本文记录 Microsoft GraphRAG (`microsoft/graphrag`) 在本项目中的接入方式，以及它和 Graphiti 的核心差异。

## 接入方式

当前新增 provider：`PERSONAL_AGENT_ASK_GRAPH_PROVIDER=ms_graphrag`。

代码入口：

- [MicrosoftGraphRagStore](../src/personal_agent/ms_graphrag/store.py)
- [RuntimeAskMixin._run_graph_retrieval](../src/personal_agent/agent/runtime_ask.py)
- [Settings.ms_graphrag](../src/personal_agent/core/config.py)

Microsoft GraphRAG 是项目目录式离线索引：

```powershell
graphrag init --root data/ms_graphrag
graphrag index --root data/ms_graphrag --method standard
graphrag query --root data/ms_graphrag --method local --query "..."
```

本项目的 adapter 做了三件事：

1. capture/sync 时把 `KnowledgeNote` 导出为 `ROOT/input/<note-id>.txt`。
2. 可选调用 `graphrag index` 构建 Microsoft GraphRAG artifacts。
3. ask 时调用 `graphrag query`，把生成答案包装成 provider-neutral `GraphAskResult`，再进入统一 `EvidenceItem -> ContextPack -> generation/verifier` 链路。

## Graphiti vs Microsoft GraphRAG

| 维度 | Graphiti | Microsoft GraphRAG |
| --- | --- | --- |
| 更新模型 | 在线/增量 `add_episode` | 离线批处理 `input -> index -> output artifacts` |
| 存储 | Neo4j entity/edge/episode | 本地 GraphRAG 项目目录，主要 artifacts 为 parquet |
| 查询返回 | nodes / edges / fact_refs / citation_hits / episode UUID | 生成答案；CLI 不直接返回本项目 note id |
| 与原文 note 映射 | episode UUID 可回连 `KnowledgeNote.graph.episode_uuid` | 当前需 answer text -> local note projection |
| 适合场景 | 个人记忆、持续写入、实体关系、可追溯 citation | 静态语料、全局/社区摘要、批量 corpus 级分析 |
| 延迟 | ingest/query 都可在线执行，但 LLM 抽取较慢 | index 很重，query 依赖已构建 artifacts |
| 多跳解释 | relation edges + citation hits | community/global/local search 生成解释，citation 映射需额外适配 |

## 评估口径

现有 Open RAGBench / MultiHopRAG IR 指标需要 ranked note ids。Graphiti 原生能通过 citation hit 的 episode UUID 映射到 note id；Microsoft GraphRAG CLI query 主要返回答案文本。

因此 runner 中的 `ms_graphrag` 口径是：

```text
GraphRAG query answer
  -> graph_fact evidence
  -> answer/evidence text projected through local note retrieval
  -> ranked note ids for Recall/MRR
```

这个口径可以用于端到端对照，但不能视为 Graphiti `citation_hits` 的严格等价替代。后续如果需要更公平的检索级对比，应直接读取 Microsoft GraphRAG output artifacts 中的 source/context records，并映射回 `KnowledgeNote`。

## 示例命令

Open RAGBench：

```powershell
$env:PERSONAL_AGENT_MS_GRAPHRAG_ENABLED="true"
$env:PERSONAL_AGENT_MS_GRAPHRAG_ROOT="evals/open_ragbench/results/ms_graphrag_30q"
uv run python -m evals.open_ragbench.runner `
  --num-queries 30 `
  --corpus-mode relevant `
  --strategies current_runtime_ask `
  --ask-graph-provider ms_graphrag `
  --ask-reranker llm `
  --ask-disable-web `
  --output evals/open_ragbench/results/current_runtime_ask_30q_ms_graphrag.json
```

MultiHopRAG：

```powershell
$env:PERSONAL_AGENT_MS_GRAPHRAG_ENABLED="true"
$env:PERSONAL_AGENT_MS_GRAPHRAG_ROOT="evals/multihoprag/results/ms_graphrag_30q"
uv run python -m evals.multihoprag.runner `
  --num-queries 30 `
  --corpus-mode relevant `
  --strategies current_runtime_ask `
  --ask-graph-provider ms_graphrag `
  --ask-reranker llm `
  --ask-disable-web `
  --output evals/multihoprag/results/current_runtime_ask_30q_ms_graphrag.json
```

注意：运行这些命令前，需要安装 `graphrag` CLI，并让 GraphRAG 项目目录内的 `.env/settings.yaml` 配好 LLM 与 embedding。

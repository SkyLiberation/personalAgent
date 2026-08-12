# Open RAGBench 检索组件评测

**本目录只评估检索候选、排序与证据选择，不代表产品最终回答。** 产品 grounded answer 的唯一入口与发布证据是 Conversation 的 `ASK-001A/B`；strategy registry 不包含平行的最终回答 runtime。

## 数据与边界

- 数据通过 `datasets` 加载，默认 split 为 `test`；
- `--corpus-mode relevant` 只加载抽样 query 的相关文档，`full` 加载完整 corpus；
- 输出 MRR、Recall@k、延迟和 query diagnostics；这些是 component metrics，不能替代正式 HTTP E2E；
- Graphiti strategy 可复用 manifest，但 manifest identity 必须匹配 corpus 与切分配置。

## 主要策略

- `keyword`、`citation_reranker`：确定性基线；
- `structural`、`graphiti_*`：结构/图检索；
- `doc_first_*`、`shared_evidence_selector*`：文档优先、fusion 与 evidence selection ablation；
- `ask_retrieve_*`：证据检索组合实验；不生成答案、不运行产品 Completion。

可用策略始终以代码为准：

```powershell
uv run python -m evals.open_ragbench.runner --help
```

## 示例

```powershell
uv run python -m evals.open_ragbench.runner \
  --strategies keyword,structural,doc_first_fusion \
  --num-queries 30 \
  --corpus-mode relevant \
  --output evals/open_ragbench/results/component-comparison.json
```

运行低层回归：

```powershell
uv run pytest evals/open_ragbench tests/test_open_ragbench_structural.py -q
```

## 解释结果

策略提升只能准入“检索机制候选”。若要改变生产 Context/Tool/Agent 行为，必须先用相同自然用户目标运行当前 Conversation baseline；目标改动完成后仍由 Product E2E 证明用户结果、scope、零写入和关键反事实。

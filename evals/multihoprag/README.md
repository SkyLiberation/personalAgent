# MultiHopRAG 检索组件评测

**本目录衡量多跳 evidence set 的召回与排序，不是产品最终回答链。** strategy registry 只包含 retrieval/component 机制；Conversation grounded answer 由 `ASK-001A/B` 从正式 HTTP 入口验证。

## 与 Open RAGBench 的区别

- MultiHopRAG 关注一个问题需要同时召回 2–4 篇证据文档；
- 指标除 MRR/Recall@k 外还关注整组 evidence 的覆盖；
- corpus Note 切分、Graphiti manifest 与 query sampling 必须进入运行 profile，避免不可比结果。

## 策略

保留 keyword、structural、Graphiti/hybrid 等 retrieval-only strategy。所有 strategy 只返回 ranked evidence ids，不生成 FinalMessage，不拥有 Verification 或 Completion。

## 示例

```powershell
uv run python -m evals.multihoprag.runner \
  --strategies keyword,graphiti_hybrid_rrf \
  --num-queries 30 \
  --output evals/multihoprag/results/component-comparison.json
```

可用参数与策略以 runner 为准：

```powershell
uv run python -m evals.multihoprag.runner --help
```

组件指标改善后，若要接入生产，仍需执行 Conversation baseline 与目标 Product E2E；不能把 retrieval-only 分数直接解释为用户答案完成率。

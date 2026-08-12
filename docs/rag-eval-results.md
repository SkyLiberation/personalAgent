# Retrieval 评测结果边界

**历史 `current_runtime_ask` 结果不能代表当前生产 Agent。** 产品最终回答由 Conversation 单一拥有；旧结果文件只是不可发布的历史 artifact，文档不维护第二份数值账本。

当前口径：

- Open RAGBench / MultiHopRAG：retrieval、rerank、evidence selection 组件评测；
- `evals/rag_quality`：冻结 fixture 上的 verifier/scorer 低层回归；
- `ASK-001A/B`：正式 Conversation grounded answer 产品结果；
- `metrics_report`：同 profile E2E 的完成率、token、调用、延迟、恢复与 completeness；
- `release_gate`：证据是否可用于目标 revision 发布。

一次性结果必须由 runner 生成并绑定 dataset/profile/revision；本文不手工复制指标。检索策略改善不能替代 Product E2E，也不能反向定义生产架构。运行说明见 [评测索引](evals/README.md) 与各 `evals/<suite>/README.md`。

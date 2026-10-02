# 工具内部模型用量未进入 Conversation 总账

`TOOL-MODEL-USAGE-HANDOFF-001` 的责任边界是工具执行结果到 Conversation 用量聚合。2026-10-01 完整终态中，Provider 已完成 66 次生产响应，共 1,194,979 tokens；Conversation 记录 62 次 typed 操作和 1,143,604 tokens。分项差额 51,375 tokens 精确等于三次最终核验工具的内部模型响应。直接模型调用的 63 份物理响应与 Journal 三项用量精确相等，内部恢复聚合为 62 次 typed 操作；本问题与[失败重试计量固化记录](completed/model-retry-usage.md)的分支不同。

[实际成本审计](../../.tmp/research-source-reuse-repair-20261001/cost-audit.json)保存完整请求、响应和逐分项等式。`application/conversation/service.py` 消费 `_verify_final` 的工具结果时只增加 `tool_calls`；`tools/interaction_verifier.py` 已取得结构化响应，却没有把模型用量交回总账。因此终态 `provider_usage_complete=true` 不代表全部生产模型成本完整。该路径在本轮未修改。

## 责任与下一边界

Provider 拥有实际调用用量；工具执行方返回 typed 用量事实，包括成功、语义拒绝和契约失败前已完成的响应；Conversation 聚合当前执行事实一次并纳入预算。未知消耗保持未知，不补零。下一候选先盘点工具/agent 内部调用的全部生产消费者，确定唯一传递契约，再以本次三份实际响应验证失败和成功的交接与去重。准入为失败归因阶段，见[Future 队列](../future/design-optimization-backlog.md)，本轮未实施。

## 2026-10-02 最终契约失败调用仍有漏计

诊断补齐后的正式终态共完成 93 个生产响应，2,013,022 tokens；Journal 为 1,945,314。差额输入 57,431、输出 10,277、合计 67,708，精确等于五次最终核验工具的已完成模型响应；五次都因验收项转录失败，仍产生服务方用量。扣除这五次后，直接模型的输入、输出、total 与 Journal 逐项相等，全部请求已经完成，不归为在途调用或本轮选证未提交。证据见[分项等式](../../.tmp/mimo-provider-diagnostics-20261002/recovery-boundary-audit.json)及[完整结果](../../.tmp/mimo-provider-diagnostics-20261002/result.json)。本轮该交接路径未修改，已完成但契约失败的模型响应须纳入后续恢复及预算验证。

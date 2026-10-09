# 工具内部模型用量未进入 Conversation 总账

`TOOL-MODEL-USAGE-HANDOFF-001` 的责任边界是工具执行结果到 Conversation 用量聚合。2026-10-01 完整终态中，Provider 已完成 66 次生产响应，共 1,194,979 tokens；Conversation 记录 62 次 typed 操作和 1,143,604 tokens。分项差额 51,375 tokens 精确等于三次最终核验工具的内部模型响应。直接模型调用的 63 份物理响应与 Journal 三项用量精确相等，内部恢复聚合为 62 次 typed 操作；本问题与[失败重试计量固化记录](completed/model-retry-usage.md)的分支不同。

[实际成本审计](../../.tmp/research-source-reuse-repair-20261001/cost-audit.json)保存完整请求、响应和逐分项等式。`application/conversation/service.py` 消费 `_verify_final` 的工具结果时只增加 `tool_calls`；`tools/interaction_verifier.py` 已取得结构化响应，却没有把模型用量交回总账。因此终态 `provider_usage_complete=true` 不代表全部生产模型成本完整。该路径在本轮未修改。

## 责任与下一边界

Provider 拥有实际调用用量；工具执行方返回 typed 用量事实，包括成功、语义拒绝和契约失败前已完成的响应；Conversation 聚合当前执行事实一次并纳入预算。未知消耗保持未知，不补零。下一候选先盘点工具/agent 内部调用的全部生产消费者，确定唯一传递契约，再以本次三份实际响应验证失败和成功的交接与去重。准入为失败归因阶段，见[Future 队列](../future/design-optimization-backlog.md)，本轮未实施。

## 2026-10-02 最终契约失败调用仍有漏计

诊断补齐后的正式终态共完成 93 个生产响应，2,013,022 tokens；Journal 为 1,945,314。差额输入 57,431、输出 10,277、合计 67,708，精确等于五次最终核验工具的已完成模型响应；五次都因验收项转录失败，仍产生服务方用量。扣除这五次后，直接模型的输入、输出、total 与 Journal 逐项相等，全部请求已经完成，不归为在途调用或本轮选证未提交。证据见[分项等式](../../.tmp/mimo-provider-diagnostics-20261002/recovery-boundary-audit.json)及[完整结果](../../.tmp/mimo-provider-diagnostics-20261002/result.json)。本轮该交接路径未修改，已完成但契约失败的模型响应须纳入后续恢复及预算验证。

## 2026-10-02 引用身份修复后的合法回执用量

最终 ID 报告形成有效 passed 回执后，生产 Provider 合计 1,659,663 tokens，Journal 1,647,159；差额输入 10,138、输出 2,366、total 12,504 精确等于该一次工具模型响应。全部请求已完成，原用户评分的 9,413 tokens 独立计量。扣除工具响应后，直接模型与 Journal 三项相等，见[最终成本审计](../../.tmp/final-criterion-reference-20261002/target-audit.json)。身份绑定修复没有修改这条既存交接；合法和契约失败的工具响应均继续作为本问题的必要反事实。

## 2026-10-08 最终当前稿核验响应仍未交接

新正式轨迹完成 47 份生产响应，1,126,488 tokens；Journal 为 1,091,580。差额输入 32,856、输出 2,052、合计 **34,908**，精确等于一次最终 v6 工具模型响应。独立 grader 的 63,695 tokens 另计，全部 48 份响应完成，无未知服务用量。该问题未修复，不据终态完整标志宣称总账闭合，见[分项审计](../../.tmp/claim-atomic-reference-repair-20261008/product-audit.json)。

初始选证状态修复后的正式轨迹中，生产完成46份SDK响应，722,048 tokens；Journal为666,454。差额 **55,594** 精确等于两次最终核验工具的27,617与27,977；独立评分64,760另计，全部47份响应完成。两次合法报告分别拒绝和接受当前稿，均仍漏交工具内部用量，见[本次分项审计](../../.tmp/research-selection-state-target-20261008/product-audit.json)。实际恢复与当前稿核验成立，不改变本问题的归属和未修复状态。

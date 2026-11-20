# 写作失败前的已完成选证用量未提交

`RESEARCH-SELECTION-USAGE-COMMIT-001` 是[研究未收敛问题](claim-revision-nonconvergence.md)的计量子问题。责任边界为 Conversation 已完成选证响应到 Journal 提交；与[工具内部用量交接](tool-model-usage-handoff.md)及[失败重试计量](completed/model-retry-usage.md)分别处理。

2026-10-02 原正式 E2E 完成 45 个生产 Provider 响应，已知 901,189 tokens；最后 Journal 前缀为 864,407 tokens。差额精确等于末次选证的输入 32,440、输出 4,342、合计 36,782 tokens。随后 writer 请求及两次重试均返回 429，入口返回 503，没有新的 Journal 提交。三次拒绝请求未返回 usage，用量保持未知。原用户结果、实发请求与分项等式见[实际审计](../../.tmp/research-joint-goal-20261002/result.json)。

原选证返回后先更新内存用量，再等待 writer 响应。writer 异常在下一次提交前抛出，已完成的选证用量未持久化。该缺口早于当轮新增的原项校验。

原轨迹未到达覆盖、汇总和最终工具核验。工具内部用量交接按独立问题验收。

## 2026-10-02 选证结构失败的已完成用量

来源归属候选的原正式 E2E 在选证两次截断、缺必填 `reason` 后返回 503，尚未调用 writer。Provider 五份响应合计 61,582 tokens，Journal 前缀 22,187；输入差额 23,011、输出 16,384、合计 39,395 精确等于两份完成选证，见[分项审计](../../.tmp/source-attribution-product-target-20261002/selection-failure-audit.json)。该失败补充异常提交边界；实际额度与结构错误由[选证截断子问题](claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究)拥有。后续候选已保留异常响应并提交真实用量，本次仅静态检查，不把修复代码或旧 Trace 默认用量当作当前计量通过。

## 当时的修复与验证边界

2026-10-02 的修复将完成的选证用量在调用 writer 前提交。结构恢复失败时，由应用异常携带已完成响应的累计用量，在原 Journal 边界提交后继续传播异常。未返回 usage 的请求保留未知，异常响应正文不进入公开错误。该轮仅有[静态检查](../../.tmp/final-revision-comparison-usage-20261002/static-checks.json)，真实失败回放与去重未验证。选证写作链已随 [ADR 0055](../adr/0055-unified-conversation-answer.md)退役。

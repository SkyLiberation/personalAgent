# 写作失败前的已完成选证用量未提交

`RESEARCH-SELECTION-USAGE-COMMIT-001` 是[研究未收敛问题](claim-revision-nonconvergence.md)的计量子问题。责任边界为 Conversation 已完成选证响应到 Journal 提交；与[工具内部用量交接](tool-model-usage-handoff.md)及[失败重试计量](completed/model-retry-usage.md)分别处理。

2026-10-02 原正式 E2E 完成 45 个生产 Provider 响应，已知 901,189 tokens；最后 Journal 前缀为 864,407 tokens。差额精确等于末次选证的输入 32,440、输出 4,342、合计 36,782 tokens。随后 writer 请求及两次重试均返回 429，入口返回 503，没有新的 Journal 提交。三次拒绝请求未返回 usage，用量保持未知。原用户结果、实发请求与分项等式见[实际审计](../../.tmp/research-joint-goal-20261002/result.json)。

失败发生时，`service.py` 在选证返回后通过 `_record_model_usage` 更新内存用量，合法选择进入 `_decide` 等待 writer；writer 异常在下一次 `_commit` 前抛出，已完成选证没有持久化。成功选择的计量语句及 writer 派发分支在当时起点源码与候选中相同，新增原项校验没有触发拒绝。现行[及时提交候选](to_verify/research-selection-usage-commit.md)已按用户要求接入，真实回放及正式验收延后；准入由[Future 队列](../future/design-optimization-backlog.md)拥有。

修复机制及防护由候选正文拥有；下一验收消费真实选证与 writer 失败轨迹，核对全部完成用量、恢复去重及未返回 usage 的诊断，再按原入口验证。原轨迹没有到达覆盖、汇总及最终工具核验，工具内部用量交接按独立问题验收。

## 2026-10-02 选证结构失败的已完成用量

来源归属候选的原正式 E2E 在选证两次截断、缺必填 `reason` 后返回 503，尚未调用 writer。Provider 五份响应合计 61,582 tokens，Journal 前缀 22,187；输入差额 23,011、输出 16,384、合计 39,395 精确等于两份完成选证，见[分项审计](../../.tmp/source-attribution-product-target-20261002/selection-failure-audit.json)。该失败补充异常提交边界；实际额度与结构错误由[选证截断子问题](claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究)拥有。后续候选已保留异常响应并提交真实用量，本次仅静态检查，不把修复代码或旧 Trace 默认用量当作当前计量通过。

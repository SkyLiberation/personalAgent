# 写作失败前的已完成选证用量未提交

`RESEARCH-SELECTION-USAGE-COMMIT-001` 是[研究未收敛问题](claim-revision-nonconvergence.md)的计量子问题。责任边界为 Conversation 已完成选证响应到 Journal 提交；与[工具内部用量交接](tool-model-usage-handoff.md)及[失败重试计量](completed/model-retry-usage.md)分别处理。

2026-10-02 原正式 E2E 完成 45 个生产 Provider 响应，已知 901,189 tokens；最后 Journal 前缀为 864,407 tokens。差额精确等于末次选证的输入 32,440、输出 4,342、合计 36,782 tokens。随后 writer 请求及两次重试均返回 429，入口返回 503，没有新的 Journal 提交。三次拒绝请求未返回 usage，用量保持未知。原用户结果、实发请求与分项等式见[实际审计](../../.tmp/research-joint-goal-20261002/result.json)。

`service.py` 在选证返回后通过 `_record_model_usage` 更新内存用量，合法选择进入 `_decide` 等待 writer；writer 的调用异常在下一次 `_commit` 前抛出，已经完成的选证事实没有持久化。实际成功选择的计量语句及 writer 派发分支，在本轮开始前源码与候选中相同；新增原项校验未在这次选择中触发拒绝。该缺口已有工程归因，当前没有生产修正，准入由[Future 队列](../future/design-optimization-backlog.md)拥有。

下一设计由 Conversation 对每个已经返回的 Provider 用量事实及时提交，后置 writer 的可用性独立处理；沿用 Journal 和现行模型响应契约，避免重复计费。验收消费本次真实选证与 writer 失败轨迹，核对全部已完成用量、恢复后的去重及未知用量表达，再按原入口验证。当前覆盖、汇总与最终工具核验未到达，因此本轮没有验证工具内部用量交接。

# 按实际输入复用来源核验结果

**已修复 `CLAIM-SOURCE-REVIEW-REUSE-001`：集合其他项变化时，未变来源核验输入消费 Journal 中最新适用的已完成报告。** 通过和拒绝采用同一适用性判据；修改项继续核验整条 claim。

原正式轨迹仅修改 c3，却重新核验与上一版完整 SDK 参数相同的 c1；后一响应长度截止而无正文，最终入口超时。原始失败由[历史封存报告](../../../.tmp/research-retained-reference-repair-20261001/REPORT.md)拥有。

## 解决机制

`ResearchReview` 继续唯一保存已完成模型判断，包含原集合版本、claim 身份、来源判据版本及报告。Conversation 在同一次 `respond` 的固定模型绑定范围内，从 Journal 找到当前 claim 最新适用报告。适用条件为集合身份与 owner 相同、claim 正文和引用相同、canonical binder 恢复的完整原文及来源身份相同、核验契约版本相同。集合其他项的 revision 变化不使这些输入失效。

当前所有引用先经过 binder。输入相同便消费原判断；拒绝报告同样复用并交回选证及写作者，不另写“已通过”状态或复制旧报告。修改后的整条 claim、新增项、改变引用或原文、改变判据及新的 `respond` 调用重新核验。显式 `recheck_claims` 重新核验全部项。全部项具有适用通过报告后，仍检查当前完整集合的事实覆盖，后续独立汇总与最终交付沿原门禁执行。

## 防护与责任

claim 正文和引用由 `ResearchClaims` 拥有；原文与来源身份由执行事实和 binder 拥有；开放语义由 Verifier 判断；复用条件由 Runtime 检查。最新适用拒绝优先于更早通过，未形成合法报告的请求没有可复用事实。selector 和 writer 从相同适用性函数选择修订反馈，防止其他项的新通过遮住已有拒绝。

复用范围通过当前调用开始时的输入边界限定，模型与提供方配置变化在新的调用中建立新边界。判据版本随原模型判断保存，不引入持久缓存、通过镜像或新运行开关。


## 决定性证据

2026-10-01 一个原中文正式入口 target 实际消费 32 次未变项报告；12 次修订后的整条 claim 均发出新的来源核验请求。7 条 claims 在第 13 版具有适用通过报告，随后完整覆盖、独立汇总与最终门禁到达。原用户 E2E 因独立评分器无有效输出仍为 `0/1`，结果由[评测记录](../../evals/02-current-case-inventory.md#2026-10-01-来源报告复用与结构化修订反馈)拥有；机制消费见[实际审计](../../../.tmp/research-source-reuse-repair-20261001/reuse-audit.json)。

[同轨迹责任反事实](../../../.tmp/research-source-reuse-repair-20261001/actual-reuse-counterfactual.json)使用本次真实第 8 版、已完成的现行报告及原文，在隔离代码身份中只移除复用决定：消融下一请求为 c1，现行下一请求为已修改 c4；前三项来源输入、报告、Journal 及 Prompt 保持。请求分别与实际旧 c1 和实际 c4 的实发输入相同，包括 Adapter 前缀。新增模型调用为 0，该回放不计第二个 Product E2E。

[历史边界回放](../../../.tmp/research-source-reuse-repair-20261001/replay.json)另覆盖最新拒绝优先、契约版本失效、新调用失效与拒稿原文交接。旧报告恢复新形状的部分只属于条件算法证据；正式轨迹和上述现行报告反事实共同证明生产消费。

[LangGraph Functional API](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/functional-api.mdx)恢复已完成 task/subgraph；[Temporal Tasks](https://docs.temporal.io/tasks)从事件历史恢复 Activity 结果。两份独立 A 级实现于 2026-10-01 核对，本工程使用现有 Journal，并以实际依赖界定结果适用性。

## 失败尝试与重新打开条件

原按集合 revision 重验全部项的机制重复生成相同判断，使未改项承受额外服务方差；本次改为输入适用性。历史版本变化与独立随机 target 的调用差异不作成本消融，原文未变也不自动证明模型判决准确。

若输入改变仍消费旧报告、最新拒绝被旧通过覆盖、显式重验被跳过，或未变项再次因其他项 revision 变化被重复核验，则重新打开本问题。经验入口为[按判断输入决定失效](../../interview/10-development-pitfalls.md#11-按判断输入决定结果失效)。

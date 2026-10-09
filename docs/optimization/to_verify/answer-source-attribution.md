# 最终稿具体来源归属

`ANSWER-NORMATIVE-SCOPE-001` 的本候选修复最终稿把一篇资料的流程归到另一篇资料的问题。[失败事实及实际输入审计](../normative-scope-attribution.md#2026-10-02-实际流程步骤的来源错配)确认引用目录中的原文和 URL 正确，局部修订留下含混指代，汇总确定了错误页面归属；最终核验未取得已物化的逐段原文。

## 机制与责任

Conversation 保留 canonical binder 按最终每段 references 恢复的 `CitedDraftUnit`，将原文和 `CitationSource.source_url` 交给现有最终核验。工具参数要求 units 与 segments 数量、顺序及正文逐字对应；每段只取得自身实际引用。原文与来源身份由执行事实和 Runtime 拥有，模型判断具体来源支持关系。

研究来源 Verifier 继续判断 claim 的事实支持。最终 Verifier 按整段上下文解析“其、该页、上述资料”等指代，对照所称页面实际返回的原文；多来源共同支持的论断保留全部相关引用。写作者在局部修订改变前文来源时，把受影响的相邻指代句纳入最小连续编辑范围。独立汇总按具体说明关联现有引用，并从 `ResearchBasis.sources` 获取对应 URL。

初次来源归属验证使用 writer v16、synthesis v2、research final v4，复用已有模型请求、typed 引用及 binder。当前来源归属机制继续保留；同日[修订比较候选](final-revision-comparison.md)更新汇总与最终核验版本，新身份已在2026-10-08正式入口两次物化逐段原文与URL并验收当前稿；本文的完整用户门禁仍待取得，最新独立失败是章节非规范性限定未取证。权威调用链见 [ADR 0032](../../adr/0032-conversation-research-claims.md)。

## 证据与剩余门禁

[预声明](../../../.tmp/source-attribution-repair-20261002/plan.json)固定原中文任务、mimo-v2.6-flash、thinking、原预算、暂停机制和已资格 v8 评分。真实错稿与仅改出处的合法多来源对照各一次，条件局部来源归属资格 2/2；真实拒绝反馈连续驱动汇总修订，实际出处修正，最终核验 passed。独立评分因新稿把非穷尽列举改成完整四步枚举而拒绝，连续用户结果资格 0/1，见[审查](../../../.tmp/source-attribution-repair-20261002/continuation-review.json)。

该反例没有再次出现错页归属；整体候选仍缺原正式入口的完整验收及语义回归排除。候选保留待验证身份，具体枚举范围的独立失败由[问题入口](../claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举)拥有，不把条件局部成功固化为完整产品能力。

局部停止已封存，原连续资格0/1保持。随后依据用户明确要求“优化必须接入真实路径，跑对应E2E”，[单独预声明](../../../.tmp/source-attribution-product-target-20261002/plan.json)从空资料运行原 `test_conversation_research_review_001.py` 一个样本一次：固定历史 basis 的枚举范围反例没有覆盖当前写作者自主取证及现有最终核验的正式消费路径，本次没有追加生产或评分修补。该执行改变了原“局部完整评分通过后才跑target”的先后门槛，原门槛失败与审查决定都保留，不改写原归档。

正式预算保持 2M tokens、32 回合、48 工具和7200秒HTTP；完整用户结果与来源归属检查点分别验收。正式target失败即封存并归因，不追加同向提示、修改评分契约或重复采样寻找通过。反例直接否定来源归属机制或证明新增输入引入回归时，撤回对应生产部分；未到达的正式边界单列。枚举范围候选后续按用户要求先实现、统一延后测试；实际状态由[修订比较方案](final-revision-comparison.md)拥有。

本次正式target实际0/1：两次选证响应截断且缺必填 `reason`，入口503，claims未创建，归属候选的生产消费检查点未到达。来源归属条件局部证据保留，完整候选继续待验证；最早阻塞由[选证输出子问题](../claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究)拥有，完整结果及成本由[正式登记](../../evals/02-current-case-inventory.md#2026-10-02-具体来源归属候选的正式入口验证)拥有。

后续正式来源消费已到达，两次Finalv6的段落、原文与来源身份逐字核对成立，未复现旧错页归属；完整用户结果0/1仍保留。[规范性限定取证](normative-context-acquisition.md)拥有新确定的章节层级缺口，当前页面绑定机制保持。正式结果见[登记](../../evals/02-current-case-inventory.md#2026-10-08-选证状态修复后的正式入口结果)。

# Conversation Draft 语义验证隔离设计

本页是[设计优化队列](design-optimization-backlog.md)中 `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001` 的条件设计，只保存尚未闭环的决策、剩余门禁和退出条件。机制候选由[问题总览](../optimization/claim-revision-nonconvergence.md)及其子问题拥有，最新正式结果由[评测文档](../evals/02-current-case-inventory.md#2026-10-02-验收项引用恢复的正式验证)拥有，后续条件局部反例见[来源归属与枚举范围验证](../evals/02-current-case-inventory.md#2026-10-02-具体来源归属与实际反馈修订验证)。

## 1. 尚未解决的问题

**恢复 evidence-first 后，研究与修订仍未稳定交付。** [选证候选](../optimization/to_verify/claim-evidence-selection.md)已按用户要求接回真实生产路径，完整用户结果仍缺通过证据；不能把选中引用、合法编辑、来源支持局部通过或预算内停止当作用户完成。

剩余准入涉及[来源核验一致性](../optimization/claim-verifier-consistency.md)、[具体来源归属候选](../optimization/to_verify/answer-source-attribution.md)及[枚举范围交接](../optimization/claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举)。正文目标与参数范围分别见[片段寻址完成记录](../optimization/completed/claim-fragment-addressing.md)和[参数范围完成记录](../optimization/completed/claim-argument-scope.md)。上一正式轨迹已到达完整覆盖、独立汇总与有效最终核验，仍有来源归属错误；后续条件局部反馈修订恢复出处，却把部分列举改为完整四步流程。原正式用户结果和新局部失败分别保留，当前产品门禁未通过。

随后单独执行的正式target在选证两次截断且缺必填reason处返回503，claims及归属核验未到达。默认额度和用量及时提交已按用户要求接入，真实恢复效果待统一测试；失败事实见[选证输出边界](../optimization/claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究)，保留原thinking、模型、评分及来源归属候选；原局部及正式失败分别计分，实际结果由[最新登记](../evals/02-current-case-inventory.md#2026-10-02-具体来源归属候选的正式入口验证)拥有。

## 2. 责任与保留条件

原始用户 goal 确定事实问题；模型选择信息需求、证据、正文和修订；执行系统拥有实际来源正文、坐标、URL 和失败事实。代码拥有版本、唯一编辑目标、可见引用与选中子集不变量；来源 Verifier 判断提交片段的支持关系，研究覆盖判断事实齐全，最终 Verifier 判断忠实性及用户交付，Completion 绑定同一通过稿。

保留现行唯一研究路径、确定性来源投影和版本绑定；当前行为由 [ADR 0032](../adr/0032-conversation-research-claims.md)及[验证专题](../topics/verification-and-completion.md)拥有。`split_claim`、复合识别和独立文档缺项识别继续按 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)停用。删除动作的自然使用及语义覆盖仍按[单条撤回候选](../optimization/to_verify/claim-deletion.md)验收，不用本轮未触发结果代替。

[确定性坐标反馈](../optimization/completed/research-admission-coordinate-feedback.md)的局部缺陷已修复，不再列为待办；它不承担证据适合性或精确文本复制。既有[动作协议恢复](../optimization/completed/conversation-action-protocol-recovery.md)、[完整基稿交接](../optimization/completed/complete-rejected-draft-handoff.md)及[查询事实保真](../optimization/completed/query-execution-handoff.md)继续保留。保存误路由的独立边界由[准入审计](conversation-research-save-misroute.md)拥有。

## 3. 下一准入边界

### 用户事实要求的逐项覆盖

当前保留[研究与覆盖联合候选](../optimization/to_verify/research-goal-coverage.md#2026-10-02-联合正式验证与保留决定)。剩余门禁为未读必要关系识别、来源反馈与修订范围判别、覆盖恢复的语义保真，以及按原用户目标判断必要性、保持真实声明的来源归属。最新正式轨迹发现客户端结果校验缺项并消费真实修订，后续独立评分复核确认流程步骤被错归到MCP架构页；未展开字段或安全条款不自动成为必答缺项，见[覆盖消费记录](../optimization/to_verify/research-goal-coverage.md#2026-10-02-引用身份修复后的覆盖消费)。原评分及暂停机制保持，停止同向补丁及新增付费样本；原用户结果由[最新评测登记](../evals/02-current-case-inventory.md#2026-10-02-验收项引用恢复的正式验证)拥有。

### 最终修订与计量验收

[修订比较候选](../optimization/to_verify/final-revision-comparison.md)已接入现有最终核验；[计量候选](../optimization/to_verify/research-selection-usage-commit.md)已接入成功及异常提交边界。2026-10-02 接入时尚未调用模型；2026-10-07 [核心校准未成立](../optimization/claim-revision-nonconvergence.md#核验校准的实际结果)，停止同向 Prompt 追加，未进入连续修订及新正式 E2E。下一判断责任重审仍保持实际稿件、真实反馈与原验收项；语义门禁通过后再扩大循环。计量按完成响应与 Journal 等式及恢复去重独立验收，不随本次最终语义失败推断成败。

### 有范围的未知与正常交付

“规范明确没有此要求”是需要证据的外部断言；“依据本次所读片段无法确认”是有范围的认知限制。后者应允许与有据事实一起形成正常答案，由模型依据用户目标、线索与成本决定继续查找或停止。不能暗加每个问题必须有肯定答案的条件，也不能用切换 disposition 绕过原事实及用户结果契约。

当前仅对 `answer` 执行独立语义评分，`limitation` 仍计未交付。若需改变公开结果契约，须先单独声明正反例、原始失败及评分边界；本轮没有该变更。

### 来源支持与片段修订

[一次有界范围校准](../optimization/claim-verifier-consistency.md#2026-09-30-断言范围校准)已经执行，下一次来源变更须重新区分真实缺证、语境范围误读和生成稿范围扩张，不能继续叠加同义判据。相同输入通过与拒绝不自动裁定哪次正确；不得选择较早通过覆盖最新适用拒绝。按实际输入消费最新已完成判断与判决本身的准确性分别验收。

局部修订的已有引用交接由[引用继承完成记录](../optimization/completed/claim-retained-references.md)拥有。来源语义的进一步校准先按[完整实发输入审查](../optimization/claim-verifier-consistency.md#2026-10-01-修订修复后的判决边界审查)区分主体歧义、模态扩大、有效推导与上下文义务强度，固定清晰相邻对照后再进入连续验证。保留 thinking、原模型参数及原始推理。来源报告复用由[固化记录](../optimization/completed/claim-source-review-reuse.md)拥有；[支持范围修订](../optimization/to_verify/claim-supported-scope-repair.md)已真实消费反馈，但仍有范围扩大及正文新增事实未绑定新引用的失败，下一设计聚焦同一修订提交的引用绑定。最终验收项身份由[引用恢复完成记录](../optimization/completed/final-criterion-transcription.md)拥有；保留原评分标准和 thinking。

实际同 SDK 输入还出现有效报告与输出额度耗尽的结构差异。下一验证分别计语义判决、报告可完成性及全部已完成响应的成本；原始空正文没有判决，不计为来源拒绝或通过。

正文目标方案由[Runtime 片段寻址完成记录](../optimization/completed/claim-fragment-addressing.md)拥有；`CLAIM-EDIT-TARGET-TRANSCRIPTION-001` 的事实、契约及决定性证据只维护在该记录中。[片段有界修订](../optimization/to_verify/claim-fragment-revision.md)独立验收编辑范围与内容语义，来源一致性及完整用户结果继续作为本上位问题的准入边界。

正式验证仍须从中文自然任务、空资料和生产入口连续消费真实选证、生成、核验、修订与交付，不注入理想稿或挑选通过版本。未到达阶段单列，调用、tokens、耗时与用户结果分开计分，不从独立随机轨迹宣称成本收益。

## 4. 停止与退出

保持原模型、思考模式、预算及独立用户评分，不扩大昂贵矩阵或重复无增益 E2E。相同边界一次有界修正后仍失败时，停止对应方向局部补丁，按 EVD 重审责任、输入与最小边界。新的机制选择才适用独立 A 级比较；恢复确定性反馈契约依据工程失败和反事实，不用外部资料替代。

后续候选仅在具备责任边界依据和预声明后进入实现。已撤回的整体 Context、固定搜索流程或孤立同义提示不恢复为并行路径；已成立局部机制也不因独立下游失败被撤销。临时接入的移除日期与退出决定由 [ADR 0032](../adr/0032-conversation-research-claims.md#验证风险与退出)拥有；完整用户结果未通过前，不移除本产品问题或声明可发布。

评分输出预算机制见[固化记录](../optimization/completed/research-grader-output-budget.md)，评分资格契约见[固化记录](../optimization/completed/research-grader-qualification.md)，运行步骤见[评测执行](../evals/04-running-and-release.md#研究评分器输出额度)。工具内部模型用量交接由[独立问题](../optimization/tool-model-usage-handoff.md)拥有，成本不得只报直接调用总账。

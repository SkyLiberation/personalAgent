# Conversation Draft 语义验证隔离设计

本页是[设计优化队列](design-optimization-backlog.md)中 `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001` 的活动边界，只保存尚未闭环的决策、剩余门禁和退出条件。机制候选由[统一 Spec](../optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)及对应问题记录拥有，最新正式结果由[评测文档](../evals/02-current-case-inventory.md#2026-10-16-统一研究与最终回答的正式验证)拥有。

## 1. 尚未解决的问题

**统一链的既定 v3 正式续验已完成用户交付并通过独立评分，本例关闭。** 其余已声明 S／F 统一阶段回放和正式缺失回答生命周期按原范围记录，不因未覆盖的泛化疑虑否定已通过用例。

本次真实报告还把“提交前自行核对”扩大为正文必须展示核对清单，归既有目标满足类别的 RV-01／RV-03 用例，单独待校准。后续只按该实际输入审查反馈边界，不新增类别或叠加复核；其他真实来源归属、列举范围及修订问题沿对应既定用例验收，原成绩和失败不改写。

## 2. 责任与保留条件

原始用户目标确定所需内容；模型选择信息需求、证据、正文和修订；执行系统拥有实际来源正文、坐标、URL 和失败事实。代码拥有版本、唯一编辑目标、可见引用与选中子集不变量。现行代码由同一研究模型生成 claims 与最终回答，唯一核验器检查来源支持、回答与 claims 的一致性及原目标覆盖；Completion 绑定同一完整版本和确切通过正文。正式结果与当前行为分别由评测文档和 ADR 拥有。

保留现行唯一研究路径、确定性来源投影和版本绑定；当前行为由 [ADR 0032](../adr/0032-conversation-research-claims.md)及[验证专题](../topics/verification-and-completion.md)拥有。`split_claim`、复合识别和独立文档缺项识别继续按 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)停用。删除动作的自然使用及语义覆盖仍按[单条撤回候选](../optimization/to_verify/claim-deletion.md)验收，不用本轮未触发结果代替。

[确定性坐标反馈](../optimization/completed/research-admission-coordinate-feedback.md)的局部缺陷已修复，不再列为待办；它不承担证据适合性或精确文本复制。既有[动作协议恢复](../optimization/completed/conversation-action-protocol-recovery.md)、[完整基稿交接](../optimization/completed/complete-rejected-draft-handoff.md)及[查询事实保真](../optimization/completed/query-execution-handoff.md)继续保留。保存误路由的独立边界由[准入审计](conversation-research-save-misroute.md)拥有。

## 3. 下一准入边界

### 研究、最终回答与单一核验

研究模型同时负责 claims 与最终回答，统一生产链已迁入。C1、G2 和原目标正式续验均已按既定条件通过，不追加稳定性采样；普通回答保持原路径。剩余类别回放、正式 N 生命周期及上述真实反馈误读按[统一 Spec](../optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)记录，不用本例替代其证据，不恢复已删除的 Coverage、独立汇总或研究 Final。

### 最终修订与计量验收

[当前稿独立核验](../optimization/to_verify/final-revision-comparison.md)的 v6 已随统一方案替换，其真实拒稿与修订成果保持原身份，不再维护独立 Final 活动候选。[计量候选](../optimization/to_verify/research-selection-usage-commit.md)继续按完成响应、Journal 等式与恢复去重独立验收。

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

保持原模型、思考模式、预算及独立用户评分，不扩大昂贵矩阵或重复无增益 E2E。相同边界一次有界修正后仍失败时，停止对应方向局部补丁，按 EVD 重审责任、输入与最小边界，并及时检索同类优秀实践；恢复确定性反馈契约依据工程失败和反事实，不用外部资料替代。

后续候选仅在具备责任边界依据和预声明后进入实现。已撤回的整体 Context、固定搜索流程或孤立同义提示不恢复为并行路径；已成立局部机制也不因独立下游失败被撤销。当前决定由 [ADR 0032](../adr/0032-conversation-research-claims.md#2026-10-16-当前决定)拥有；既定用例达到条件即关闭，新真实失败再按对应问题重新打开。其他未执行边界与完整发布矩阵不得写成通过。

评分输出预算机制见[固化记录](../optimization/completed/research-grader-output-budget.md)，评分资格契约见[固化记录](../optimization/completed/research-grader-qualification.md)，运行步骤见[评测执行](../evals/04-running-and-release.md#研究评分器输出额度)。工具内部模型用量交接由[独立问题](../optimization/tool-model-usage-handoff.md)拥有，成本不得只报直接调用总账。

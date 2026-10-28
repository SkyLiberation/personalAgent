# Conversation Draft 语义验证隔离设计

本页维护 `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001` 尚未闭环的决策、剩余门禁和退出条件。准入状态见[设计优化队列](design-optimization-backlog.md)，机制与验收见[统一 Spec](../optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)，正式结果见[评测盘点](../evals/02-current-case-inventory.md#2026-10-16-统一研究与最终回答的正式验证)。

## 1. 尚未解决的问题

剩余问题包括既定 S／F 统一阶段回放、正式缺失回答生命周期，以及真实来源归属、列举范围和反馈后修订的失败边界。既定 v3 正式续验已按原条件关闭，不追加泛化或稳定性门槛。

真实报告曾将“提交前自行核对”扩大为正文必须展示核对清单，归现有目标满足类别的 RV-01／RV-03，仍待按实际输入校准。新反馈问题分别取得依据，不新增类别或叠加复核。

## 2. 责任与保留条件

用户目标确定所需内容，模型选择证据、正文与修订；执行系统保存实际来源正文、坐标、URL 和失败事实。代码保护版本、编辑目标、可见引用和选中子集。同一研究模型生成 claims 与最终回答，统一核验器检查来源支持、稿件一致性和目标覆盖，Completion 绑定同一完整版本与确切正文。

现行行为由 [ADR 0032](../adr/0032-conversation-research-claims.md)及[核验专题](../topics/verification-and-completion.md)拥有。拆分、复合识别和独立文档缺项识别按 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)停用；删除动作的自然使用与语义覆盖仍按[单条撤回候选](../optimization/to_verify/claim-deletion.md)验收。保存误路由见[独立准入审计](conversation-research-save-misroute.md)。

## 3. 下一准入边界

### 研究、最终回答与单一核验

剩余类别回放、正式 N 生命周期及目标反馈误读按[统一 Spec](../optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)验收。保留唯一研究路径、确定性来源投影与版本绑定，不恢复已删除的 Coverage、独立汇总或研究 Final。

### 最终修订与计量验收

[当前稿独立核验](../optimization/to_verify/final-revision-comparison.md)的 v6 已被统一方案替换，旧拒稿与修订结果按原身份保留。[选证用量提交](../optimization/to_verify/research-selection-usage-commit.md)仍按完成响应、Journal 等式和恢复去重独立验收。

### 有范围的未知与正常交付

“规范明确没有此要求”是需要证据的外部断言；“依据本次所读片段无法确认”是有范围的认知限制。后者可与有据事实一起形成答案，由模型依据目标、线索和成本决定继续查找或停止，不能暗加每项必须有肯定答案的条件。

当前仅对 `answer` 执行独立语义评分，`limitation` 仍计未交付。改变公开结果契约须另有正反例、原始失败和评分边界，不能切换 disposition 绕过用户结果契约。

### 来源支持与片段修订

来源变更须区分真实缺证、语境误读和生成稿扩大范围。相同输入异判不能靠选取较早通过消除；实际消费最新判断与该判断是否准确分别验收。现有类型能够表达已发现问题，尚无依据新增生产阶段或分类。

已结束诊断的结果、样本和成本由原报告拥有，本文只链接其依据：

- [范围校准](../optimization/claim-verifier-consistency.md#2026-09-30-断言范围校准)、[完整实发输入审查](../optimization/claim-verifier-consistency.md#2026-10-01-修订修复后的判决边界审查)与[输入归属审计](../ablation/claim-verifier.md#24-持续漏检的输入归属审计)说明来源、主体和限定范围的实际差异。
- [Context 删除与隔离诊断](../ablation/claim-verifier.md#23-context-定向删除验证)、[最小输入与现有类型](../ablation/claim-verifier.md#210-最小-context-与错误类型核对)、[逐组加回及追问](../ablation/claim-verifier.md#211-最简输入逐组加回)未证明完整阶段修复或唯一根因。
- [字段顺序](../ablation/feedback-output-schema.md#7-字段顺序敏感性诊断)、[未绑定片段](../ablation/feedback-output-schema.md#8-未绑定原文片段的加入诊断)、[固定输入重复](../optimization/to_verify/research-goal-coverage.md#同输入判决波动的扩展采样)及[逐轨审计](../ablation/claim-verifier.md#218-海岸漏报的逐轨判断审计)保留同输入波动和归属问题，不据此启动新生产阶段。
- [临时理由输出](../ablation/claim-verifier.md#219-临时-reason-输出诊断)、[中文语言对照](../ablation/claim-verifier.md#220-整体中文翻译的语言对照)与[基础反馈恢复复核](../ablation/claim-verifier.md#222-中文单类核验恢复基础反馈与验收复核)分别解释单点覆盖和整轮有效反馈，不能把“未找齐错误”直接计为整轮失败。

下一来源方案按[当前优化取舍](../optimization/to_verify/research-goal-coverage.md#当前优化取舍)取得具体关系漏报、材料归属及输出定位的依据；同义提示、claim 拆分或新字段不能自动成为新候选。模型可见理由辅助定位，不作为隐藏因果证明。

[支持范围修订](../optimization/to_verify/claim-supported-scope-repair.md)仍有扩大声明和新增事实未绑定引用的失败，聚焦同一修订提交的引用绑定；[片段有界修订](../optimization/to_verify/claim-fragment-revision.md)独立验收编辑范围与内容。已成立的引用继承、片段寻址、完整基稿交接和来源报告复用见[完成记录](../optimization/completed/README.md)，不在本页重复跟踪。

语义判决、报告能否完整返回及全部已完成响应的成本分别计分；空正文没有判决。正式验证从中文自然任务和生产入口连续消费真实选证、生成、核验、修订与交付，未到达阶段单列，不注入理想稿或挑选通过版本。

## 4. 停止与退出

上述诊断已按各自计划结束，没有新生产候选。后续方案须先更新唯一设计并满足 [EVD](../devSpec/change-evidence.md#7-强制开发与设计流程)；核验输入不足按 [QLT](../devSpec/quality-security.md#21-核验漏放先验证最小充分上下文)定位。保持对应比较身份中的模型、思考模式、预算和独立评分，不将不同输入或随机轨迹当作机制收益。

同一阻塞一次有界修正后仍失败，按 EVD 停止局部叠补并复审；已撤回的整体 Context、固定搜索流程和同义提示不恢复为并行生产路径。已成立机制不因独立下游失败撤销，既定用例达到条件即关闭，新真实失败按原问题重新打开。

评分资格与输出预算见[评分固化记录](../optimization/completed/research-grader-qualification.md)及[输出预算记录](../optimization/completed/research-grader-output-budget.md)，执行方法见[运行与发布](../evals/04-running-and-release.md)。工具内部用量见[独立交接问题](../optimization/tool-model-usage-handoff.md)；未执行边界与完整发布矩阵保持未验证。

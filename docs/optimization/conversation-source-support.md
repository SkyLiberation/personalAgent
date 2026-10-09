# 研究回答来源支持：问题总览与经验索引

**当前推进需要区分来源支持、用户事实覆盖和最终表达保真。** 三者的局部通过不能相互替代，也不能覆盖原用户结果。近期失败集中在[具体来源归属](normative-scope-attribution.md#2026-10-02-实际流程步骤的来源错配)、[修订扩大列举范围](claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举)及[选证输出截断](claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究)。本轮按[当前稿独立核验的预声明](claim-revision-nonconvergence.md#2026-10-08-当前稿独立核验的预声明)先执行隔离校准。

本文提供跨问题导航，不维护第二份准入或结果台账。当前行为由[验证专题](../topics/verification-and-completion.md)、[ADR 0032](../adr/0032-conversation-research-claims.md)和 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)拥有；准入由 [Future 队列](../future/design-optimization-backlog.md)拥有，原始用户结果由[评测盘点](../evals/02-current-case-inventory.md)拥有。拆分、复合识别及独立文档缺项识别已停用，历史局部收益按原条件保留。

## 当前核心问题与责任边界

先定位责任边界，再决定验证范围。执行系统提供原文、坐标与执行事实；模型提出论断和修订；来源 Verifier 判断依据能否支持具体声明，研究覆盖判断事实能否回答用户问题，最终 Verifier 判断实际成稿，Completion Gate 绑定同一通过稿。

| 问题边界 | 记录与候选入口 |
| --- | --- |
| 修正出处时把部分列举改成完整清单 | [实际连续修订反例](claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举)、[当前稿独立核验候选](to_verify/final-revision-comparison.md) |
| 具体步骤被归到另一个来源页面 | [来源归属问题](normative-scope-attribution.md)、[来源归属候选](to_verify/answer-source-attribution.md) |
| 相关事实没有回答用户所问对象 | [对象与适用范围](answer-object-mismatch.md)、[事实覆盖候选](to_verify/research-goal-coverage.md) |
| 同一请求得到冲突判断 | [核验一致性与实际请求审计](claim-verifier-consistency.md) |
| 缺证反馈后扩大主体、条件或义务强度 | [支持范围修订](to_verify/claim-supported-scope-repair.md)、[研究修订总问题](claim-revision-nonconvergence.md) |
| 局部观察被写成全文缺项 | [历史缺项问题](document-absence.md)、[停用后的保护边界](to_verify/document-absence-pause.md) |
| 原文行号与临时引用编号混用 | [引用坐标问题](citation-coordinate-confusion.md) |
| 引用原文没有可核对的来源信息 | [来源绑定问题及剩余验收](citation-source-attribution.md) |
| 后置失败遮蔽已完成模型成本 | [选证及时提交](research-selection-usage-commit.md)、[工具内部用量交接](tool-model-usage-handoff.md) |
| 选证截断使后续阶段未到达 | [正式失败](claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究)、[默认额度候选](to_verify/research-provider-output-default.md) |
| 拒稿后的取证、计划恢复和自主补证 | [反馈与修订](revision-feedback-loop.md)、[取证](evidence-acquisition.md) |

### 缺项问题的状态更正

独立缺项识别与读取覆盖门禁的历史有效边界见[职责分离](document-absence.md#83-文档缺项识别与普通支持验证的职责分离)、[真实读取消费](document-absence.md#85-覆盖门禁接入真实读取事实与生产工具)及[分类交接修复](document-absence.md#104-按来源顺序返回缺项分类)。这些局部证据保留，完整任务失败也保留；当前停用决定由 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)拥有，历史方案的“继续保留门禁”不再作为今天的实施指令。

[原文核查](document-absence.md#109-原文缺项核查与扩源反馈的边界验证)已更正“已保存来源存在被漏读答案”的旧解释。未取得证据时，模型可以扩源或说明本次取证限制；是否满足任务另由事实覆盖和最终交付判断。没有保存核验入参的历史运行只报告实际到达阶段，不推断缺项分支是否触发。

### 评测与成本的独立阻塞

正式结果、有效独立评分和已完成模型成本分别记录。无有效评分不代表答案通过；已确认的来源错误也不因评分结构失败而消失。局部通过、前置截断、服务超时和未交付按阶段归因，见[评测盘点](../evals/02-current-case-inventory.md)、[Provider 诊断](to_verify/model-provider-diagnostics.md)与[用量交接](tool-model-usage-handoff.md)。

## 必须保留的经验

有效机制在后续验证中继续保留，独立下游失败不重开已解决问题。已固化机制只引用唯一完成文档，不在本页重述状态、结果或待办。

| 查阅目的 | 唯一记录 |
| --- | --- |
| 真实反馈逐轮修订与同稿绑定 | [多错误渐进修订](completed/multi-error-verification-revision.md) |
| 被拒稿的完整文字和引用交接 | [完整基稿](completed/complete-rejected-draft-handoff.md) |
| 引句、验收项和编辑目标的身份恢复 | [调用单元](completed/verifier-finding-binding.md)、[验收项引用](completed/final-criterion-transcription.md)、[片段寻址](completed/claim-fragment-addressing.md) |
| 已完成报告按实际输入消费 | [来源报告复用](completed/claim-source-review-reuse.md) |
| 引用继承与坐标反馈 | [引用继承](completed/claim-retained-references.md)、[坐标反馈](completed/research-admission-coordinate-feedback.md) |
| 动作与独立评分恢复 | [动作协议](completed/conversation-action-protocol-recovery.md)、[评分资格](completed/research-grader-qualification.md)、[评分额度](completed/research-grader-output-budget.md) |

## 已尝试的方法与未证实假设

历史尝试集中在具体问题内。提示、输入聚焦、职责分离或预算调整只在其实际输入与判据范围内成立，不作为所有语义误判的总解释。

| 尝试或待区分假设 | 原始问题与证据入口 |
| --- | --- |
| 显式禁令、反问、示例与推导判断 | [权限责任推断](permission-inference.md) |
| 摘要、全文标志与缺项分类 | [文档缺项](document-absence.md) |
| Context 裁剪、单句与完整稿、两侧聚焦 | [对象错位](answer-object-mismatch.md) |
| 先取证再写作、扩源及主动停止 | [取证](evidence-acquisition.md)、[选证候选](to_verify/claim-evidence-selection.md) |
| 片段保护与真实反馈消费 | [片段有界修订](to_verify/claim-fragment-revision.md)、[修订总问题](claim-revision-nonconvergence.md) |
| 正文提取、思考传递和输出截断 | [提取](source-extraction.md)、[思考](thinking-context-transport.md)、[截断](verifier-output-truncation.md) |

## 阅读顺序与完整记录

历史编号用于反查，日期对应当轮代码和证据身份。旧复合坐标、旧引用复制协议及已撤回候选不作为当前生产反例；停止理由保留在原问题中。

| 要查的问题 | 完整记录 |
| --- | --- |
| 近期研究、来源、汇总和最终核验的关系 | [研究修订总问题](claim-revision-nonconvergence.md)、[候选索引](to_verify/README.md) |
| 局部观察被写成全文缺项 | [文档缺项](document-absence.md)；历史编号 3、4、6、8、9、30、31、32、67、69、78、81 至 85、104、105、109 |
| 对象与依据范围错位 | [对象错位](answer-object-mismatch.md)；历史编号 57 至 66、75、86 至 101、114 |
| 执行职责被推成权限责任 | [权限推断](permission-inference.md)；原文保留对应历史编号 |
| 自主补证及拒稿后的恢复 | [取证](evidence-acquisition.md)、[反馈修订](revision-feedback-loop.md) |
| 整稿验收的来源支持职责 | [来源支持](verification-source-support.md)；历史编号 47 至 49、55、56 |
| 动作阶段输出与结构恢复 | [动作协议问题](action-final-protocol.md)、[完成记录](completed/conversation-action-protocol-recovery.md) |
| 正文提取、思考配置和核验额度 | [提取](source-extraction.md)、[思考](thinking-context-transport.md)、[截断](verifier-output-truncation.md) |
| 面试经验讲述 | [开发踩坑与优化经验](../interview/10-development-pitfalls.md)；证据继续由具体问题拥有 |

## 后续推进与接入规则

新尝试写入同一具体问题，总览只维护导航。未充分证明的机制由 `to_verify/` 保留，已解决机制按 [completed 规则](README.md#已解决问题的固化规则)收敛；Future 维护准入，正式评测维护原始用户结果。

先审查实际请求，在条件局部回放中消费同一轨迹的实际反馈和实际输出；人工相邻控制只校准判断边界，不能拼接成产品成功。核验符合预声明后再扩大至连续修订和正式 E2E。完整读取、工具可用、模型理由、合法动作与一次放行均不能替代用户结果。

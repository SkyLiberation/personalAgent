# Conversation Draft 语义验证隔离设计

本页是[设计优化队列](design-optimization-backlog.md)中 `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001` 的条件设计，只保存当前语义问题与下一准入边界。过程由[优化总览](../optimization/conversation-source-support.md)拥有，正式结果由[评测文档](../evals/02-current-case-inventory.md)拥有。

## 1. 尚未解决的问题与证据边界

**拒稿后的整稿修订仍不稳定，正确条款还可能被用于另一对象或扩大要求强度。** 最新整体 Context 正式候选四稿未交付，先后三次覆盖拒绝、一次引用支持拒绝；最终误转保存确认。该候选已撤回，取舍见[第 115 节](../optimization/evidence-acquisition.md#115-完整查询交接与-context-重组的正式接入验证)。不能把拒绝次数当作各次分类都准确，也不能仅从最终未交付推断某条提示的因果。

后续复用[多错误渐进修订](../optimization/completed/multi-error-verification-revision.md)、[查询执行事实交接](../optimization/completed/query-execution-handoff.md)、当前正文提取、按行读取、随文引用与原 Plan 生命周期。独立缺项覆盖门禁已按 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)暂停；当前来源支持和语义核验由[验证专题](../topics/verification-and-completion.md)拥有，不重复证明循环存在或参数可以区分。

此前整体重组在受控续跑取得扩源和原权限缺项修订收益，见[原 Context 实验](../optimization/document-absence.md#补充重组候选的真实工具连续续跑)。该收益保持，但不能直接宣布本轮正式迁移成功；已撤回的逐字复制引用、孤立同义提示、固定搜索流程不恢复为并行实现。

## 2. 责任主体与当前可达边界

Conversation 选择证据、引用和原生正文；执行系统拥有真实查询、读取及失败事实；局部支持 Verifier 判断声明是否受本段提交证据支持；研究覆盖与最终 Verifier 分别判断事实齐全和用户结果；Completion 绑定同一通过稿。任何一方都不能把另一对象的保证、URL 存在、计划自评或 typed 合法当成用户完成。

此前隔离验证不修改模型、预算算法、工具授权、来源权威范围或 Completion，也不要求固定工具、查询、次数或措辞。取证充分性字段已随独立缺项门禁退出；claim 主链按 [ADR 0032](../adr/0032-conversation-research-claims.md)接入，现可按 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)撤回单条论断，但用户结果尚未通过。首次研究提交的 [typed 输出故障](../optimization/to_verify/claim-writer-typed-output.md)在正式 target 中越过了原 503 检查点，研究仍因后续取证与预算限制未交付，当前准入状态不变。保存误路由的候选输入因果与当前代码 baseline 另见[准入审计](conversation-research-save-misroute.md)，不在本项追加保存策略。

## 3. 条件候选与因果准入顺序

**首先验证证据不足时的正常交付边界，不能把继续搜索直到找到答案作为必达条件。** [历史第 109 节](../optimization/document-absence.md#109-原文缺项核查与扩源反馈的边界验证)已经审计过主文档不含直接权限条款，并通过人工限定稿验证局部未知可以解除覆盖拒绝；这没有证明自主修订和完整交付已通过。用户本轮进一步明确：问题可能没有可取得的证据，Runtime 不应因此完全拦截回答。

“规范明确没有此要求”是需要证据的外部断言；“本次检索未取得足以确认此项的依据”是有范围的证据限制。后者应允许与有据结论一起交付，由模型依据用户目标、线索和成本决定继续查找或停止。是否满足完整任务仍按原用户结果判断，但不能暗加“每个问题必须找到肯定答案”的标准，也不能把表达未知本身判成无据事实。已有错误的肯定论断仍须修订。

当前应在同一真实依赖链中核对 claim 创建、证据选择、修订或撤回、来源支持、事实覆盖、独立汇总、最终交付及后置评测。当前评测只对 `answer` 执行语义评分，`limitation` 直接记为未交付；需验证有实质责任说明且明确未知的正常答案，不用切换 disposition 绕过事实核验。需要改变公开结果契约时，先单独声明新契约与正反例，保留旧 E2E 原始失败。

历史取证充分性候选及覆盖分支的未决观测已随独立缺项门禁暂停，不再作为当前准入步骤；原失败与局部证据保留在 [ADR 0027](../adr/0027-model-owned-evidence-sufficiency.md) 和[评测登记](../evals/02-current-case-inventory.md#取证充分性契约的正式验证)。本轮的新增删除动作与停用风险由 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md) 约束。

### 条件设计：局部修改，完整合成后核验

当前上位问题下，[先选合适证据再生成论断](../optimization/to_verify/claim-evidence-selection.md)针对 claim 创建与后续取证方向；参数和修订的既有候选分别为[参数范围约束](../optimization/to_verify/claim-argument-scope.md)、[参数错误恢复](../optimization/to_verify/claim-parameter-recovery.md)及[正文与引用独立修订](../optimization/to_verify/claim-evidence-revision.md)。[复合论断拆分候选](../optimization/to_verify/claim-multi-proposition.md)的生产动作已暂停。第 40 版后的整项改写退步与长期未核验编辑分别对应[片段修订候选](../optimization/to_verify/claim-fragment-revision.md)和[新版复验触发候选](../optimization/to_verify/claim-revision-progress.md)。各自机制、证据、依赖及下一判据由对应 `to_verify` 文档唯一拥有；[整体问题](../optimization/claim-revision-nonconvergence.md)区分责任边界，本页不复制方案。

原生产轨迹存在局部修好后被完整重写丢失引用的反例，见[连续反馈记录](../optimization/revision-feedback-loop.md#128-连续反馈中的修订保留验证)。已有完整基稿交接、反馈绑定、统一文档行引用与自检继续保留。研究论断与独立汇总已进入当前 Conversation 生产路径，具体接入及原始 E2E 结果见[问题入口](../optimization/claim-revision-nonconvergence.md#2026-09-28-完整生产接入)；证据选择先于论断的候选尚未接入。

完整研究集合在一次正式 target 中通过并进入独立汇总，但该次独立语义评分器没有有效判决；稳定通过与正式用户结果仍缺证据。[宽限制完整循环](../optimization/revision-feedback-loop.md#145-宽限制下的完整研究修订循环)取得主动复验、c1 局部支持通过和 c2 引用修改，但第 15 版 c2 被拒。[仅提供拆分工具](../optimization/revision-feedback-loop.md#146-复合论断拆分工具的连续验证)未引出拆分。后续[Verifier 粒度反馈验证](../optimization/revision-feedback-loop.md#147-verifier-粒度反馈的识别与连续消费)在固定第 15 版识别了 c2 的三项独立职责，并在真实续接中送达；模型首先原稿提交，重验先拒绝 c1，随后收到 c1 的粒度反馈并合法拆成七项。第 16 版因一个拆出项新增无据细节仍被拒，原 c2 未再核验。反馈到动作的局部消费成立一次，拆后语义保持及完整集合通过当时未成立。

未改 claim 的相同实发核验输入曾得到不同结果，独立记录为[核验一致性问题](../optimization/claim-verifier-consistency.md)。新一轮重验转向未改项不证明其他缺口已解除，也不能把不同随机判断直接当作粒度反馈的因果收益。[移除参数错误次数上限的连续续接](../optimization/revision-feedback-loop.md#151-移除参数错误次数上限后的连续续接)已使模型从第 40 版合法提交并取得第 20 次核验反馈，但该轮仍拒绝 c7；之后模型反复修改至第 59 版而未再提交，第 180 次服务请求无响应。修订中扩张无据细节、复合论断、长期未核验编辑、参数误用和相同输入核验不一致按[子问题总览](../optimization/claim-revision-nonconvergence.md)分别归因。下一门禁仍是让现有证据支持每项论断，并取得稳定的完整真实核验及用户结果通过，同时独立处理相同请求核验不一致。不能硬编码具体问题、固定拆分数量或仅扩大轮数来取得一次偶然通过。证据选择机制、阶段职责修正后的连续交付和正式用户结果仍缺适用证据。


截至 2026-09-30，拆分动作、复合论断识别及独立文档缺项识别已暂停，研究写作者可用单条 `delete_claim`；来源 URL 由执行记录确定性投影到独立汇总，研究事实覆盖不再判断 URL 存在与呈现。[最新两次正式 target](../evals/02-current-case-inventory.md#2026-09-29-研究来源-url-交接与事实覆盖职责复验)均为 `0/1`：首次到达汇总和最终答案，但独立评测器输出无效；第二次在前置来源支持修订循环耗尽 32 个决策回合，覆盖、汇总与最终核验未到达。当前剩余门禁是前置论断修订稳定收敛、阶段职责修正后的连续交付和有效用户结果评分；不能用首次 URL 交接的局部通过替代。既有正式路径继续保留[动作协议恢复](../optimization/completed/conversation-action-protocol-recovery.md)。

## 4. 外部机制核对与复杂度约束

当前单条删除动作的两个 A 级机制坐标、最小边界和退出条件见 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)；历史充分性候选的比较见 [ADR 0027](../adr/0027-model-owned-evidence-sufficiency.md)。后续新机制仍须按 EVD 核对独立实现、预声明检查点与正式用户结果。已有 Context 固定外部坐标见[机制与输入审计](../optimization/document-absence.md#补充持续续读指引与-system-prompt-组织审计)。不以摘要替代实际请求，也不根据可见理由推断隐藏因果。

## 5. 停止与退出条件

原 E2E 失败保持，不扩大昂贵矩阵。已撤回的整体 Context 候选不恢复；后续每轮按[参数恢复候选](../optimization/to_verify/claim-parameter-recovery.md)及预声明预算执行：可修复参数拒绝返回模型，达到拒绝上限、服务或预算阻塞才停止；缺少后置覆盖不能算通过，不补抽成功样本。相同候选反例复现时停止局部提示追加，重新判断责任边界；历史独立机制不因此撤销。

参数保真是已固化前提，仍重复搜索不构成该事实机制的反例。整体 Context 重新接入须补齐误路由因果排查和原完整用户结果；不能以局部通过保留未经准入的行为分支。若新失败确认为独立下游问题，再单独登记，不追溯撤回已成立机制。

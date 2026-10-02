# 用证据支持范围约束缺证修订

`CLAIM-SUPPORTED-SCOPE-REPAIR-001` 属于[研究未收敛问题](../claim-revision-nonconvergence.md)。上一正式轨迹第 5 版反馈“原文未把配置主体指定为应用”，下一实际 replacement 扩大成“原文未指定配置主体”。原文有 `You`，缺少映射到特定架构角色的前提，被写作者转换成了更广的否定。具体请求及反馈由[来源判决审查](../claim-verifier-consistency.md#2026-10-01-修订修复后的判决边界审查)拥有。

## 解决机制

研究来源核验消费当前整条 draft、全部已绑定原文及 Runtime 无损派生的片段目录。`ResearchSupportReport` 每项反馈分别返回 `unsupported_assertion`、`supported_scope`、`missing_premise`、相关 `evidence_ids` 及片段首尾 ID，明确草稿断言、已有支持与尚缺前提。模型输出定位 ID，Runtime 检查当前片段范围及证据身份，不要求重抄旧句。

Runtime 从该报告的原始绑定恢复相关 evidence ID 的实际原文，作为 `source_feedback` 交给正式选证模型和写作者。写作者先核对原文，再选择收窄、删除无据部分、按支持范围改写、改引用或取证，保留有据内容及用户所需事实。反馈解释只描述修订任务；新事实和否定必须来自实际原文，某个主体缺证不能推出没有任何主体。

## 防护与责任

研究反馈采用唯一 typed 契约，替换研究路径的平面 OverreachReport；普通整稿核验保留自身输出契约，双方共享同一来源支持判据正文。未修改普通 Prompt 的语义字节。反馈中的片段 ID 绑定当前整条 claim，证据 ID 只从该次原始核验输入恢复，来源 URL 继续由执行来源投影。

片段合并和引用保持仍由 Runtime 执行。修订后核验整条 claim 中的每项事实，包括新增否定与解释；无据替换继续返回反馈。事实覆盖及最终用户结果由各自 Verifier 判断。反馈扩展接入原来源请求，不新增模型核验轮次、复合识别或 claim 拆分。

## 验收

按[本轮计划](../../../.tmp/research-source-reuse-repair-20261001/plan.json)审计真实模型请求，确认当前全文、片段目录、全部绑定原文及 typed 输出契约一致。正式 target 自然到达拒稿后，连续记录真实反馈、选证、实际修订及新稿核验，分别检查原缺口、新无据声明、未受影响事实和用户事实覆盖。没有到达修订的样本记录为未覆盖；正式完整答案按原中文任务与原 grader 判定。一次有界修正后同因复现即封存，停止追加同义提示。


## 2026-10-01 真实反馈消费结果与下一设计边界

一个原中文正式 target 中，12 次写作请求消费 typed `source_feedback` 及 Runtime 恢复的相关原文，12 个新完整 claim 均重新核验；最终研究集合通过。证据为[写作输入审计](../../../.tmp/research-source-reuse-repair-20261001/writer-audit.json)及[修订连续审计](../../../.tmp/research-source-reuse-repair-20261001/repair-audit.json)。完整用户结果由[评测记录](../../evals/02-current-case-inventory.md#2026-10-01-来源报告复用与结构化修订反馈)拥有。

首次修订可靠性尚未达标：c1 第 2 版把主体限定改成更广的资料否定，再次被拒；第 3 版收窄后通过。c2 第 6 版和 c7 第 12 版加入真实规范事实，但片段修改保留各自旧引用，未绑定这些新增事实；后续独立 `replace_references` 才解除缺口。c7 从 4 项 findings 增至 6 项。模型已收到反馈和原文，故不归因为反馈未送达，也不继续叠加同义提示。

下一候选聚焦“正文片段与新增依据的同一修订提交”：模型提交片段 ID、replacement 以及明确选择的新增引用；Runtime 保留已有绑定，校验新增引用已选且可见，原子提交当前新版，再核验整条 claim。新事实与引用由模型一起选择，Admission 只接受或拒绝；现行 selector 不能自动把所有所选证据写入 claim。应使用本次 c2/c7 的实际动作、引用与取证状态验证新增绑定、未选拒绝及未改项保真，再以原自然任务连续验证。此方案尚未实现。

主体缺证扩大为任意主体缺失仍按相邻真实样本核对。来源判决中的局部范围误读由[一致性问题](../claim-verifier-consistency.md)独立归因；完整输入中“本条引用”的限定不能按整篇文档否定来拒绝。保留 thinking 和原始 reasoning。

## 2026-10-02 新增事实未随正文绑定引用

诊断补齐后的同一正式轨迹中，c8 第 14 版仅写两个 URL 支持前述结论；第 15 版为回应反馈，加入默认批准、可跳过批准、工具发现与调用、outputSchema 校验及 MUST／SHOULD 强度等事实。两次来源实发请求的十项引用逐条相同，仍为标题、URL、两页介绍及页面顶部文字，新条款没有成为 c8 的提交引用。其他 claim 的引用不会自动进入该条核验。第 15 版报告形成六项 findings，新增事实的引用缺口成立，见[第 14 版输入](../../../.tmp/mimo-provider-diagnostics-20261002/target/model-calls/21152/0116-request.json)、[第 15 版输入](../../../.tmp/mimo-provider-diagnostics-20261002/target/model-calls/21152/0122-request.json)及[实际报告](../../../.tmp/mimo-provider-diagnostics-20261002/target/model-calls/21152/0122-response.json)。

本反例补充“正文与新增依据在同一修订提交”的既有准入依据。写作者已消费真实反馈并修改正文，当前缺口归属修订的引用绑定；来源 Verifier 消费该条完整正文及已提交引用。本轮保持原修订契约与 Prompt，连续验证和完整用户结果在[诊断验证归档](../../../.tmp/mimo-provider-diagnostics-20261002/REPORT.md)中单列。

随后第 16 版实际提交 `replace_claim_references`，保留正文并补入工具发现、调用响应、schema、批准默认及跳过等对应原文，引用从十项单行证据改为十六个证据范围。来源复验仅剩“两页各自只支持一组结论”的排他范围反馈。两次独立提交及其间的拒绝仍保留，正文与新增引用的原子修订方案继续待验证，见[实际修订](../../../.tmp/mimo-provider-diagnostics-20261002/target/model-calls/21152/0128-response.json)和[复验报告](../../../.tmp/mimo-provider-diagnostics-20261002/target/model-calls/21152/0130-response.json)。

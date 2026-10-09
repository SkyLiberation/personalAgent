# 用证据支持范围约束缺证修订

`CLAIM-SUPPORTED-SCOPE-REPAIR-001` 属于[研究未收敛问题](../claim-revision-nonconvergence.md)。上一正式轨迹第 5 版反馈“原文未把配置主体指定为应用”，下一实际 replacement 扩大成“原文未指定配置主体”。原文有 `You`，缺少映射到特定架构角色的前提，被写作者转换成了更广的否定。具体请求及反馈由[来源判决审查](../claim-verifier-consistency.md#2026-10-01-修订修复后的判决边界审查)拥有。

## 解决机制

研究来源核验消费当前整条 draft、全部已绑定原文及 Runtime 无损派生的片段目录。`ResearchSupportReport` 每项反馈分别返回 `unsupported_assertion`、`supported_scope`、`missing_premise`、相关 `evidence_ids` 及片段首尾 ID，明确草稿断言、已有支持与尚缺前提。模型输出定位 ID，Runtime 检查当前片段范围及证据身份，不要求重抄旧句。

Runtime 从该报告的原始绑定恢复相关 evidence ID 的实际原文，作为 `source_feedback` 交给正式选证模型和写作者。写作者先核对原文，再选择收窄、删除无据部分、按支持范围改写、改引用或取证，保留有据内容及用户所需事实。反馈解释只描述修订任务；新事实和否定必须来自实际原文，某个主体缺证不能推出没有任何主体。

## 防护与责任

研究反馈采用唯一 typed 契约，替换研究路径的平面 OverreachReport；普通整稿核验保留自身输出契约，双方共享同一来源支持判据正文。未修改普通 Prompt 的语义字节。反馈中的片段 ID 绑定当前整条 claim，证据 ID 只从该次原始核验输入恢复，来源 URL 继续由执行来源投影。

片段合并和已有引用保持由 Runtime 执行。正文与新增引用的交接由[原子修订完成记录](../completed/claim-atomic-evidence-revision.md)拥有。修订后核验整条 claim 中的每项事实，包括新增否定与解释；无据替换继续返回反馈。事实覆盖及最终用户结果由各自 Verifier 判断。反馈扩展接入原来源请求，不新增核验阶段。

## 验收

按[本轮计划](../../../.tmp/research-source-reuse-repair-20261001/plan.json)审计真实模型请求，确认当前全文、片段目录、全部绑定原文及 typed 输出契约一致。正式 target 自然到达拒稿后，连续记录真实反馈、选证、实际修订及新稿核验，分别检查原缺口、新无据声明、未受影响事实和用户事实覆盖。没有到达修订的样本记录为未覆盖；正式完整答案按原中文任务与原 grader 判定。一次有界修正后同因复现即封存，停止追加同义提示。


## 已观察结果与下一边界

真实 c1 将特定主体缺证扩大为任意主体缺失，下一修订收窄后来源通过；c7 曾新增无据范围。typed 反馈和原文已经送达，首次语义修订仍需验证，不能继续叠加同义提示。实际输入及修订由[2026-10-01 归档](../../../.tmp/research-source-reuse-repair-20261001/repair-audit.json)保留。

正文与新增依据分轮提交的子问题由[完成记录](../completed/claim-atomic-evidence-revision.md)唯一拥有。该契约继续保留，本候选只处理支持范围反馈被改写成更广否定或新无据声明；核验范围误读由[一致性问题](../claim-verifier-consistency.md)独立归因。下一样本保持真实反馈、原文与 thinking，连续核对修订语义、未受影响事实及原用户要求。

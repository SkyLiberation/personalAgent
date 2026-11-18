# Conversation Draft 语义验证隔离设计

本页维护 `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001` 的剩余准入条件。当前状态见[设计优化队列](design-optimization-backlog.md)。

## 1. 尚未解决的问题

旧链在来源归属、列举范围和目标条件上有真实误判。例如，将“提交前自行核对”误判为正文必须展示核对清单。旧 v3 原目标续验已经按当时的条件通过，记录见[正式结果](../evals/02-current-case-inventory.md#2026-10-16-统一研究与最终回答的正式验证)。[ADR 0055](../adr/0055-unified-conversation-answer.md)移除 Conversation claim 后，剩余判断以当前提交稿的实际失败为依据。

## 2. 当前责任

用户目标决定所需结果，模型选择证据、正文和修订，执行系统持有来源原文、坐标及工具事实。代码核对引用坐标；适用的回答核验以本次完整候选和生效目标给出判决，退回后由原循环继续。详细契约见[核验专题](../topics/verification-and-completion.md)。

## 3. 下一准入边界

先核对当前正式轨迹是否复现原来具体的来源归属、范围扩大或目标约束误判。若复现，检查提交当时的生效目标、实际原文、引用及反馈，区分未读、误读和正文扩大范围。业务结论与“根据本次所读资料无法确认”承担不同举证责任。原报告和后续改稿分别作为真实输入，不挑选同输入异判中较早的通过结论。旧研究核验诊断及其证据见[历史消融](../ablation/claim-verifier.md)和[来源支持记录](../optimization/conversation-source-support.md)。

## 4. 停止与退出

当前没有新生产候选。复现后按 [EVD](../devSpec/change-evidence.md#7-强制开发与设计流程)更新唯一设计，再按 [QLT](../devSpec/quality-security.md#21-核验漏放先验证最小充分上下文)检查当前核验输入。真实用户结果、模型判决和用量分别记录。

同一阻塞一次有界修正后仍失败，按 EVD 停止局部叠补并复审；已撤回的整体 Context、固定搜索流程和同义提示不恢复为并行生产路径。已成立机制不因独立下游失败撤销，既定用例达到条件即关闭，新真实失败按原问题重新打开。

旧评分资格和输出预算分别见[评分固化记录](../optimization/completed/research-grader-qualification.md)及[输出预算记录](../optimization/completed/research-grader-output-budget.md)。工具用量见[独立交接问题](../optimization/tool-model-usage-handoff.md)。

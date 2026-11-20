# 统一答复核验的复现条件

本页维护 `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001` 的剩余准入条件。当前状态见[设计优化队列](design-optimization-backlog.md)。

## 1. 尚未解决的问题

旧链在来源归属、列举范围和目标条件上有真实误判。例如，将“提交前自行核对”误判为正文必须展示核对清单。旧 v3 原目标续验已经按当时的条件通过，记录见[正式结果](../evals/02-current-case-inventory.md#2026-10-16-统一研究与最终回答的正式验证)。[ADR 0055](../adr/0055-unified-conversation-answer.md)移除 Conversation claim 后，剩余判断以当前提交稿的实际失败为依据。

## 2. 下一准入边界

先核对当前正式轨迹是否复现原来具体的来源归属、范围扩大或目标约束误判。若复现，检查提交当时的生效目标、实际原文、引用及反馈，区分未读、误读和正文扩大范围。业务结论与“根据本次所读资料无法确认”承担不同举证责任。原报告和后续改稿分别作为真实输入，不挑选同输入异判中较早的通过结论。旧研究核验诊断及其证据见[历史消融](../ablation/claim-verifier.md)和[来源支持记录](../optimization/conversation-source-support.md)。

## 3. 停止与退出

当前没有新生产候选。复现后按 [EVD](../devSpec/change-evidence.md#7-强制开发与设计流程)更新唯一设计，再按 [QLT](../devSpec/quality-security.md#21-核验漏放先验证最小充分上下文)检查当前核验输入。真实用户结果、模型判决和用量分别记录。

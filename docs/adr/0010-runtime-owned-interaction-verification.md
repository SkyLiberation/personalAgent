# ADR 0010：由 Runtime 装配并调用交互语义核验

2026-07-31 决定。Runtime 拥有核验触发、冻结判据以及稿件与回执的绑定。Verifier 负责语义判断。现行目标与回答核验分别使用各自上下文，并依部署开关执行。[核验专题](../topics/verification-and-completion.md) · [ADR 0047](0047-user-goal-verification-context.md) · [ADR 0050](0050-verification-feature-flags.md)

## 背景与决定

旧循环允许模型自行选择是否调用核验、重复提交判据，并重新抄写通过的草稿。ADR 0009 曾让模型按 `verified_receipt_id` 引用通过的稿件，防止文本漂移，但首套判据仍由模型提交，核验也可绕过。Runtime 随后直接调用适用的核验，绑定冻结判据与本次稿件，从持有的原件交付。原模型凭据引用分支随之移除。[ADR 0009 原记录](https://github.com/SkyLiberation/personalAgent/blob/345c62679a6c1f6a4c70980c868f55b5dee95fef/docs/adr/0009-verified-final-message-receipt-reference.md)

模型保有提议用户语义和写作的责任。Runtime 核对判据来源与稿件身份，复用既有内部工作流工具、权限与执行网关。失败反馈交回原循环；通过后由交付边界消费同一稿件。[当前答复提交](0055-unified-conversation-answer.md)

## 历史验证与边界修正

L06 进程内探针从凭据引用阶段的 5/9 到 Runtime 装配后的 9/9。早期四次失败表现为把整条用户指令作为单项判据、反复拒稿。首轮对照尚未触发稿件摘要失配，无法据此估计原复述故障率或节省的成本。

2026-09-07 撤回“所有非 answer 都是逃避核验”及“请求必然已提供待改正文”的推导。该轮正式运行在模型提交前耗尽预算，原结果保留。合法澄清与限制按各自契约处理，适用的回答核验仍由 Runtime 调用。[边界修复记录](../evals/02-current-case-inventory.md#验收条件不再推导改稿任务的边界修复)

原 Investigation 消费者随 [ADR 0015](0015-withdraw-investigation-project.md)退出。核验触发、判据来源或交付绑定出现因果回归时，以实际失败的边界复验。

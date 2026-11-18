# ADR 0047：分别核验目标定义与回答交付

2026-11-03 决定，后续统一接入 Conversation。两类核验的独立开关见 [ADR 0050](0050-verification-feature-flags.md)，现行目标和任务范围见 [ADR 0048](0048-conversation-goal-maintenance.md)。

## 问题与决定

统一核验曾因尚无实际数值而拒绝待执行的任务定义，目标准入和计算相互等待。目标核验只判断定义是否忠实表达用户要求，回答核验判断实际交付。通过目标核验只允许对应目标操作生效。

复用同一个内部核验工具、原回执与 Journal。Runtime 维护各自任务契约、当前用户原话及同职责历史。回答历史消费当时生效目标的原有通过回执，新目标不会覆盖历史答复绑定。配置关闭时保持无核验事实。原生主循环和核验失败反馈各自消费真实输入，避免写入重复历史。[职责分离与绑定](../optimization/to_verify/analysis-goal-maintenance.md#914-分离目标核验与回答核验的职责及历史) · [历史绑定固化](../optimization/completed/verification-context-goal-binding.md)

## 历史验证与退出

新空会话前三轮正式接续，原评分为 `[1,1,1]`，用户结果为通过、通过、失败。旧单核验对照的首轮误拒和原始分数保持原身份。后续若出现历史串用、错绑或对未来结果的误判，回到相应职责的实际输入复验。[新三轮结果](../optimization/to_verify/verify_results/analysis-correctness.md#34-分离目标与回答核验的空会话连续前三轮) · [旧误拒记录](../optimization/to_verify/verify_results/analysis-correctness.md#33-逐项用户要求核验的空会话连续前三轮)

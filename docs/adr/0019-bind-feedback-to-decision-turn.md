# ADR 0019：按模型决策回合统计反馈修复尝试

## 背景

同轮两个无效工具参数产生两条反馈，旧运行时将其当作模型已尝试两次，在模型看到错误前终止。历史轨迹与确定性反例见[推进记录第 53 节](../optimization/revision-feedback-loop.md#53-按完整循环修复错误尝试计数并接入已证实改动)。状态为缺陷修复已接入，完整产品验收待通过。

## 决定与责任主体

`DecisionFeedback.decision_turn` 表示产生反馈的模型决策回合；ConversationService 提交新增反馈时，以已提交的 `usage.model_turns` 唯一赋值。没有模型决策的前置反馈保持空值，不参与重复模型决策判断。下游不得从反馈条数、工具数量或 action ID 推测尝试次数。

同一动作种类、失败原因和计划版本下，至少两个不同决策回合被拒绝才触发既有停止保护。成功观察后的进展边界保持原状。字段随 Journal 的原反馈保存，服务重建后仍保留回合归属；不另存派生计数，不修改执行事实或赋予工具权限。

## Complexity Justification

新增一个可空正整数事实字段，无新类、表、Port、后台任务或第二执行链。旧 Journal 只有扁平输入和累计回合，不能确定同批反馈的归属，因此该字段不能从原 canonical facts 唯一重建。唯一写入口为 ConversationService._commit，生产消费者为下一回合的重复反馈检查。删除归属或恢复按条计数会使同轮参数纠错 Contract 失败。

## 外部参考与证据

机制核对采用两个独立 A 级实现：[OpenAI Agents SDK](https://github.com/openai/openai-agents-python/blob/89c02c828ee8510fe9a84ee6675608193aa13b02/docs/running_agents.md#the-agent-loop) 和 [Gemini CLI](https://github.com/google-gemini/gemini-cli/blob/55b495d6db1794bf5b7f37a9bc03ebcab5103673/packages/core/src/core/client.ts)。工具结果回到下一模型回合，循环限制与工具并发数量分离；项目反例决定是否需要修复，外部机制不替代验收。

同轮修复与跨轮停止的 Contract、Journal 重启反事实和恢复状态的真实模型检查已执行；模型获得下一次决策机会后仍重复旧计划。两次同入口 Product E2E 因预算边界失败，未证明完整交付；不得否定已成立的计数修正，也不得据此声称产品完成。命令、实际结果和成本由推进记录维护。

## 未采用方案、迁移与退出条件

不提高重试次数、不丢弃同批反馈、不让模型自报回合、不删除合法失败出口，也不让 Verifier 负责下一动作。旧条数计数被直接替换，无 flag 或 fallback。

上线前不存在需兼容的生产 Journal 数据契约；新增运行直接写入回合。旧实验 Journal 只用于显式离线恢复，可按封存的逐次 Journal 还原，不凭累计总数猜测；未经还原的历史模型反馈不能作为新的重复决策证据。若发生模型反馈不能被唯一绑定、恢复后失去停止保护或真实 target 出现因果回归，撤回相关实现并重新定位，不保留双轨。

# GPT Researcher A2A 委派

GPT Researcher 是 Conversation 可选择的外部 Agent 执行资源。父 Conversation 拥有用户目标、下一步决策和最终交付；AgentGateway 拥有提交、远端生命周期、执行结果与 Artifact 引用。

## 当前链路

```text
中文用户目标
  -> Conversation 物化已装配且可用的 Agent 动作
  -> 模型提出 agent_id、bounded_sub_goal、预期产物与预算
  -> Application 校验能力与委派边界
  -> AgentTask + DelegationGrant + 稳定 submission_key
  -> AgentGateway 提交与轮询
  -> 子级状态、ArtifactRef 与有界内容进入 ActionObservation
  -> 父 Conversation 判断补证、综合与最终交付
  -> 适用 Verification 与 Completion
```

真实消费者位于 [ConversationService](../../src/personal_agent/application/conversation/service.py)，原生动作由 [model_actions.py](../../src/personal_agent/application/conversation/model_actions.py)投影；执行与作用域由 [AgentGateway](../../src/personal_agent/agents/gateway.py)和 [Agent 契约](../../src/personal_agent/kernel/contracts/agent.py)约束。配置与外部服务启动见 [env.md](../env.md#gpt-researcher-a2a-配置)。

## 提交、预算与恢复

父级从已准入委派构造 `AgentTask` 和 `DelegationGrant`，以运行引用与 `action_id` 派生稳定提交键。Gateway 的 durable submission 保护重复提交，事实与恢复规则见 [ADR 0004](../adr/0004-durable-agent-submission-and-artifact-reference.md)。

当前父级等待子任务直到终态或该委派的时间预算耗尽；超时时通过 Gateway 终止等待并返回执行状态。子级 Artifact 按父级身份与 owner 读取，有界摘录和完整内容引用一起交回。它们不能自动成为长期知识或父级完成事实。

能力未装配或不可用时，Application 返回明确反馈。模型的 Agent 选择、Gateway 的授权和实际远端结果分别记录；拒绝后不能由执行器静默替换 provider 或改写子目标。

## 证据与交付

A2A 响应可解析只证明协议形状；子任务终止与有 Artifact 只证明远端执行结果。父级按原用户要求核对来源、覆盖、时效和冲突，必要时继续读取或核验，再提交唯一最终答复。具体验收由[核验专题](../topics/verification-and-completion.md)拥有。

当前正式用户结果、失败分布和配置身份由[评测盘点](../evals/02-current-case-inventory.md)维护；历史委派成功不能外推到当前模型和配置。现行验证分工见 [QLT](../devSpec/quality-security.md#1-测试职责与覆盖)，历史单元测试只读保留。

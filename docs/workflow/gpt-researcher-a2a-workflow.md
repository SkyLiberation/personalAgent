# GPT Researcher A2A 委派

GPT Researcher 作为 Agent capability 注册，不是固定 `gpt_researcher_a2a` workflow。用户明确点名 provider 时，Task Analyzer 形成 required provider ResourceHint；未点名时，Executive 只表达 provider-neutral delegate requirement。

## 链路

```text
Task Goal
  -> Executive chooses delegate
  -> SubtaskSpec(goal, deliverable, constraints, evidence policy, budget)
  -> CapabilityResolver selects Agent capability
  -> AgentGateway
       create AgentRun
       dispatch / poll / stream / cancel
       collect AgentEvent + AgentArtifact
  -> unverified Observation
  -> Executive verifies or gathers independent evidence
  -> GoalVerifier / CompletionVerifier
```

AgentGateway 管理 transport、生命周期、超时、取消、审计和数据外发边界。外部 Agent 不能修改主 Ledger、选择主任务的下一个 Goal、调用主 Agent 的高风险工具或宣布主任务完成。

## 信任边界

A2A schema 通过只证明结构可解析，不证明报告事实正确。`AgentArtifact` 默认 `unverified`，主 Agent 必须按 Goal criterion 检查来源、覆盖、冲突和时效；必要时再执行 acquire/verify 动作。

## Provider Binding

- 用户明确要求 GPT Researcher：required provider，缺失时澄清或报告 unavailable；
- 用户只要求深度研究：Resolver 可在符合 delegate requirement 的 Agent 之间选择；
- provider denied：不能静默改用另一 Agent 冒充用户点名结果。

## 验证

关键回归位于 `tests/test_agent_gateway.py`、`tests/test_gpt_researcher_a2a_binding.py` 与 agent gateway/E2E capability suites。

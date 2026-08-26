# AGENT-RUN-TIMEOUT-FACT-001 消融

`consumer.patch` 只把 Conversation 在委托预算到期时的生产消费点从 `AgentGateway.timeout()` 恢复为 `AgentGateway.cancel()`。补丁不修改用户输入、模型 Proposal、时间预算、外部 Agent、Gateway 实现、状态类型或评测断言。

对当前代码应用补丁后，以下 Application Use Case 断言应重新观察到 `cancelled`，从而失败：

```powershell
uv run pytest tests/test_conversation_interaction.py::test_delegated_agent_budget_expiry_is_observed_as_timeout_failure -q
```

该消融只证明预算到期必须消费 timeout 写入口，不证明 GPT Researcher 能在预算内交付报告，也不证明服务提供方 usage 已被计量。

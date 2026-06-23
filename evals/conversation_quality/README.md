# Conversation Quality Golden Set

多轮会话评测以完整 conversation case 为最小单元。同一 case 的所有 entry
复用一个 `session_id`，HITL 补充通过 `resume_entry` 沿原 `run_id/thread_id`
恢复，不会被降级成新的单轮请求。

测试分为契约/集成测试与 Golden Test：

```powershell
# 纯函数 scorer + 人工评审 trace，无 DB/LLM
uv run pytest evals/conversation_quality/test_metrics.py `
  evals/conversation_quality/test_conversation_gate.py -q

# 真实 LangGraph/Postgres + 确定性 router stub
uv run pytest evals/conversation_quality/test_conversation_runtime_gate.py -q

# Golden Test：真实 router LLM + 真实 runtime
uv run pytest evals/conversation_quality/test_conversation_real_gate.py -v
```

Golden Test 不需要额外功能开关；LLM 与 Postgres 配置齐全时直接运行，缺少
真实环境配置时 skip。前两组测试用于验证 scorer 和系统契约，不作为 Golden
质量结果。

当前 8 条 case 覆盖：同 thread 连续 entry、代词追问、clarify→resume、
clarify→reject、总结历史、话题切换、写后即查、问答后 solidify。

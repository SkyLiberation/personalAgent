# INVESTIGATION-AGENT-GOAL-BINDING-001 消融

`consumer.patch` 只撤销 accepted SubGoal 到远端 Agent 任务的确定性编译与 Admission
防绕过消费点，并恢复模型对 `_AgentOperationDraft.bounded_sub_goal` 的写入。它保留
canonical 编译函数、accepted Plan、Agent 选择、预算、A2A Adapter、Verifier 和测试输入。

```powershell
git apply --check evals/ablations/investigation_agent_goal_binding_001/consumer.patch
git apply evals/ablations/investigation_agent_goal_binding_001/consumer.patch
uv run pytest -q tests/test_investigation_project_model_ports.py -k "compiles_agent_goal_from_accepted_subgoal or rejects_agent_goal_outside_accepted_subgoal"
git apply -R evals/ablations/investigation_agent_goal_binding_001/consumer.patch
```

预期消融后两项断言失败：生产 Proposer 再次要求模型提供目标，ID-only 目标再次绕过
Admission。恢复 patch 后两项通过。该消融只证明命令绑定机制不可省略，不替代远端
Artifact 与 SubGoalOutcome 的真实 Provider target。

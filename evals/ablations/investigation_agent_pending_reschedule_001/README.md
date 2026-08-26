# INVESTIGATION-AGENT-PENDING-RESCHEDULE-001 消融

本目录冻结“外部 Agent 结果仍为 pending 时，continuation 必须消费已有队列 `due_at`”的单变量消融。

`consumer.patch` 只删除 `InvestigationProjectService.process()` 从 `yield_for_external` 到 `defer_seconds` 的消费；`ProjectExecutionPolicy.external_wait_retry_seconds`、注入时钟、AgentRun、预算、队列、幂等键和业务事实保持不变。

执行方式：

```powershell
git apply evals/ablations/investigation_agent_pending_reschedule_001/consumer.patch
uv run pytest tests/test_investigation_project_lifecycle.py::test_pending_agent_result_yields_the_current_process_cycle -q
git apply -R evals/ablations/investigation_agent_pending_reschedule_001/consumer.patch
uv run pytest tests/test_investigation_project_lifecycle.py::test_pending_agent_result_yields_the_current_process_cycle -q
```

消融态必须重新出现 continuation 立即可 lease；恢复候选后，continuation 的 `due_at` 至少比入队时间晚 4.5 秒、立即 lease 返回空，并且同一 AgentRun 的第二次 reconcile 仍能完成 Project。

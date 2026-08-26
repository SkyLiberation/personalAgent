# INVESTIGATION-WORKER-FAIRNESS-001 消融

`consumer.patch` 只撤去调查 worker 对单次队列租约 `max_cycles=1` 的消费，保留 Project 状态机、事件、队列、租约、恢复和所有 Provider 配置。应用后，`ProcessInvestigationProject` 恢复默认 100 cycles，`test_investigation_worker_leases_only_one_project_cycle_at_a_time` 必须失败；反向应用后必须恢复通过。

该检查属于 Runtime Conformance，只证明调度时间片的生产消费点命中预声明变量。它不证明 20 个真实后台项目已经交付，也不能用来提高观察窗口或替代产品 target。

```powershell
git apply --check evals/ablations/investigation_worker_fairness_001/consumer.patch
git apply evals/ablations/investigation_worker_fairness_001/consumer.patch
uv run pytest -q tests/test_worker_queue.py::test_investigation_worker_leases_only_one_project_cycle_at_a_time
git apply --reverse evals/ablations/investigation_worker_fairness_001/consumer.patch
```
